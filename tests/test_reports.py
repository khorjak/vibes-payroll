"""
Smoke tests for Phase 5 report routes.
"""
from datetime import date
import pytest
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck, ClientLiability


def _run_payroll(client, db, company, employee, approve=True):
    """Calculate a May 2026 run. Reports only count approved/paid paychecks, so approve by default."""
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
    if approve:
        client.post(f"/payroll/{pp.id}/approve")
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
        assert "No payroll data" in r.text

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


class TestClientLiabilitiesOnlyOwedWhenApproved:
    def _run(self, db, company, salaried_employee, benefit_plan, approve):
        from models.benefit import EmployeeBenefitEnrollment
        from models.payroll import PayPeriod
        from services.payroll_service import approve_payroll_run, calculate_payroll_run
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                       pay_date=date(2026, 5, 20), frequency="biweekly", status="open")
        db.add(pp)
        db.commit()
        calculate_payroll_run(pp, db)
        if approve:
            approve_payroll_run(pp, db)
        return pp

    def test_draft_run_owes_nothing(self, client, db, company, salaried_employee, benefit_plan):
        self._run(db, company, salaried_employee, benefit_plan, approve=False)
        r = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026")
        assert "Health Plan" not in r.text

    def test_approved_run_is_listed(self, client, db, company, salaried_employee, benefit_plan):
        self._run(db, company, salaried_employee, benefit_plan, approve=True)
        r = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026")
        assert "Health Plan" in r.text

    def test_voided_check_drops_off(self, client, db, company, salaried_employee, benefit_plan):
        from models.payroll import Paycheck
        from services.payroll_service import void_paycheck
        self._run(db, company, salaried_employee, benefit_plan, approve=True)
        void_paycheck(db.query(Paycheck).one(), "error", db)
        r = client.get(f"/reports/client-liabilities?company_id={company.id}&year=2026")
        assert "Health Plan" not in r.text


class TestMarkNewHireReported:
    def _hire(self, db, company):
        emp = Employee(company_id=company.id, first_name="New", last_name="Hire",
                       employment_type="hourly", pay_rate=15, status="active",
                       state="OK", hire_date=date.today())
        db.add(emp)
        db.commit()
        return emp

    def test_marks_reported_and_leaves_report(self, client, db, company):
        emp = self._hire(db, company)
        r = client.post(f"/employees/{emp.id}/new-hire-reported", data={"return_to": "report"})
        assert r.status_code == 303
        assert r.headers["location"] == f"/reports/new-hires?company_id={company.id}"
        db.refresh(emp)
        assert emp.new_hire_reported_at == date.today()
        page = client.get(f"/reports/new-hires?company_id={company.id}")
        assert "All recent hires have been reported" in page.text

    def test_profile_redirect_by_default(self, client, db, company):
        emp = self._hire(db, company)
        r = client.post(f"/employees/{emp.id}/new-hire-reported")
        assert r.headers["location"] == f"/employees/{emp.id}?flash=new_hire_reported"

    def test_report_and_profile_show_button_until_reported(self, client, db, company):
        emp = self._hire(db, company)
        assert "Mark as reported" in client.get(f"/reports/new-hires?company_id={company.id}").text
        assert "Mark as reported" in client.get(f"/employees/{emp.id}").text
        client.post(f"/employees/{emp.id}/new-hire-reported")
        assert "Mark as reported" not in client.get(f"/employees/{emp.id}").text


class TestMarkNewHireReportedEdgeCases:
    def _hire(self, db, company):
        emp = Employee(company_id=company.id, first_name="New", last_name="Hire",
                       employment_type="hourly", pay_rate=15, status="active",
                       state="OK", hire_date=date.today())
        db.add(emp)
        db.commit()
        return emp

    def test_second_post_changes_nothing(self, client, db, company):
        from datetime import timedelta
        from models.audit import AuditLog
        emp = self._hire(db, company)
        client.post(f"/employees/{emp.id}/new-hire-reported")
        emp.new_hire_reported_at = date.today() - timedelta(days=3)
        db.commit()
        client.post(f"/employees/{emp.id}/new-hire-reported")
        db.refresh(emp)
        assert emp.new_hire_reported_at == date.today() - timedelta(days=3)
        assert db.query(AuditLog).filter_by(table_name="employees", record_id=emp.id).count() == 1

    def test_redirect_keeps_consolidated_view(self, client, db, company):
        emp = self._hire(db, company)
        r = client.post(f"/employees/{emp.id}/new-hire-reported",
                        data={"return_to": "report", "company_id": "-1"})
        assert r.headers["location"] == "/reports/new-hires?company_id=-1"

    def test_report_form_posts_current_company(self, client, db, company):
        self._hire(db, company)
        page = client.get(f"/reports/new-hires?company_id={company.id}").text
        assert f'name="company_id" value="{company.id}"' in page


class TestDeductionsReportWithData:
    def _run(self, db, company, salaried_employee, benefit_plan):
        from models.benefit import EmployeeBenefitEnrollment
        from services.payroll_service import approve_payroll_run, calculate_payroll_run
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        pp = PayPeriod(company_id=company.id, start_date=date(2026, 5, 1), end_date=date(2026, 5, 14),
                       pay_date=date(2026, 5, 20), frequency="biweekly", status="open")
        db.add(pp)
        db.commit()
        calculate_payroll_run(pp, db)
        approve_payroll_run(pp, db)

    def test_lists_each_deduction_with_total(self, client, db, company, salaried_employee, benefit_plan):
        self._run(db, company, salaried_employee, benefit_plan)
        r = client.get(f"/reports/deductions?company_id={company.id}&year=2026")
        assert r.status_code == 200
        assert "Health Plan" in r.text
        assert "150.00" in r.text

    def test_other_year_is_empty(self, client, db, company, salaried_employee, benefit_plan):
        self._run(db, company, salaried_employee, benefit_plan)
        r = client.get(f"/reports/deductions?company_id={company.id}&year=2025")
        assert "Health Plan" not in r.text

    def test_voided_paycheck_excluded(self, client, db, company, salaried_employee, benefit_plan):
        from services.payroll_service import void_paycheck
        self._run(db, company, salaried_employee, benefit_plan)
        void_paycheck(db.query(Paycheck).one(), "mistake", db)
        r = client.get(f"/reports/deductions?company_id={company.id}&year=2026")
        assert "Health Plan" not in r.text

    def test_same_deduction_across_paychecks_is_summed(self, client, db, company, salaried_employee, benefit_plan):
        from services.payroll_service import approve_payroll_run, calculate_payroll_run
        self._run(db, company, salaried_employee, benefit_plan)
        pp2 = PayPeriod(company_id=company.id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 14),
                        pay_date=date(2026, 6, 20), frequency="biweekly", status="open")
        db.add(pp2)
        db.commit()
        calculate_payroll_run(pp2, db)
        approve_payroll_run(pp2, db)
        r = client.get(f"/reports/deductions?company_id={company.id}&year=2026")
        assert "300.00" in r.text  # two $150 deductions in one row


# ── Oklahoma SUTA (OESC) report ─────────────────────────────────────────────

class TestSutaReport:
    def _check(self, db, company, employee, pay_date, gross, status="approved", pre_tax=0):
        from models.payroll import PaycheckLine
        pp = PayPeriod(company_id=company.id, start_date=pay_date, end_date=pay_date,
                       pay_date=pay_date, frequency="biweekly", status="approved")
        db.add(pp)
        db.flush()
        pc = Paycheck(employee_id=employee.id, pay_period_id=pp.id, status=status,
                      gross_wages=gross, net_pay=gross)
        db.add(pc)
        db.flush()
        if pre_tax:
            db.add(PaycheckLine(paycheck_id=pc.id, line_type="deduction", description="401k",
                                amount=pre_tax, is_pre_tax=True))
        db.commit()
        return pc

    @staticmethod
    def _first_row(page):
        """[total, excess, taxable, contributions] of the first employee row."""
        import re
        body = page.split("<tbody", 1)[1].split("</tbody>", 1)[0]
        return re.findall(r"tabular-nums[^>]*>\$([\d.]+)</td>", body)[:4]

    def _get(self, client, company, quarter=2, year=2026):
        return client.get(f"/reports/suta?company_id={company.id}&year={year}&quarter={quarter}")

    def test_no_params(self, client):
        r = client.get("/reports/suta")
        assert r.status_code == 200
        assert "Select a company" in r.text

    def test_listed_on_index(self, client):
        assert "/reports/suta" in client.get("/reports/").text

    def test_refuses_consolidation(self, client, company):
        r = client.get("/reports/suta?company_id=-1&year=2026&quarter=2")
        assert r.status_code == 200
        assert "filed per EIN" in r.text

    def test_wages_and_contributions_from_real_payroll(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee)
        pc = db.query(Paycheck).filter_by(pay_period_id=pp.id).one()
        suta = next(l.amount for l in pc.lines if l.description == "SUTA")
        page = self._get(client, company).text
        assert "Smith, Jane" in page
        assert "$2500.00" in page            # total and taxable wages, under the base
        assert f"${suta:.2f}" in page        # contribution as calculated

    def test_draft_paychecks_excluded(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee, approve=False)
        assert "No approved or paid payroll" in self._get(client, company).text

    def test_voided_paychecks_excluded(self, client, db, company, salaried_employee):
        self._check(db, company, salaried_employee, date(2026, 5, 20), 1000, status="voided")
        assert "No approved or paid payroll" in self._get(client, company).text

    def test_wage_base_spans_quarters(self, client, db, company, salaried_employee):
        # 26,000 earned in Q1 leaves 1,000 of the 27,000 base for Q2.
        self._check(db, company, salaried_employee, date(2026, 3, 20), 26000)
        self._check(db, company, salaried_employee, date(2026, 5, 20), 5000)
        assert self._first_row(self._get(client, company).text) == [
            "5000.00", "4000.00", "1000.00", "0.00"]

    def test_wage_base_exhausted_means_no_taxable_wages(self, client, db, company, salaried_employee):
        self._check(db, company, salaried_employee, date(2026, 3, 20), 30000)
        self._check(db, company, salaried_employee, date(2026, 5, 20), 2000)
        assert self._first_row(self._get(client, company).text) == [
            "2000.00", "2000.00", "0.00", "0.00"]

    def test_pre_tax_deductions_are_not_taxable_wages(self, client, db, company, salaried_employee):
        self._check(db, company, salaried_employee, date(2026, 5, 20), 1000, pre_tax=100)
        assert self._first_row(self._get(client, company).text) == [
            "1000.00", "100.00", "900.00", "0.00"]

    def test_only_selected_quarter_listed(self, client, db, company, salaried_employee, hourly_employee):
        self._check(db, company, salaried_employee, date(2026, 5, 20), 1000)
        self._check(db, company, hourly_employee, date(2026, 8, 20), 1000)
        page = self._get(client, company, quarter=2).text
        assert "Smith" in page and "Jones" not in page

    def test_other_company_excluded(self, client, db, company, second_company, other_employee):
        self._check(db, second_company, other_employee, date(2026, 5, 20), 1000)
        assert "Person" not in self._get(client, company).text

    def test_ssn_masked(self, client, db, company, salaried_employee):
        from utils.crypto import encrypt
        salaried_employee.ssn_encrypted = encrypt("123456789")
        db.commit()
        self._check(db, company, salaried_employee, date(2026, 5, 20), 1000)
        page = self._get(client, company).text
        assert "***-**-6789" in page
        assert "123456789" not in page

    def test_q4_boundary(self, client, db, company, salaried_employee):
        self._check(db, company, salaried_employee, date(2026, 12, 31), 1000)
        assert "Smith" in self._get(client, company, quarter=4).text
        assert "No approved or paid payroll" in self._get(client, company, quarter=3).text

    def test_totals_row(self, client, db, company, salaried_employee, hourly_employee):
        self._check(db, company, salaried_employee, date(2026, 5, 20), 1000)
        self._check(db, company, hourly_employee, date(2026, 5, 20), 500)
        assert "$1500.00" in self._get(client, company).text


# ── Reports count approved/paid paychecks only ──────────────────────────────

class TestDraftsExcludedFromReports:
    """(url, marker present only when the report has data)."""
    REPORTS = {
        "tax-liability": ("/reports/tax-liability?company_id={c}&year=2026", "Year Total"),
        "941": ("/reports/quarterly-941?company_id={c}&year=2026&quarter=2", "Form 941 Summary"),
        "workers-comp": ("/reports/workers-comp?company_id={c}&year=2026", "Unclassified"),
        "ok-withholding": ("/reports/ok-withholding?company_id={c}&year=2026", "May"),
        "deductions": ("/reports/deductions?company_id={c}&year=2026", "Health Plan"),
        "suta": ("/reports/suta?company_id={c}&year=2026&quarter=2", "Smith, Jane"),
    }

    @pytest.fixture()
    def enrolled(self, db, salaried_employee, benefit_plan):
        from models.benefit import EmployeeBenefitEnrollment
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        db.commit()

    @pytest.mark.parametrize("name", REPORTS)
    def test_draft_run_not_reported(self, client, db, company, salaried_employee, enrolled, name):
        url, marker = self.REPORTS[name]
        _run_payroll(client, db, company, salaried_employee, approve=False)
        assert marker not in client.get(url.format(c=company.id)).text

    @pytest.mark.parametrize("name", REPORTS)
    def test_approved_run_reported(self, client, db, company, salaried_employee, enrolled, name):
        url, marker = self.REPORTS[name]
        _run_payroll(client, db, company, salaried_employee)
        assert marker in client.get(url.format(c=company.id)).text

    def test_paid_run_reported(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee)
        client.post(f"/payroll/{pp.id}/mark-paid")
        assert "Form 941 Summary" in client.get(
            f"/reports/quarterly-941?company_id={company.id}&year=2026&quarter=2").text

    def test_w2_export_skips_drafts(self, client, db, company, salaried_employee):
        _run_payroll(client, db, company, salaried_employee, approve=False)
        r = client.get(f"/reports/w2-export?company_id={company.id}&year=2026")
        assert len(r.text.splitlines()) == 1  # header only

    def test_voiding_after_approval_drops_it_from_reports(self, client, db, company, salaried_employee):
        from services.payroll_service import void_paycheck
        _run_payroll(client, db, company, salaried_employee)
        void_paycheck(db.query(Paycheck).one(), "mistake", db)
        assert "Form 941 Summary" not in client.get(
            f"/reports/quarterly-941?company_id={company.id}&year=2026&quarter=2").text

    def test_payroll_register_still_shows_draft_for_review(self, client, db, company, salaried_employee):
        pp = _run_payroll(client, db, company, salaried_employee, approve=False)
        r = client.get(f"/reports/payroll-register?company_id={company.id}&pay_period_id={pp.id}")
        assert "Smith" in r.text
