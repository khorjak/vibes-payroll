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
        original = templates.env.globals["is_admin"]
        templates.env.globals["is_admin"] = lambda request: False
        try:
            r = client.get("/employees/")
            assert "+ New Employee" not in r.text
        finally:
            templates.env.globals["is_admin"] = original


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
