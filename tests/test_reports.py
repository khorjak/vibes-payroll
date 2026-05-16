"""
Smoke tests for Phase 5 report routes.
"""
from datetime import date
import pytest
from models.payroll import PayPeriod, Paycheck


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
