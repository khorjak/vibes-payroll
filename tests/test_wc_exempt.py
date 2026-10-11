"""Workers comp exempt flag: deliberately uncovered employees."""
import importlib.util
from datetime import date

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from models.employee import Employee
from models.payroll import PayPeriod, PaycheckLine
from models.workers_comp import WorkersCompCode
from services.payroll_service import draft_paycheck
from tests.test_reports import _run_payroll
from tests.test_payroll_runs import _load_employee, _load_pay_period

NOTE = "No workers comp code on file"


def _form(company, **over):
    data = {"company_id": company.id, "first_name": "Alice", "last_name": "Walker",
            "employment_type": "hourly", "pay_rate": "20.00", "status": "active", "state": "OK"}
    data.update(over)
    return data


class TestFormSaving:
    def test_create_exempt_clears_the_code(self, client, db, company, wc_code):
        r = client.post("/employees/new", data=_form(
            company, workers_comp_exempt="on", workers_comp_code_id=str(wc_code.id)))
        assert r.status_code == 303
        emp = db.query(Employee).one()
        assert emp.workers_comp_exempt is True
        assert emp.workers_comp_code_id is None

    def test_default_is_not_exempt(self, client, db, company):
        client.post("/employees/new", data=_form(company))
        assert db.query(Employee).one().workers_comp_exempt is False

    def test_update_to_exempt_clears_existing_code(self, client, db, company, salaried_employee, wc_code):
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        r = client.post(f"/employees/{salaried_employee.id}/edit", data=_form(
            company, employment_type="salaried", pay_rate="65000", workers_comp_exempt="on"))
        assert r.status_code == 303
        db.refresh(salaried_employee)
        assert salaried_employee.workers_comp_exempt is True
        assert salaried_employee.workers_comp_code_id is None

    def test_update_unchecking_exempt_and_assigning_a_code(self, client, db, company, salaried_employee, wc_code):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        client.post(f"/employees/{salaried_employee.id}/edit", data=_form(
            company, employment_type="salaried", pay_rate="65000",
            workers_comp_code_id=str(wc_code.id)))
        db.refresh(salaried_employee)
        assert salaried_employee.workers_comp_exempt is False
        assert salaried_employee.workers_comp_code_id == wc_code.id

    def test_exempt_ignores_a_code_from_another_company(self, client, db, company, second_company):
        foreign = WorkersCompCode(company_id=second_company.id, ncci_code="8810",
                                  description="Clerical", rate_per_100_wages=0.25)
        db.add(foreign)
        db.commit()
        r = client.post("/employees/new", data=_form(
            company, workers_comp_exempt="on", workers_comp_code_id=str(foreign.id)))
        assert r.status_code == 303   # dropped, not validated
        assert db.query(Employee).one().workers_comp_code_id is None

    def test_not_exempt_still_rejects_a_foreign_code(self, client, db, company, second_company):
        foreign = WorkersCompCode(company_id=second_company.id, ncci_code="8810",
                                  description="Clerical", rate_per_100_wages=0.25)
        db.add(foreign)
        db.commit()
        r = client.post("/employees/new", data=_form(company, workers_comp_code_id=str(foreign.id)))
        assert r.status_code == 422

    def test_edit_form_shows_checkbox_checked(self, client, db, salaried_employee):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        page = client.get(f"/employees/{salaried_employee.id}/edit").text
        assert 'name="workers_comp_exempt"' in page
        assert "checked" in page.split('name="workers_comp_exempt"', 1)[1].split(">", 1)[0]

    def test_new_form_shows_unchecked_checkbox(self, client):
        page = client.get("/employees/new").text
        assert 'name="workers_comp_exempt"' in page


class TestNoWarningsOrCost:
    def test_period_warning_skips_exempt(self, client, db, company, salaried_employee):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                       pay_date=date(2026, 5, 20), frequency="biweekly", status="open")
        db.add(pp)
        db.commit()
        assert NOTE not in client.get(f"/payroll/{pp.id}").text

    def test_period_warning_still_lists_non_exempt(self, client, db, company, salaried_employee, hourly_employee):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                       pay_date=date(2026, 5, 20), frequency="biweekly", status="open")
        db.add(pp)
        db.commit()
        page = client.get(f"/payroll/{pp.id}").text
        assert "Bob Jones" in page and "Jane Smith" not in page

    def test_profile_shows_exempt_without_warning(self, client, db, salaried_employee):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        page = client.get(f"/employees/{salaried_employee.id}").text
        assert "Exempt" in page
        assert "coverage is not verified" not in page

    def test_no_workers_comp_cost_even_if_a_code_lingers(self, db, salaried_employee, wc_code, pay_period):
        salaried_employee.workers_comp_code_id = wc_code.id
        salaried_employee.workers_comp_exempt = True   # defensive: exempt wins over a stale code
        db.commit()
        pc = draft_paycheck(_load_employee(db, salaried_employee.id),
                            _load_pay_period(db, pay_period.id), None, db)
        assert pc.employer_workers_comp == 0
        assert db.query(PaycheckLine).filter_by(paycheck_id=pc.id, description="Workers Comp").count() == 0

    def test_covered_employee_still_costs(self, db, salaried_employee, wc_code, pay_period):
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        pc = draft_paycheck(_load_employee(db, salaried_employee.id),
                            _load_pay_period(db, pay_period.id), None, db)
        assert pc.employer_workers_comp > 0


class TestReport:
    def _get(self, client, company):
        return client.get(f"/reports/workers-comp?company_id={company.id}&year=2026").text

    def test_exempt_wages_get_their_own_row_with_no_premium(self, client, db, company, salaried_employee):
        salaried_employee.workers_comp_exempt = True
        db.commit()
        _run_payroll(client, db, company, salaried_employee)
        page = self._get(client, company)
        assert "EXEMPT" in page and "Exempt from workers comp" in page
        assert "$2,500.00" in page
        assert "Unclassified" not in page
        assert "No workers comp code on file for" not in page

    def test_exempt_separate_from_unclassified(self, client, db, company, salaried_employee, hourly_employee):
        from models.payroll import Timesheet
        salaried_employee.workers_comp_exempt = True
        db.commit()
        pp = _run_payroll(client, db, company, salaried_employee, approve=False)
        db.add(Timesheet(employee_id=hourly_employee.id, pay_period_id=pp.id, regular_hours=40))
        db.commit()
        client.post(f"/payroll/{pp.id}/calculate")
        client.post(f"/payroll/{pp.id}/approve")
        page = self._get(client, company)
        assert "Exempt from workers comp" in page and "Unclassified" in page
        assert "Bob Jones" in page and "Jane Smith" not in page.split("No workers comp code on file for:")[1]


def _migration():
    spec = importlib.util.spec_from_file_location(
        "wc_exempt_migration", "alembic/versions/e5a1c7b9d2f4_add_workers_comp_exempt_to_employees.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration:
    def test_revision_chain(self):
        mod = _migration()
        assert mod.down_revision == "d3e8f1a2b4c6"

    def test_upgrade_backfills_false_and_downgrade_drops(self, tmp_path):
        mod = _migration()
        engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
        with engine.begin() as conn:
            conn.execute(text("create table employees (id integer primary key, first_name text)"))
            conn.execute(text("insert into employees (id, first_name) values (1, 'Existing')"))
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
            assert conn.execute(text("select workers_comp_exempt from employees where id = 1")).scalar() == 0
            with Operations.context(MigrationContext.configure(conn)):
                mod.downgrade()
            cols = [r[1] for r in conn.execute(text("pragma table_info(employees)"))]
            assert "workers_comp_exempt" not in cols
            assert conn.execute(text("select first_name from employees")).scalar() == "Existing"
