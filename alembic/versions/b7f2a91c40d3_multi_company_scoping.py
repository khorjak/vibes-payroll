"""multi-company: user_companies table and per-company workers comp codes

Revision ID: b7f2a91c40d3
Revises: c52a89761498
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7f2a91c40d3'
down_revision: Union[str, None] = 'c52a89761498'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _collapse_duplicate_codes(conn) -> None:
    """Merge workers comp codes that are identical on (ncci, description, rate).

    Used by BOTH directions. Upgrade calls it first so that clones left behind
    by an interrupted or hand-rolled rollback are absorbed instead of cloned
    again; downgrade calls it so dropping company_id is a true inverse rather
    than leaving duplicates for the next upgrade to multiply.

    Company is deliberately NOT part of the grouping key: the whole point is to
    collapse copies that only ever differed by which company owned them.
    Employees are repointed at the survivor first, so no FK is left dangling,
    and rates are never touched -- historical paychecks stay reconcilable.
    """
    # GROUP BY already treats NULL rates as equal to one another, and the
    # lookup below uses SQLite's null-safe IS -- so no sentinel value is
    # needed. (An IFNULL(rate, -1) sentinel would wrongly group a real rate of
    # -1 together with NULL.)
    groups = conn.execute(sa.text(
        "SELECT ncci_code, description, rate_per_100_wages, MIN(id) AS keep_id "
        "FROM workers_comp_codes "
        "GROUP BY ncci_code, description, rate_per_100_wages "
        "HAVING COUNT(*) > 1"
    )).fetchall()

    for group in groups:
        dupes = [
            r[0] for r in conn.execute(
                sa.text(
                    "SELECT id FROM workers_comp_codes "
                    "WHERE ncci_code = :ncci AND description = :descr "
                    "AND rate_per_100_wages IS :rate "
                    "AND id != :keep ORDER BY id"
                ),
                {"ncci": group.ncci_code, "descr": group.description,
                 "rate": group.rate_per_100_wages, "keep": group.keep_id},
            ).fetchall()
        ]
        if not dupes:
            continue
        conn.execute(
            sa.text(
                "UPDATE employees SET workers_comp_code_id = :keep "
                "WHERE workers_comp_code_id IN :dupes"
            ).bindparams(sa.bindparam("dupes", expanding=True)),
            {"keep": group.keep_id, "dupes": dupes},
        )
        conn.execute(
            sa.text("DELETE FROM workers_comp_codes WHERE id IN :dupes")
            .bindparams(sa.bindparam("dupes", expanding=True)),
            {"dupes": dupes},
        )


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. user <-> company assignments -------------------------------
    op.create_table(
        'user_companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'company_id', name='uq_user_company'),
    )
    op.create_index(op.f('ix_user_companies_company_id'), 'user_companies', ['company_id'], unique=False)
    op.create_index(op.f('ix_user_companies_user_id'), 'user_companies', ['user_id'], unique=False)

    # Preserve today's behaviour: every existing non-admin user keeps access to
    # every existing company. Admins bypass this table entirely, so they get no
    # rows. New restrictions become a deliberate admin action rather than a
    # surprise lockout on upgrade.
    conn.execute(sa.text("""
        INSERT INTO user_companies (user_id, company_id)
        SELECT u.id, c.id FROM users u CROSS JOIN companies c
        WHERE u.role != 'admin' AND u.is_active = 1
    """))

    # --- 2. workers comp codes become per-company ----------------------
    # Codes were global but presented per-company, so editing a rate under one
    # company silently changed every other company's payroll cost.
    op.add_column('workers_comp_codes', sa.Column('company_id', sa.Integer(), nullable=True))
    # Absorb any clones a previous downgrade/upgrade cycle left behind before
    # cloning again -- otherwise codes compound on every cycle.
    _collapse_duplicate_codes(conn)

    companies = [r[0] for r in conn.execute(
        sa.text("SELECT id FROM companies ORDER BY id")
    ).fetchall()]
    codes = conn.execute(sa.text(
        "SELECT id, ncci_code, description, rate_per_100_wages FROM workers_comp_codes ORDER BY id"
    )).fetchall()

    if not companies:
        # Nothing can reference these; a NOT NULL FK has no valid value.
        conn.execute(sa.text("DELETE FROM workers_comp_codes"))
    else:
        for code in codes:
            used = [r[0] for r in conn.execute(
                sa.text(
                    "SELECT DISTINCT company_id FROM employees "
                    "WHERE workers_comp_code_id = :cid ORDER BY company_id"
                ),
                {"cid": code.id},
            ).fetchall()]
            # Unreferenced codes are cloned to every company so each company's
            # picker keeps the full catalogue it sees today.
            targets = used if used else companies

            conn.execute(
                sa.text("UPDATE workers_comp_codes SET company_id = :co WHERE id = :cid"),
                {"co": targets[0], "cid": code.id},
            )
            # Referenced by several companies: clone per extra company and
            # repoint those employees. Rates are copied verbatim, so no
            # historical paycheck figure changes.
            for company_id in targets[1:]:
                conn.execute(
                    sa.text(
                        "INSERT INTO workers_comp_codes "
                        "(company_id, ncci_code, description, rate_per_100_wages) "
                        "VALUES (:co, :ncci, :descr, :rate)"
                    ),
                    {"co": company_id, "ncci": code.ncci_code,
                     "descr": code.description, "rate": code.rate_per_100_wages},
                )
                new_id = conn.execute(sa.text("SELECT last_insert_rowid()")).scalar()
                conn.execute(
                    sa.text(
                        "UPDATE employees SET workers_comp_code_id = :new_id "
                        "WHERE workers_comp_code_id = :old_id AND company_id = :co"
                    ),
                    {"new_id": new_id, "old_id": code.id, "co": company_id},
                )

    # SQLite cannot add a NOT NULL column with an FK in one step -- added
    # nullable above, backfilled, now tightened inside a table rebuild.
    with op.batch_alter_table('workers_comp_codes') as batch_op:
        batch_op.alter_column('company_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            'fk_workers_comp_codes_company_id', 'companies', ['company_id'], ['id'],
        )
    op.create_index(
        op.f('ix_workers_comp_codes_company_id'), 'workers_comp_codes', ['company_id'], unique=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Collapse the clones upgrade() created. Once company_id is gone the codes
    # are global again, so rows identical on (ncci, description, rate) ARE the
    # same code -- merging them is the true inverse, not a loss.
    _collapse_duplicate_codes(conn)

    op.drop_index(op.f('ix_workers_comp_codes_company_id'), table_name='workers_comp_codes')
    with op.batch_alter_table('workers_comp_codes') as batch_op:
        batch_op.drop_constraint('fk_workers_comp_codes_company_id', type_='foreignkey')
        batch_op.drop_column('company_id')
    op.drop_index(op.f('ix_user_companies_user_id'), table_name='user_companies')
    op.drop_index(op.f('ix_user_companies_company_id'), table_name='user_companies')
    op.drop_table('user_companies')
