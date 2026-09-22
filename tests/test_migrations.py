"""
Migration round-trip safety for b7f2a91c40d3 (multi-company scoping).

That migration clones shared workers comp codes so each company owns a copy.
An earlier version's downgrade() dropped company_id but left the clones behind,
so a later upgrade cloned them again -- codes grew 2 -> 4 -> 6 -> 10 across
three up/down cycles. These tests pin the fix: downgrade collapses duplicates,
upgrade refuses to double up, and no employee's workers comp rate ever changes.
"""
import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

import models  # noqa: F401 -- registers all models on Base.metadata
from models.base import Base

PREVIOUS_REVISION = "c52a89761498"
MULTI_COMPANY_REVISION = "b7f2a91c40d3"


def _alembic_config(db_path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    # env.py overwrites sqlalchemy.url from config.settings, so point the app
    # settings at the temp DB too.
    from config import settings
    settings.database_url = f"sqlite:///{db_path}"
    return cfg


@pytest.fixture()
def legacy_db(tmp_path):
    """A database at the pre-multi-company revision, with a shared WC code.

    Code 8810 is referenced by employees in BOTH companies (so the migration
    must clone it); 9999 is referenced by nobody (so it is cloned to every
    company). That is the exact shape that used to compound.
    """
    db_path = tmp_path / "legacy.db"

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    con = sqlite3.connect(db_path)
    c = con.cursor()
    # Restore the pre-migration shape: workers comp codes without company_id.
    c.executescript(
        """
        DROP TABLE workers_comp_codes;
        CREATE TABLE workers_comp_codes (
            id INTEGER NOT NULL PRIMARY KEY,
            ncci_code VARCHAR(10) NOT NULL,
            description VARCHAR(200) NOT NULL,
            rate_per_100_wages NUMERIC(7,4)
        );
        DROP TABLE IF EXISTS user_companies;
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        );
        """
    )
    c.execute("INSERT INTO companies (id,name,state,pay_frequency) VALUES (1,'Alpha','OK','biweekly')")
    c.execute("INSERT INTO companies (id,name,state,pay_frequency) VALUES (2,'Beta','OK','biweekly')")
    c.execute("INSERT INTO workers_comp_codes VALUES (1,'8810','Clerical',0.25)")
    c.execute("INSERT INTO workers_comp_codes VALUES (2,'9999','Unused',1.0)")
    for emp_id, company_id in ((1, 1), (2, 2)):
        c.execute(
            "INSERT INTO employees "
            "(id,company_id,first_name,last_name,state,status,employment_type,"
            " pay_rate,flsa_exempt,workers_comp_code_id) "
            "VALUES (?,?,'Emp','X','OK','active','hourly',20,0,1)",
            (emp_id, company_id),
        )
    for uid, name, role, active in (
        (1, "boss", "admin", 1), (2, "prep", "preparer", 1), (3, "gone", "preparer", 0),
    ):
        c.execute(
            "INSERT INTO users (id,username,hashed_password,role,is_active) VALUES (?,?,'x',?,?)",
            (uid, name, role, active),
        )
    c.execute("DELETE FROM alembic_version")
    c.execute("INSERT INTO alembic_version VALUES (?)", (PREVIOUS_REVISION,))
    con.commit()
    con.close()
    return db_path


def _codes(db_path) -> list[tuple]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT ncci_code, description, rate_per_100_wages FROM workers_comp_codes "
        "ORDER BY ncci_code, description"
    ).fetchall()
    con.close()
    return rows


def _employee_rates(db_path) -> dict:
    """Each employee's effective WC rate -- must survive every migration step."""
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT e.id, w.ncci_code, w.rate_per_100_wages "
        "FROM employees e JOIN workers_comp_codes w ON w.id = e.workers_comp_code_id "
        "ORDER BY e.id"
    ).fetchall()
    con.close()
    return {r[0]: (r[1], r[2]) for r in rows}


class TestMultiCompanyRoundTrip:
    def test_upgrade_clones_shared_code_per_company(self, legacy_db):
        cfg = _alembic_config(legacy_db)
        command.upgrade(cfg, MULTI_COMPANY_REVISION)

        con = sqlite3.connect(legacy_db)
        rows = con.execute(
            "SELECT company_id, ncci_code FROM workers_comp_codes ORDER BY company_id, ncci_code"
        ).fetchall()
        mismatched = con.execute(
            "SELECT COUNT(*) FROM employees e JOIN workers_comp_codes w "
            "ON w.id = e.workers_comp_code_id WHERE w.company_id != e.company_id"
        ).fetchone()[0]
        con.close()

        # Both codes exist once per company: 2 codes x 2 companies.
        assert rows == [(1, "8810"), (1, "9999"), (2, "8810"), (2, "9999")]
        assert mismatched == 0

    def test_downgrade_restores_original_code_count(self, legacy_db):
        """The defect: downgrade used to leave clones behind."""
        before = _codes(legacy_db)
        cfg = _alembic_config(legacy_db)

        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        command.downgrade(cfg, PREVIOUS_REVISION)

        assert _codes(legacy_db) == before

    def test_repeated_cycles_do_not_compound(self, legacy_db):
        """Codes grew 2 -> 4 -> 6 -> 10 before the fix. Must stay flat now."""
        cfg = _alembic_config(legacy_db)
        original = _codes(legacy_db)

        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        after_first_upgrade = _codes(legacy_db)

        for _ in range(3):
            command.downgrade(cfg, PREVIOUS_REVISION)
            assert _codes(legacy_db) == original
            command.upgrade(cfg, MULTI_COMPANY_REVISION)
            assert _codes(legacy_db) == after_first_upgrade

    def test_employee_rates_unchanged_across_cycles(self, legacy_db):
        """Cloning and collapsing must never alter an employee's WC rate --
        that is what keeps already-approved historical paychecks reconcilable."""
        cfg = _alembic_config(legacy_db)
        original_rates = _employee_rates(legacy_db)

        for _ in range(3):
            command.upgrade(cfg, MULTI_COMPANY_REVISION)
            assert _employee_rates(legacy_db) == original_rates
            command.downgrade(cfg, PREVIOUS_REVISION)
            assert _employee_rates(legacy_db) == original_rates

    def test_upgrade_is_idempotent_against_leftover_clones(self, legacy_db):
        """Even if a hand-rolled rollback leaves clones behind, upgrade must
        reuse them rather than minting a second copy."""
        cfg = _alembic_config(legacy_db)
        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        expected = _codes(legacy_db)

        # Simulate a partial rollback: drop the version marker and the column,
        # leaving the cloned rows in place.
        con = sqlite3.connect(legacy_db)
        con.executescript(
            """
            CREATE TABLE wc_tmp AS
                SELECT id, ncci_code, description, rate_per_100_wages FROM workers_comp_codes;
            DROP TABLE workers_comp_codes;
            ALTER TABLE wc_tmp RENAME TO workers_comp_codes;
            DROP TABLE IF EXISTS user_companies;
            """
        )
        con.execute("DELETE FROM alembic_version")
        con.execute("INSERT INTO alembic_version VALUES (?)", (PREVIOUS_REVISION,))
        con.commit()
        con.close()

        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        assert _codes(legacy_db) == expected


class TestNullRateCodes:
    """A NULL rate must group with other NULLs and never with a numeric rate.

    The collapse helper relies on SQLite treating NULLs as equal under GROUP BY
    and on the null-safe IS operator, rather than an IFNULL(x, -1) sentinel that
    would wrongly merge a genuine rate of -1 with an unrated code.
    """

    def _seed(self, db_path, rows):
        con = sqlite3.connect(db_path)
        con.execute("DELETE FROM employees")
        con.execute("DELETE FROM workers_comp_codes")
        for row in rows:
            con.execute(
                "INSERT INTO workers_comp_codes "
                "(id, ncci_code, description, rate_per_100_wages) VALUES (?,?,?,?)",
                row,
            )
        con.commit()
        con.close()

    def test_null_rated_duplicates_collapse(self, legacy_db):
        self._seed(legacy_db, [
            (1, "8810", "Clerical", None),
            (2, "8810", "Clerical", None),
        ])
        cfg = _alembic_config(legacy_db)
        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        command.downgrade(cfg, PREVIOUS_REVISION)

        # The two NULL-rated rows are the same code and must merge into one.
        assert _codes(legacy_db) == [("8810", "Clerical", None)]

    def test_null_rate_never_merges_with_negative_one(self, legacy_db):
        self._seed(legacy_db, [
            (1, "8810", "Clerical", None),
            (2, "8810", "Clerical", -1),
        ])
        cfg = _alembic_config(legacy_db)
        command.upgrade(cfg, MULTI_COMPANY_REVISION)
        command.downgrade(cfg, PREVIOUS_REVISION)

        # Distinct rates -> distinct codes, even though -1 was the old sentinel.
        # Order-insensitive: _codes sorts on ncci/description only, so rows that
        # tie there come back in rowid order.
        assert sorted(_codes(legacy_db), key=lambda r: (r[2] is None, r[2])) == [
            ("8810", "Clerical", -1),
            ("8810", "Clerical", None),
        ]


class TestUserCompanyBackfill:
    def test_active_non_admins_get_every_company(self, legacy_db):
        cfg = _alembic_config(legacy_db)
        command.upgrade(cfg, MULTI_COMPANY_REVISION)

        con = sqlite3.connect(legacy_db)
        rows = con.execute(
            "SELECT u.username, uc.company_id FROM user_companies uc "
            "JOIN users u ON u.id = uc.user_id ORDER BY u.username, uc.company_id"
        ).fetchall()
        con.close()

        # 'boss' is admin (bypasses scope, no rows); 'gone' is inactive
        # (deliberately no rows -- reactivation requires a fresh grant).
        assert rows == [("prep", 1), ("prep", 2)]
