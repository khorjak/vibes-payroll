"""Workers comp coverage verification: flag employees paid with no WC code on file."""
from datetime import date

import pytest

from models.employee import Employee
from models.payroll import PayPeriod
from tests.test_reports import _run_payroll

NOTE = "No workers comp code on file"


def _period(db, company, status="open"):
    pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                   pay_date=date(2026, 5, 20), frequency="biweekly", status=status)
    db.add(pp)
    db.commit()
    return pp


class TestPeriodPageWarning:
    def test_lists_active_employee_without_code(self, client, db, company, salaried_employee):
        pp = _period(db, company)
        page = client.get(f"/payroll/{pp.id}").text
        assert NOTE in page
        assert "Jane Smith" in page
        assert f"/employees/{salaried_employee.id}/edit" in page

    def test_employee_with_code_not_listed(self, client, db, company, salaried_employee, wc_code):
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        assert NOTE not in client.get(f"/payroll/{_period(db, company).id}").text

    def test_only_the_uncovered_employee_is_named(self, client, db, company, salaried_employee,
                                                  hourly_employee, wc_code):
        hourly_employee.workers_comp_code_id = wc_code.id
        db.commit()
        page = client.get(f"/payroll/{_period(db, company).id}").text
        assert "Jane Smith" in page and "Bob Jones" not in page

    @pytest.mark.parametrize("status", ["terminated", "on_leave"])
    def test_inactive_employees_not_listed(self, client, db, company, salaried_employee, status):
        salaried_employee.status = status
        db.commit()
        assert NOTE not in client.get(f"/payroll/{_period(db, company).id}").text

    def test_other_companys_employee_not_listed(self, client, db, company, other_employee):
        assert NOTE not in client.get(f"/payroll/{_period(db, company).id}").text

    def test_shown_on_draft_period(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee, approve=False)
        assert pp.status == "draft"
        assert NOTE in client.get(f"/payroll/{pp.id}").text

    @pytest.mark.parametrize("status", ["approved", "paid"])
    def test_not_shown_once_locked(self, client, db, company, salaried_employee, status):
        assert NOTE not in client.get(f"/payroll/{_period(db, company, status).id}").text

    def test_warning_does_not_block_calculate_or_approve(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee)
        assert pp.status == "approved"

    def test_clears_once_a_code_is_assigned(self, client, db, company, salaried_employee, wc_code):
        pp = _period(db, company)
        assert NOTE in client.get(f"/payroll/{pp.id}").text
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        assert NOTE not in client.get(f"/payroll/{pp.id}").text


class TestProfileNote:
    def test_active_without_code_flagged(self, client, salaried_employee):
        assert "coverage is not verified" in client.get(f"/employees/{salaried_employee.id}").text

    def test_with_code_not_flagged(self, client, db, salaried_employee, wc_code):
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        assert "coverage is not verified" not in client.get(f"/employees/{salaried_employee.id}").text

    def test_terminated_not_flagged(self, client, db, salaried_employee):
        salaried_employee.status = "terminated"
        db.commit()
        assert "coverage is not verified" not in client.get(f"/employees/{salaried_employee.id}").text


class TestWorkersCompReportNamesEmployees:
    def _get(self, client, company):
        return client.get(f"/reports/workers-comp?company_id={company.id}&year=2026").text

    def test_unclassified_row_names_uncovered_employees(self, client, db, company,
                                                        salaried_employee, hourly_employee):
        _run_payroll(client, db, company, salaried_employee)
        page = self._get(client, company)
        assert "Unclassified" in page
        assert "No workers comp code on file for: " in page
        assert "Jane Smith" in page

    def test_names_are_sorted_and_comma_separated(self, client, db, company,
                                                  salaried_employee, hourly_employee):
        pp = _run_payroll(client, db, company, salaried_employee, approve=False)
        from models.payroll import Timesheet
        db.add(Timesheet(employee_id=hourly_employee.id, pay_period_id=pp.id, regular_hours=40))
        db.commit()
        client.post(f"/payroll/{pp.id}/calculate")
        client.post(f"/payroll/{pp.id}/approve")
        assert "Bob Jones, Jane Smith" in self._get(client, company)

    def test_covered_employee_not_named(self, client, db, company, salaried_employee, wc_code):
        salaried_employee.workers_comp_code_id = wc_code.id
        db.commit()
        _run_payroll(client, db, company, salaried_employee)
        page = self._get(client, company)
        assert "8810" in page
        assert "No workers comp code on file for" not in page

    def test_consolidated_names_each_companys_employees(self, client, db, company, second_company,
                                                       salaried_employee, other_employee):
        _run_payroll(client, db, company, salaried_employee)
        _run_payroll(client, db, second_company, other_employee)
        page = client.get("/reports/workers-comp?company_id=-1&year=2026").text
        assert "Jane Smith" in page and "Rival Person" in page
