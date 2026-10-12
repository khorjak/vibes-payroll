"""Bonus runs: several employees paid a bonus in one off-cycle pay run at supplemental rates."""
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.benefit import BenefitPlan, EmployeeBenefitEnrollment
from models.company import Company
from models.employee import Employee, OKWithholdingElection
from models.garnishment import GarnishmentOrder
from models.oklahoma_withholding import DEFAULT_OKLAHOMA_TABLES
from models.payroll import PayPeriod, Paycheck, PaycheckLine
from models.federal_withholding import DEFAULT_FEDERAL_TABLES
from tax_engine.calculator import calculate_paycheck
from tax_engine.federal import calc_federal_withholding
from tax_engine.models import FederalTable, OKTable, OKWithholdingInput, W4Input
from tax_engine.oklahoma import calc_ok_withholding, calc_supplemental_ok
from tests.test_tax_calculator import make_input

PAY_DATE = "2026-12-18"


def _post(client, company, amounts, **extra):
    data = {"company_id": str(company.id), "pay_date": PAY_DATE, "description": "Christmas Bonus",
            **{f"amount_{emp.id}": amt for emp, amt in amounts}, **extra}
    return client.post("/payroll/bonus/new", data=data, follow_redirects=False)


def _regular_run(db, company, pay_date=date(2026, 12, 4), hours=80):
    """A regular biweekly run: salaried employees at salary, hourly at `hours`."""
    from models.payroll import Timesheet
    from services.payroll_service import calculate_payroll_run
    pp = PayPeriod(company_id=company.id, start_date=pay_date - timedelta(days=13), end_date=pay_date,
                   pay_date=pay_date, frequency="biweekly", status="open")
    db.add(pp)
    db.flush()
    for emp in db.query(Employee).filter(Employee.company_id == company.id, Employee.employment_type != "salaried"):
        db.add(Timesheet(employee_id=emp.id, pay_period_id=pp.id, regular_hours=hours))
    db.commit()
    calculate_payroll_run(pp, db)
    return pp


@pytest.fixture()
def regular_run(db, company, salaried_employee, hourly_employee):
    return _regular_run(db, company)


def _bonus_check(db, emp):
    return db.query(Paycheck).join(PayPeriod).filter(
        Paycheck.employee_id == emp.id, PayPeriod.start_date == date(2026, 12, 18)).one()


def _lines_for_period(db, emp, start):
    pc = db.query(Paycheck).join(PayPeriod).filter(
        Paycheck.employee_id == emp.id, PayPeriod.start_date == start).one()
    return pc, {(l.line_type, l.description): l for l in pc.lines}


def _lines(db, emp):
    pc = _bonus_check(db, emp)
    return pc, {(l.line_type, l.description): l for l in pc.lines}


# ── Tax engine ───────────────────────────────────────────────────────────────

class TestSupplementalOklahoma:
    @pytest.mark.parametrize("year,expected", [(2025, "47.50"), (2026, "45.00")])
    def test_top_rate_of_the_year(self, year, expected):
        table = OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[year])
        assert calc_supplemental_ok(Decimal("1000"), table) == Decimal(expected)

    def test_calculator_ignores_allowances_and_extra(self):
        ok = OKWithholdingInput(filing_status="married", allowances=3, extra_withholding=Decimal("25"))
        result = calculate_paycheck(make_input(gross_wages=Decimal("1000"), is_supplemental=True, ok_withholding=ok))
        assert result.taxes.ok_income_tax == Decimal("47.50")

    def test_exempt_withholds_nothing(self):
        ok = OKWithholdingInput(filing_status="single", exempt=True)
        result = calculate_paycheck(make_input(gross_wages=Decimal("1000"), is_supplemental=True, ok_withholding=ok))
        assert result.taxes.ok_income_tax == Decimal("0")


class TestAggregateMethod:
    """No income tax withheld from regular wages: tax bonus + regular wages as one payment."""

    def test_federal_adds_regular_wages_and_subtracts_their_tax(self):
        inp = make_input(gross_wages=Decimal("1000"), is_supplemental=True, federal_flat_allowed=False,
                         regular_taxable=Decimal("1500"), regular_federal_tax=Decimal("40"))
        whole = calculate_paycheck(make_input(gross_wages=Decimal("2500"))).taxes.federal_income_tax
        assert calculate_paycheck(inp).taxes.federal_income_tax == whole - Decimal("40")

    def test_oklahoma_adds_regular_wages_and_subtracts_their_tax(self):
        inp = make_input(gross_wages=Decimal("1000"), is_supplemental=True, ok_flat_allowed=False,
                         regular_taxable=Decimal("1500"), regular_ok_tax=Decimal("10"))
        whole = calculate_paycheck(make_input(gross_wages=Decimal("2500"))).taxes.ok_income_tax
        result = calculate_paycheck(inp).taxes
        assert result.ok_income_tax == whole - Decimal("10")
        assert result.federal_income_tax == Decimal("220.00")  # federal still flat

    def test_never_negative(self):
        inp = make_input(gross_wages=Decimal("10"), is_supplemental=True, federal_flat_allowed=False,
                         ok_flat_allowed=False, regular_federal_tax=Decimal("500"), regular_ok_tax=Decimal("500"))
        taxes = calculate_paycheck(inp).taxes
        assert taxes.federal_income_tax == 0 and taxes.ok_income_tax == 0


# ── Creating a run ───────────────────────────────────────────────────────────

class TestBonusRun:
    def test_pages_link_and_render(self, client, salaried_employee, hourly_employee):
        assert "/payroll/bonus/new" in client.get("/payroll/").text
        page = client.get("/payroll/bonus/new")
        assert page.status_code == 200
        assert salaried_employee.full_name in page.text and hourly_employee.full_name in page.text

    def test_one_run_pays_each_employee_entered(self, client, db, company, salaried_employee, hourly_employee,
                                                regular_run):
        r = _post(client, company, [(salaried_employee, "1,000"), (hourly_employee, "$500.00")])
        assert r.status_code == 303
        pp = db.query(PayPeriod).filter(PayPeriod.id != regular_run.id).one()
        assert pp.is_off_cycle and pp.pay_date == date(2026, 12, 18) and pp.status == "draft"
        assert r.headers["location"] == f"/payroll/{pp.id}"
        for emp, gross in ((salaried_employee, "1000.00"), (hourly_employee, "500.00")):
            pc, lines = _lines(db, emp)
            assert pc.gross_wages == Decimal(gross)
            earning = [l for l in pc.lines if l.line_type == "earning"]
            assert len(earning) == 1 and earning[0].description == "Christmas Bonus"
            assert earning[0].amount == Decimal(gross) and earning[0].hours is None
            assert lines[("tax", "Federal Income Tax")].amount == Decimal(gross) * Decimal("0.22")

    def test_oklahoma_at_top_rate_even_with_allowances(self, client, db, company, salaried_employee):
        db.add(OKWithholdingElection(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                                     filing_status="married", allowances=4))
        db.commit()
        _regular_run(db, company)
        _post(client, company, [(salaried_employee, "1000")])
        _, lines = _lines(db, salaried_employee)
        assert lines[("tax", "Oklahoma Income Tax")].amount == Decimal("45.00")

    def test_only_percent_deductions_and_garnishments(self, client, db, company, salaried_employee, benefit_plan):
        k401 = BenefitPlan(company_id=company.id, name="401k", benefit_type="traditional_401k",
                           employee_contribution_type="percent", employee_contribution_amount=5,
                           employer_match_percent=50, pre_tax=True, active=True)
        db.add(k401)
        db.flush()
        for plan in (benefit_plan, k401):  # benefit_plan: fixed $150 health premium
            db.add(EmployeeBenefitEnrollment(employee_id=salaried_employee.id, benefit_plan_id=plan.id,
                                             effective_date=date(2026, 1, 1)))
        db.add(GarnishmentOrder(employee_id=salaried_employee.id, garnishment_type="creditor",
                                payee_name="Fixed Co", amount=200, amount_type="fixed",
                                effective_date=date(2026, 1, 1), active=True))
        db.add(GarnishmentOrder(employee_id=salaried_employee.id, garnishment_type="child_support",
                                payee_name="State CSE", percent=10, amount_type="percent",
                                effective_date=date(2026, 1, 1), active=True))
        db.commit()
        _regular_run(db, company)

        _post(client, company, [(salaried_employee, "2000")])
        pc, lines = _lines(db, salaried_employee)
        assert lines[("deduction", "401k")].amount == Decimal("100.00")
        assert lines[("employer_contribution", "401k (Employer Match)")].amount == Decimal("50.00")
        assert ("deduction", "Health Plan") not in lines
        garnishments = [l for l in pc.lines if l.description.startswith("Garnishment")]
        assert [l.description for l in garnishments] == ["Garnishment - Child Support"]
        # 401k deferral cuts income-tax wages only: 22% of 1,900.
        assert lines[("tax", "Federal Income Tax")].amount == Decimal("418.00")

    def test_blank_and_zero_amounts_are_skipped(self, client, db, company, salaried_employee, hourly_employee):
        assert _post(client, company, [(salaried_employee, "250"), (hourly_employee, "0")]).status_code == 303
        assert {pc.employee_id for pc in db.query(Paycheck)} == {salaried_employee.id}

    def test_employee_of_another_company_is_ignored(self, client, db, company, salaried_employee, other_employee):
        _post(client, company, [(salaried_employee, "250"), (other_employee, "999")])
        assert {pc.employee_id for pc in db.query(Paycheck)} == {salaried_employee.id}

    @pytest.mark.parametrize("bad", ["abc", "-5", "NaN", "Infinity", "1000000"])
    def test_bad_amount_saves_nothing(self, client, db, company, salaried_employee, bad):
        r = _post(client, company, [(salaried_employee, bad)])
        assert r.status_code == 422 and "Enter an amount under $1,000,000." in r.text
        assert db.query(PayPeriod).count() == 0

    def test_no_amounts_is_422(self, client, db, company, salaried_employee):
        r = _post(client, company, [(salaried_employee, "")])
        assert r.status_code == 422 and "at least one employee" in r.text
        assert db.query(PayPeriod).count() == 0

    def test_missing_date_and_description_are_422(self, client, db, company, salaried_employee):
        r = _post(client, company, [(salaried_employee, "100")], pay_date="", description="")
        assert r.status_code == 422 and "Enter a pay date." in r.text and "Required." in r.text
        assert db.query(PayPeriod).count() == 0

    def test_no_time_off_accrues(self, client, db, company, salaried_employee):
        from models.leave import LeaveEntry, LeavePolicy
        db.add(LeavePolicy(employee_id=salaried_employee.id, leave_type="pto", method="per_period", rate=4))
        db.commit()
        _post(client, company, [(salaried_employee, "500")])
        assert db.query(LeaveEntry).filter(LeaveEntry.kind == "accrued").count() == 0


    def test_same_day_regular_run_counts_toward_ytd(self, client, db, company, salaried_employee):
        from services.payroll_service import calculate_payroll_run, get_ytd_prior
        regular = PayPeriod(company_id=company.id, start_date=date(2026, 12, 5), end_date=date(2026, 12, 18),
                            pay_date=date(2026, 12, 18), frequency="biweekly", status="open")
        db.add(regular)
        db.commit()
        calculate_payroll_run(regular, db)
        regular_gross = db.query(Paycheck).one().gross_wages
        _post(client, company, [(salaried_employee, "1000")])
        bonus = db.query(PayPeriod).filter(PayPeriod.id != regular.id).one()
        assert get_ytd_prior(salaried_employee.id, bonus, db)["gross"] == regular_gross
        assert get_ytd_prior(salaried_employee.id, regular, db)["gross"] == 0  # the earlier run ignores the later
        bonus_check = db.query(Paycheck).filter(Paycheck.pay_period_id == bonus.id).one()
        assert bonus_check.ytd_gross == regular_gross + Decimal("1000")


class TestFlatRateEligibility:
    def _taxes(self, client, db, company, emp, amount="1000"):
        _post(client, company, [(emp, amount)])
        _, lines = _lines(db, emp)
        return tuple(lines[("tax", d)].amount if ("tax", d) in lines else Decimal("0")
                     for d in ("Federal Income Tax", "Oklahoma Income Tax"))

    def test_no_regular_paychecks_taxes_bonus_as_regular_pay(self, client, db, company, salaried_employee):
        fed = calc_federal_withholding(Decimal("1000"), "biweekly", W4Input(filing_status="single"),
                                       table=FederalTable.from_data(DEFAULT_FEDERAL_TABLES[2026]))
        ok = calc_ok_withholding(Decimal("1000"), "biweekly", OKWithholdingInput(filing_status="single"),
                                 table=OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[2026]))
        assert self._taxes(client, db, company, salaried_employee) == (fed, ok)
        assert fed != Decimal("220.00")

    def test_untaxed_regular_wages_are_aggregated(self, client, db, company, hourly_employee):
        _regular_run(db, company, hours=10)  # $185: below both withholding thresholds
        _, regular = _lines_for_period(db, hourly_employee, date(2026, 11, 21))
        assert ("tax", "Federal Income Tax") not in regular and ("tax", "Oklahoma Income Tax") not in regular
        fed = calc_federal_withholding(Decimal("1185"), "biweekly", W4Input(filing_status="single"),
                                       table=FederalTable.from_data(DEFAULT_FEDERAL_TABLES[2026]))
        assert self._taxes(client, db, company, hourly_employee)[0] == fed

    def test_last_years_regular_withholding_allows_flat(self, client, db, company, salaried_employee):
        _regular_run(db, company, pay_date=date(2025, 6, 6))
        assert self._taxes(client, db, company, salaried_employee) == (Decimal("220.00"), Decimal("45.00"))

    def test_withholding_two_years_back_does_not(self, client, db, company, salaried_employee):
        _regular_run(db, company, pay_date=date(2024, 6, 7))
        assert self._taxes(client, db, company, salaried_employee)[0] != Decimal("220.00")

    def test_earlier_bonus_is_not_regular_wages(self, client, db, company, salaried_employee):
        _post(client, company, [(salaried_employee, "5000")], pay_date="2026-06-05")
        assert self._taxes(client, db, company, salaried_employee)[0] != Decimal("220.00")

    def test_voided_regular_paycheck_does_not_count(self, client, db, company, salaried_employee):
        _regular_run(db, company)
        db.query(Paycheck).update({"status": "voided"})
        db.commit()
        assert self._taxes(client, db, company, salaried_employee)[0] != Decimal("220.00")


class TestOffCycleFrequency:
    def test_form_has_no_frequency_choice(self, client):
        assert "Pay Frequency" not in client.get("/payroll/off-cycle/new").text

    def test_period_records_employee_frequency(self, client, db, company, salaried_employee):
        salaried_employee.pay_frequency = "weekly"
        db.commit()
        r = client.post("/payroll/off-cycle/new", data={
            "company_id": company.id, "employee_id": salaried_employee.id, "pay_date": "2026-06-05",
            "frequency": "monthly", "gross_amount": "500", "description": "Back pay"})
        assert r.status_code == 303
        assert db.query(PayPeriod).one().frequency == "weekly"


class TestNoRecalculate:
    def test_off_cycle_period_cannot_be_recalculated(self, client, db, company, salaried_employee, hourly_employee):
        _post(client, company, [(salaried_employee, "1000")])
        pp = db.query(PayPeriod).one()
        page = client.get(f"/payroll/{pp.id}").text
        assert "Recalculate" not in page and "/timesheets" not in page
        assert client.post(f"/payroll/{pp.id}/calculate").status_code == 400
        assert db.query(Paycheck).count() == 1  # hourly_employee was not drafted

    def test_regular_period_still_recalculates(self, client, db, pay_period, salaried_employee):
        assert client.post(f"/payroll/{pay_period.id}/calculate", follow_redirects=False).status_code == 303


# ── Roles and company scope (real auth) ──────────────────────────────────────

def _login(auth_client, username, password):
    assert auth_client.post("/auth/login", data={"username": username, "password": password,
                                                 "next": "/"}).status_code == 303
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', auth_client.get("/reports/").text).group(1)


def _company_with_employee(db, name):
    co = Company(name=name, pay_frequency="biweekly", state="OK")
    db.add(co)
    db.flush()
    emp = Employee(company_id=co.id, first_name="A", last_name=name, employment_type="salaried",
                   pay_rate=52000, status="active", state="OK")
    db.add(emp)
    db.flush()
    return co, emp


def test_read_only_cannot_create(auth_client, auth_db, readonly_user):
    from models.user_company import UserCompany
    co, emp = _company_with_employee(auth_db, "Co")
    auth_db.add(UserCompany(user_id=readonly_user.id, company_id=co.id))
    auth_db.commit()
    token = _login(auth_client, "viewer", "viewpass")
    r = auth_client.post("/payroll/bonus/new", data={"company_id": co.id, "pay_date": PAY_DATE,
                                                     "description": "Bonus", f"amount_{emp.id}": "100",
                                                     "csrf_token": token})
    assert r.status_code == 403 and auth_db.query(PayPeriod).count() == 0


def test_preparer_cannot_pay_another_company(auth_client, auth_db, preparer_user):
    from models.user_company import UserCompany
    mine, _ = _company_with_employee(auth_db, "Mine")
    theirs, emp = _company_with_employee(auth_db, "Theirs")
    auth_db.add(UserCompany(user_id=preparer_user.id, company_id=mine.id))
    auth_db.commit()
    token = _login(auth_client, "preparer", "preppass")
    r = auth_client.post("/payroll/bonus/new", data={"company_id": theirs.id, "pay_date": PAY_DATE,
                                                     "description": "Bonus", f"amount_{emp.id}": "100",
                                                     "csrf_token": token})
    assert r.status_code == 404 and auth_db.query(PayPeriod).count() == 0
