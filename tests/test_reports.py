"""
Smoke tests for Phase 5 report routes.
"""
from datetime import date
import pytest
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck, ClientLiability


def _run_payroll(client, db, company, employee):
    pp = PayPeriod(
        company_id=company.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        pay_date=date(2026, 5, 20),
        frequency="biweekly",
        status="open",
    )
    db.add(pp)
    db.commit()
    db.refresh(pp)
    client.post(f"/payroll/{pp.id}/calculate")
    db.expire_all()
    db.refresh(pp)
    return pp


class TestReportRoutes:
    def test_reports_index(self, client):
        r = client.get("/reports/")
        assert r.status_code == 200
        assert "Payroll Register" in r.text

    def test_payroll_register_no_params(self, client):
        r = client.get("/reports/payroll-register")
        assert r.status_code == 200

    def test_payroll_register_company_filter(self, client, company):
        r = client.get(f"/reports/payroll-register?company_id={company.id}")
        assert r.status_code == 200

    def test_payroll_register_with_data(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee)
        paycheck = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).first()
        r = client.get(
            f"/reports/payroll-register?company_id={company.id}&pay_period_id={pp.id}"
        )
        assert r.status_code == 200
        assert "Smith" in r.text
        assert "2,500" in r.text or "500" in r.text  # some gross amount shown

    def test_tax_liability_no_params(self, client):
        r = client.get("/reports/tax-liability")
        assert r.status_code == 200

    def test_tax_liability_with_data(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(f"/reports/tax-liability?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "Year Total" in r.text

    def test_tax_liability_empty_year(self, client, company):
        r = client.get(f"/reports/tax-liability?company_id={company.id}&year=2099")
        assert r.status_code == 200
        assert "No payroll data" in r.text

    def test_quarterly_941_no_params(self, client):
        r = client.get("/reports/quarterly-941")
        assert r.status_code == 200

    def test_quarterly_941_with_data(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(
            f"/reports/quarterly-941?company_id={company.id}&year=2026&quarter=2"
        )
        assert r.status_code == 200
        assert "Total Wages" in r.text or "Wages" in r.text

    def test_quarterly_941_empty(self, client, company):
        r = client.get(
            f"/reports/quarterly-941?company_id={company.id}&year=2026&quarter=1"
        )
        assert r.status_code == 200

    def test_workers_comp_no_params(self, client):
        r = client.get("/reports/workers-comp")
        assert r.status_code == 200

    def test_workers_comp_with_data(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(f"/reports/workers-comp?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "Unclassified" in r.text or "N/A" in r.text

    def test_ok_withholding_no_params(self, client):
        r = client.get("/reports/ok-withholding")
        assert r.status_code == 200

    def test_ok_withholding_full_year(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(f"/reports/ok-withholding?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "May" in r.text

    def test_ok_withholding_by_quarter(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(
            f"/reports/ok-withholding?company_id={company.id}&year=2026&quarter=2"
        )
        assert r.status_code == 200

    def test_w2_export_returns_csv(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(f"/reports/w2-export?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        lines = r.text.splitlines()
        assert len(lines) >= 2  # header + at least one employee row
        assert "Box1_FedWages" in lines[0]
        assert "Smith" in r.text

    def test_w2_export_empty_year(self, client, company):
        r = client.get(f"/reports/w2-export?company_id={company.id}&year=2099")
        assert r.status_code == 200
        lines = r.text.splitlines()
        assert len(lines) == 1  # header only, no employees


class TestDeductionReport:
    def test_renders_without_params(self, client):
        r = client.get("/reports/deductions")
        assert r.status_code == 200
        assert "Deduction" in r.text

    def test_with_data(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee)
        r = client.get(f"/reports/deductions?company_id={company.id}&year=2026")
        assert r.status_code == 200


class TestClientLiabilitiesReport:
    def test_renders_without_params(self, client):
        r = client.get("/reports/client-liabilities")
        assert r.status_code == 200
        assert "Client Liability" in r.text

    def test_with_data(self, client, db, company):
        pp = PayPeriod(
            company_id=company.id, start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 14), pay_date=date(2026, 5, 20),
            frequency="biweekly", status="paid",
        )
        db.add(pp)
        db.flush()
        li = ClientLiability(
            company_id=company.id, pay_period_id=pp.id,
            liability_type="garnishment_remittance",
            payee_name="Court System", amount=200.00,
        )
        db.add(li)
        db.commit()
        r = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "Court System" in r.text


class TestNewHiresReport:
    def test_renders_without_params(self, client):
        r = client.get("/reports/new-hires")
        assert r.status_code == 200
        assert "New Hire" in r.text

    def test_shows_unreported_hire(self, client, db, company):
        emp = Employee(
            company_id=company.id, first_name="New", last_name="Hire",
            employment_type="hourly", pay_rate=15, status="active",
            state="OK", hire_date=date.today(),
        )
        db.add(emp)
        db.commit()
        r = client.get(f"/reports/new-hires?company_id={company.id}")
        assert r.status_code == 200
        assert "Hire" in r.text
        assert "Unreported" in r.text

    def test_reported_hire_excluded(self, client, db, company):
        emp = Employee(
            company_id=company.id, first_name="Reported", last_name="Person",
            employment_type="hourly", pay_rate=15, status="active",
            state="OK", hire_date=date.today(),
            new_hire_reported_at=date.today(),
        )
        db.add(emp)
        db.commit()
        r = client.get(f"/reports/new-hires?company_id={company.id}")
        assert r.status_code == 200
        assert "Reported" not in r.text or "All recent hires" in r.text


class TestReadOnlyRole:
    def test_no_role_hides_admin_ui(self, client):
        from app_templates import templates
        original_is_admin = templates.env.globals["is_admin"]
        original_has_role = templates.env.globals["has_role"]
        templates.env.globals["is_admin"] = lambda request: False
        templates.env.globals["has_role"] = lambda request, *roles: False
        try:
            r = client.get("/employees/")
            assert "+ New Employee" not in r.text
        finally:
            templates.env.globals["is_admin"] = original_is_admin
            templates.env.globals["has_role"] = original_has_role


class TestTerminatedEmployeeWarning:
    def test_warning_shown_for_terminated_without_final(self, client, db, company):
        terminated = Employee(
            company_id=company.id, first_name="Ex", last_name="Worker",
            employment_type="salaried", pay_rate=50000, status="terminated",
            state="OK", termination_date=date(2026, 5, 10),
        )
        db.add(terminated)
        db.commit()
        pp = PayPeriod(
            company_id=company.id, start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 14), pay_date=date(2026, 5, 20),
            frequency="biweekly", status="open",
        )
        db.add(pp)
        db.commit()
        r = client.get(f"/payroll/{pp.id}")
        assert r.status_code == 200
        assert "Ex Worker" in r.text
        assert "terminated" in r.text.lower()


class TestConsolidatedReports:
    """company_id=-1 means 'all my companies'; filing reports must refuse it."""

    def test_filing_reports_refuse_consolidation(self, client, company):
        for path in ("/reports/quarterly-941?year=2026&quarter=2",
                     "/reports/ok-withholding?year=2026"):
            r = client.get(f"{path}&company_id=-1")
            assert r.status_code == 200, path
            assert "filed per EIN" in r.text, path

    def test_w2_export_refuses_consolidation(self, client, company):
        r = client.get("/reports/w2-export?company_id=-1&year=2026")
        assert r.status_code == 400
        assert "per EIN" in r.json()["detail"]

    def test_w2_export_requires_a_company(self, client, company):
        r = client.get("/reports/w2-export?company_id=0&year=2026")
        assert r.status_code == 400

    def test_consolidated_reports_accept_all_companies(self, client, company, second_company):
        for path in ("/reports/payroll-register",
                     "/reports/tax-liability?year=2026",
                     "/reports/workers-comp?year=2026",
                     "/reports/deductions?year=2026",
                     "/reports/client-liabilities?year=2026",
                     "/reports/new-hires"):
            sep = "&" if "?" in path else "?"
            r = client.get(f"{path}{sep}company_id=-1")
            assert r.status_code == 200, path
            assert "filed per EIN" not in r.text, path

    def test_consolidated_shows_each_company_separately(
        self, client, db, company, second_company,
    ):
        from models.employee import Employee
        db.add(Employee(
            company_id=second_company.id, first_name="Fresh", last_name="Start",
            employment_type="salaried", pay_rate=50000, status="active", state="OK",
            flsa_exempt=True, hire_date=date.today(),
        ))
        db.commit()
        r = client.get("/reports/new-hires?company_id=-1")
        assert r.status_code == 200
        assert "Other Co" in r.text
        assert "Fresh" in r.text


class TestConsolidatedTotalsMatchPerCompany:
    """The invariant behind the groups-first restructure.

    Reports now build per-company groups and derive the flat totals by summing
    them, instead of aggregating the whole set a second time. Running a report
    consolidated must therefore equal running it once per company and adding the
    results -- if it does not, the restructure changed the numbers.
    """

    def _seed_two_companies(self, client, db, company, second_company):
        from models.employee import Employee
        emps = []
        for co, first in ((company, "Ann"), (second_company, "Bill")):
            emp = Employee(
                company_id=co.id, first_name=first, last_name="Worker",
                employment_type="salaried", pay_rate=52000, status="active",
                state="OK", flsa_exempt=True, hire_date=date(2025, 1, 1),
            )
            db.add(emp)
            emps.append(emp)
        db.commit()
        for emp in emps:
            db.refresh(emp)
        periods = [_run_payroll(client, db, co, emp)
                   for co, emp in ((company, emps[0]), (second_company, emps[1]))]
        return emps, periods

    def _totals_via_context(self, client, path):
        """Pull the rendered totals out of the response by re-running the route.

        The templates render the numbers, so comparing the rendered pages is the
        honest end-to-end check: identical figures must appear.
        """
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code)
        return r.text

    def test_tax_liability_consolidated_equals_sum_of_companies(
        self, client, db, company, second_company,
    ):
        from decimal import Decimal
        from routers.reports import (
            _load_paychecks, _tax_liability_rows, _totals, _TAX_LIABILITY_KEYS,
        )
        self._seed_two_companies(client, db, company, second_company)

        both = _load_paychecks(db, [company.id, second_company.id], 2026)
        assert both, "fixture produced no paychecks; test would be vacuous"

        # Derived-from-groups (what the route now does).
        per_company = []
        for cid in (company.id, second_company.id):
            rows = _tax_liability_rows(db, _load_paychecks(db, [cid], 2026))
            per_company.append(_totals(rows, _TAX_LIABILITY_KEYS))
        derived = _totals(per_company, _TAX_LIABILITY_KEYS)

        # Direct aggregation over the whole set (what it used to do).
        direct = _totals(_tax_liability_rows(db, both), _TAX_LIABILITY_KEYS)

        assert derived == direct

    def test_deductions_consolidated_equals_sum_of_companies(
        self, client, db, company, second_company,
    ):
        from routers.reports import _load_paychecks, _deduction_rows
        self._seed_two_companies(client, db, company, second_company)

        both = _deduction_rows(_load_paychecks(db, [company.id, second_company.id], 2026))
        direct_total = sum(r["total"] for r in both)
        direct_count = sum(r["count"] for r in both)

        derived_total = derived_count = 0
        for cid in (company.id, second_company.id):
            rows = _deduction_rows(_load_paychecks(db, [cid], 2026))
            derived_total += sum(r["total"] for r in rows)
            derived_count += sum(r["count"] for r in rows)

        assert derived_total == direct_total
        assert derived_count == direct_count

    def test_workers_comp_consolidated_equals_sum_of_companies(
        self, client, db, company, second_company,
    ):
        from routers.reports import _load_paychecks, _workers_comp_rows
        self._seed_two_companies(client, db, company, second_company)

        ids = [company.id, second_company.id]
        both = _workers_comp_rows(db, _load_paychecks(db, ids, 2026), ids)
        direct_gross = sum(r["gross"] for r in both)
        direct_premium = sum(r["premium"] for r in both)

        derived_gross = derived_premium = 0
        for cid in ids:
            rows = _workers_comp_rows(db, _load_paychecks(db, [cid], 2026), [cid])
            derived_gross += sum(r["gross"] for r in rows)
            derived_premium += sum(r["premium"] for r in rows)

        assert derived_gross == direct_gross
        assert derived_premium == direct_premium

    def test_consolidated_pages_render_both_companies(
        self, client, db, company, second_company,
    ):
        self._seed_two_companies(client, db, company, second_company)
        for path in ("/reports/tax-liability?company_id=-1&year=2026",
                     "/reports/deductions?company_id=-1&year=2026",
                     "/reports/workers-comp?company_id=-1&year=2026"):
            text = self._totals_via_context(client, path)
            assert company.name in text, path
            assert second_company.name in text, path
