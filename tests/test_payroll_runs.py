"""
Tests for Phase 3: payroll run service and routes.
"""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.orm import joinedload

from models.employee import Employee, W4Election, OKWithholdingElection
from models.benefit import BenefitPlan, EmployeeBenefitEnrollment
from models.garnishment import GarnishmentOrder
from models.payroll import PayPeriod, Paycheck, Timesheet, PaycheckLine, ClientLiability
from services.payroll_service import (
    calc_employee_gross,
    get_employee_pre_tax_deductions,
    get_employee_post_tax_deductions,
    get_ytd_prior,
    draft_paycheck,
    calculate_payroll_run,
    approve_payroll_run,
    mark_period_paid,
    void_paycheck,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def pay_period(db, company):
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
    return pp


def _load_employee(db, employee_id):
    return (
        db.query(Employee)
        .options(
            joinedload(Employee.w4_elections),
            joinedload(Employee.ok_withholding_elections),
            joinedload(Employee.benefit_enrollments).joinedload(EmployeeBenefitEnrollment.plan),
            joinedload(Employee.workers_comp_code),
            joinedload(Employee.garnishment_orders),
        )
        .filter(Employee.id == employee_id)
        .one()
    )


def _load_pay_period(db, period_id):
    return (
        db.query(PayPeriod)
        .options(joinedload(PayPeriod.company))
        .filter(PayPeriod.id == period_id)
        .one()
    )


# ── calc_employee_gross ──────────────────────────────────────────────────────

class TestCalcEmployeeGross:
    def test_salaried_biweekly(self, salaried_employee):
        # $65,000 / 26 = $2,500.00
        assert calc_employee_gross(salaried_employee, None, "biweekly") == Decimal("2500.00")

    def test_salaried_monthly(self, salaried_employee):
        # $65,000 / 12 = $5,416.67
        assert calc_employee_gross(salaried_employee, None, "monthly") == Decimal("5416.67")

    def test_salaried_ignores_timesheet(self, salaried_employee, db, pay_period):
        ts = Timesheet(employee_id=salaried_employee.id, pay_period_id=pay_period.id, regular_hours=100)
        assert calc_employee_gross(salaried_employee, ts, "biweekly") == Decimal("2500.00")

    def test_hourly_regular_only(self, hourly_employee, db, pay_period):
        ts = Timesheet(employee_id=hourly_employee.id, pay_period_id=pay_period.id, regular_hours=80)
        # $18.50 × 80 = $1,480.00
        assert calc_employee_gross(hourly_employee, ts, "biweekly") == Decimal("1480.00")

    def test_hourly_with_overtime(self, hourly_employee, db, pay_period):
        ts = Timesheet(
            employee_id=hourly_employee.id,
            pay_period_id=pay_period.id,
            regular_hours=80,
            overtime_hours=10,
        )
        # $18.50 × 80 + $18.50 × 1.5 × 10 = $1,480 + $277.50 = $1,757.50
        assert calc_employee_gross(hourly_employee, ts, "biweekly") == Decimal("1757.50")

    def test_hourly_with_doubletime(self, hourly_employee, db, pay_period):
        ts = Timesheet(
            employee_id=hourly_employee.id,
            pay_period_id=pay_period.id,
            regular_hours=0,
            double_time_hours=8,
        )
        # $18.50 × 2 × 8 = $296.00
        assert calc_employee_gross(hourly_employee, ts, "biweekly") == Decimal("296.00")

    def test_hourly_no_timesheet_returns_zero(self, hourly_employee):
        assert calc_employee_gross(hourly_employee, None, "biweekly") == Decimal("0.00")


# ── get_employee_pre_tax_deductions ─────────────────────────────────────────

class TestGetPreTaxDeductions:
    def test_no_enrollments(self, db, salaried_employee):
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("0")

    def test_active_pretax_fixed(self, db, salaried_employee, benefit_plan):
        enrollment = EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
        )
        db.add(enrollment)
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        # benefit_plan fixture: employee_contribution_amount=150.00
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("150.00")

    def test_terminated_enrollment_excluded(self, db, salaried_employee, benefit_plan):
        enrollment = EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
        db.add(enrollment)
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("0")

    def test_post_tax_plan_excluded(self, db, salaried_employee, company):
        post_tax_plan = BenefitPlan(
            company_id=company.id,
            name="Roth 401k",
            benefit_type="roth_401k",
            employee_contribution_type="fixed",
            employee_contribution_amount=100.00,
            pre_tax=False,
            active=True,
        )
        db.add(post_tax_plan)
        db.flush()
        enrollment = EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=post_tax_plan.id,
            effective_date=date(2026, 1, 1),
        )
        db.add(enrollment)
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("0")

    def test_post_tax_plan_returned(self, db, salaried_employee, company):
        roth_plan = BenefitPlan(
            company_id=company.id,
            name="Roth 401k",
            benefit_type="roth_401k",
            employee_contribution_type="fixed",
            employee_contribution_amount=100.00,
            pre_tax=False,
            active=True,
        )
        db.add(roth_plan)
        db.flush()
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=roth_plan.id,
            effective_date=date(2026, 1, 1),
        ))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_post_tax_deductions(emp, Decimal("2500")) == Decimal("100.00")

    def test_post_tax_excludes_pre_tax(self, db, salaried_employee, benefit_plan):
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
        ))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_post_tax_deductions(emp, Decimal("2500")) == Decimal("0")

    def test_override_amount_used(self, db, salaried_employee, benefit_plan):
        enrollment = EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
            employee_override_amount=75.00,
        )
        db.add(enrollment)
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("75.00")


# ── get_ytd_prior ────────────────────────────────────────────────────────────

class TestGetYTDPrior:
    def test_no_prior_paychecks(self, db, salaried_employee, pay_period):
        ytd = get_ytd_prior(salaried_employee.id, pay_period, db)
        assert ytd["gross"] == Decimal("0")
        assert ytd["ss_wages"] == Decimal("0")

    def test_sums_prior_paid_paychecks(self, db, salaried_employee, company):
        prior_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 30),
            pay_date=date(2026, 5, 5),
            frequency="biweekly",
            status="paid",
        )
        db.add(prior_pp)
        db.flush()
        prior_check = Paycheck(
            employee_id=salaried_employee.id,
            pay_period_id=prior_pp.id,
            status="paid",
            gross_wages=Decimal("2500.00"),
            total_deductions=Decimal("150.00"),
            total_taxes_withheld=Decimal("400.00"),
            net_pay=Decimal("1950.00"),
        )
        db.add(prior_check)
        current_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 14),
            pay_date=date(2026, 5, 20),
            frequency="biweekly",
            status="open",
        )
        db.add(current_pp)
        db.commit()
        ytd = get_ytd_prior(salaried_employee.id, current_pp, db)
        assert ytd["gross"] == Decimal("2500.00")
        assert ytd["ss_wages"] == Decimal("2350.00")  # 2500 - 150

    def test_voided_paycheck_excluded(self, db, salaried_employee, company):
        prior_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 30),
            pay_date=date(2026, 5, 5),
            frequency="biweekly",
            status="paid",
        )
        db.add(prior_pp)
        db.flush()
        db.add(Paycheck(
            employee_id=salaried_employee.id,
            pay_period_id=prior_pp.id,
            status="voided",
            gross_wages=Decimal("2500.00"),
            total_deductions=Decimal("0.00"),
            total_taxes_withheld=Decimal("0.00"),
            net_pay=Decimal("0.00"),
        ))
        current_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 14),
            pay_date=date(2026, 5, 20),
            frequency="biweekly",
            status="open",
        )
        db.add(current_pp)
        db.commit()
        ytd = get_ytd_prior(salaried_employee.id, current_pp, db)
        assert ytd["gross"] == Decimal("0")

    def test_prior_year_paychecks_excluded(self, db, salaried_employee, company):
        prev_year_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2025, 12, 16),
            end_date=date(2025, 12, 31),
            pay_date=date(2025, 12, 31),
            frequency="biweekly",
            status="paid",
        )
        db.add(prev_year_pp)
        db.flush()
        db.add(Paycheck(
            employee_id=salaried_employee.id,
            pay_period_id=prev_year_pp.id,
            status="paid",
            gross_wages=Decimal("2500.00"),
            total_deductions=Decimal("0.00"),
            total_taxes_withheld=Decimal("0.00"),
            net_pay=Decimal("2500.00"),
        ))
        current_pp = PayPeriod(
            company_id=company.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 14),
            pay_date=date(2026, 1, 20),
            frequency="biweekly",
            status="open",
        )
        db.add(current_pp)
        db.commit()
        ytd = get_ytd_prior(salaried_employee.id, current_pp, db)
        assert ytd["gross"] == Decimal("0")


# ── draft_paycheck ───────────────────────────────────────────────────────────

class TestDraftPaycheck:
    def test_creates_paycheck_record(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        assert paycheck.id is not None
        assert paycheck.status == "draft"
        assert paycheck.gross_wages == Decimal("2500.00")
        assert paycheck.net_pay > Decimal("0")

    def test_creates_earning_lines(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.line_type == "earning",
        ).all()
        assert len(lines) == 1
        assert lines[0].description == "Regular Salary"
        assert lines[0].amount == Decimal("2500.00")

    def test_creates_fica_lines(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        ss_lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.line_type == "tax",
            PaycheckLine.description == "Social Security (Employee)",
        ).all()
        assert len(ss_lines) == 1
        assert ss_lines[0].amount == Decimal("155.00")  # $2,500 × 6.2%

    @staticmethod
    def _income_tax(db, paycheck):
        lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.line_type == "tax",
        ).all()
        by_desc = {l.description: l.amount for l in lines}
        return by_desc.get("Federal Income Tax"), by_desc.get("Oklahoma Income Tax")

    def test_no_elections_withholds_as_single(self, db, salaried_employee, pay_period):
        # No W-4 / OK-W-4 on file must withhold as single, zero allowances --
        # identical to an explicit election of that, and never $0.
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        fed_default, ok_default = self._income_tax(db, draft_paycheck(emp, pp, None, db))
        assert fed_default > Decimal("0")
        assert ok_default > Decimal("0")

        db.add(W4Election(employee_id=emp.id, effective_date=date(2026, 1, 1), filing_status="single"))
        db.add(OKWithholdingElection(employee_id=emp.id, effective_date=date(2026, 1, 1),
                                     filing_status="single", allowances=0))
        db.commit()
        db.expire_all()
        emp = _load_employee(db, salaried_employee.id)
        fed_explicit, ok_explicit = self._income_tax(db, draft_paycheck(emp, pp, None, db))
        assert (fed_default, ok_default) == (fed_explicit, ok_explicit)

    def test_election_overrides_default(self, db, salaried_employee, pay_period):
        db.add(W4Election(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                          filing_status="married_filing_jointly"))
        db.add(OKWithholdingElection(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                                     filing_status="married", allowances=2))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        fed_married, ok_married = self._income_tax(db, draft_paycheck(emp, pp, None, db))

        db.query(W4Election).delete()
        db.query(OKWithholdingElection).delete()
        db.commit()
        db.expire_all()
        emp = _load_employee(db, salaried_employee.id)
        fed_single, ok_single = self._income_tax(db, draft_paycheck(emp, pp, None, db))
        assert fed_married < fed_single
        assert ok_married < ok_single

    def test_exempt_elections_withhold_no_income_tax(self, db, salaried_employee, pay_period):
        db.add(W4Election(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                          filing_status="single", exempt=True))
        db.add(OKWithholdingElection(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                                     filing_status="single", exempt=True))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        fed, ok = self._income_tax(db, paycheck)
        assert not fed and not ok  # no line, or a $0 line
        assert paycheck.net_pay < paycheck.gross_wages  # FICA still withheld

    def test_expired_federal_exemption_withholds_as_single(self, db, salaried_employee, pay_period):
        # Exempt W-4 from 2025 expired 2026-02-15; the 2026-05-20 check withholds
        # exactly as if no W-4 were on file.
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        fed_default, _ = self._income_tax(db, draft_paycheck(emp, pp, None, db))

        db.add(W4Election(employee_id=salaried_employee.id, effective_date=date(2025, 1, 1),
                          filing_status="married_filing_jointly", exempt=True))
        db.commit()
        db.expire_all()
        emp = _load_employee(db, salaried_employee.id)
        fed_expired, _ = self._income_tax(db, draft_paycheck(emp, pp, None, db))
        assert fed_expired == fed_default > Decimal("0")

    def test_replaces_existing_draft(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        draft_paycheck(emp, pp, None, db)
        draft_paycheck(emp, pp, None, db)
        count = db.query(Paycheck).filter(
            Paycheck.employee_id == salaried_employee.id,
            Paycheck.pay_period_id == pay_period.id,
        ).count()
        assert count == 1

    def test_ytd_gross_stored(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        # No prior paychecks → ytd_gross = gross_wages
        assert paycheck.ytd_gross == Decimal("2500.00")

    def test_pretax_deduction_reduces_taxable_wages(self, db, salaried_employee, benefit_plan, pay_period):
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
        ))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        # Pre-tax deductions reduce total_deductions
        assert paycheck.total_deductions == Decimal("150.00")
        # SS should be on $2,350 taxable wages: $2,350 × 6.2% = $145.70
        ss_lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.description == "Social Security (Employee)",
        ).all()
        assert ss_lines[0].amount == Decimal("145.70")

    def test_post_tax_deduction_reduces_net_pay(self, db, salaried_employee, company, pay_period):
        roth_plan = BenefitPlan(
            company_id=company.id,
            name="Roth 401k",
            benefit_type="roth_401k",
            employee_contribution_type="fixed",
            employee_contribution_amount=100.00,
            pre_tax=False,
            active=True,
        )
        db.add(roth_plan)
        db.flush()
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=roth_plan.id,
            effective_date=date(2026, 1, 1),
        ))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        assert paycheck.total_deductions == Decimal("100.00")
        # Verify post-tax deduction line exists
        post_tax_lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.line_type == "deduction",
            PaycheckLine.is_pre_tax == False,
        ).all()
        assert len(post_tax_lines) == 1
        assert post_tax_lines[0].description == "Roth 401k"
        assert post_tax_lines[0].amount == Decimal("100.00")
        # Net pay should be less than gross minus taxes
        no_deduction_emp = _load_employee(db, salaried_employee.id)
        assert paycheck.net_pay < paycheck.gross_wages - paycheck.total_taxes_withheld

    def test_garnishment_deducted_from_paycheck(self, db, salaried_employee, pay_period):
        from datetime import date as d
        order = GarnishmentOrder(
            employee_id=salaried_employee.id,
            garnishment_type="creditor",
            payee_name="Collections Inc",
            amount=Decimal("200.00"),
            amount_type="fixed",
            effective_date=d(2026, 1, 1),
            active=True,
        )
        db.add(order)
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, None, db)
        # Garnishment line exists
        garn_lines = db.query(PaycheckLine).filter(
            PaycheckLine.paycheck_id == paycheck.id,
            PaycheckLine.description.like("Garnishment%"),
        ).all()
        assert len(garn_lines) == 1
        assert garn_lines[0].amount == Decimal("200.00")
        # total_deductions includes garnishment
        assert paycheck.total_deductions >= Decimal("200.00")
        # net_pay reduced
        assert paycheck.net_pay < paycheck.gross_wages - paycheck.total_taxes_withheld

    def test_hourly_with_timesheet(self, db, hourly_employee, pay_period):
        ts = Timesheet(
            employee_id=hourly_employee.id,
            pay_period_id=pay_period.id,
            regular_hours=80,
            overtime_hours=5,
        )
        db.add(ts)
        db.commit()
        emp = _load_employee(db, hourly_employee.id)
        pp = _load_pay_period(db, pay_period.id)
        paycheck = draft_paycheck(emp, pp, ts, db)
        # $18.50 × 80 + $18.50 × 1.5 × 5 = $1,480 + $138.75 = $1,618.75
        assert paycheck.gross_wages == Decimal("1618.75")


# ── Payroll workflow ─────────────────────────────────────────────────────────

class TestPayrollWorkflow:
    def _run_draft(self, db, salaried_employee, pay_period):
        pp = db.query(PayPeriod).options(
            joinedload(PayPeriod.company),
            joinedload(PayPeriod.paychecks),
        ).filter(PayPeriod.id == pay_period.id).one()
        paychecks = calculate_payroll_run(pp, db)
        db.refresh(pp)
        return paychecks, pp

    def test_calculate_run_sets_status_draft(self, db, salaried_employee, pay_period):
        _, pp = self._run_draft(db, salaried_employee, pay_period)
        assert pp.status == "draft"

    def test_calculate_run_creates_one_paycheck(self, db, salaried_employee, pay_period):
        paychecks, _ = self._run_draft(db, salaried_employee, pay_period)
        assert len(paychecks) == 1

    def test_calculate_run_skips_inactive_employees(self, db, company, pay_period):
        # Only active employees should be included
        terminated = Employee(
            company_id=company.id,
            first_name="Ex",
            last_name="Worker",
            employment_type="salaried",
            pay_rate=50000,
            status="terminated",
            state="OK",
            flsa_exempt=True,
        )
        db.add(terminated)
        db.commit()
        pp = db.query(PayPeriod).options(
            joinedload(PayPeriod.company),
        ).filter(PayPeriod.id == pay_period.id).one()
        paychecks = calculate_payroll_run(pp, db)
        # No active employees in this test (salaried_employee fixture is not included here)
        for pc in paychecks:
            assert pc.employee_id != terminated.id

    def test_approve_sets_approved_status(self, db, salaried_employee, pay_period):
        paychecks, pp = self._run_draft(db, salaried_employee, pay_period)
        approve_payroll_run(pp, db)
        db.refresh(pp)
        assert pp.status == "approved"
        db.refresh(paychecks[0])
        assert paychecks[0].status == "approved"

    def test_approve_wrong_status_raises(self, db, pay_period):
        pp = db.query(PayPeriod).filter(PayPeriod.id == pay_period.id).one()
        with pytest.raises(ValueError, match="Cannot approve"):
            approve_payroll_run(pp, db)

    def test_mark_paid(self, db, salaried_employee, pay_period):
        paychecks, pp = self._run_draft(db, salaried_employee, pay_period)
        approve_payroll_run(pp, db)
        db.refresh(pp)
        mark_period_paid(pp, db)
        db.refresh(pp)
        assert pp.status == "paid"
        db.refresh(paychecks[0])
        assert paychecks[0].status == "paid"

    def test_mark_paid_wrong_status_raises(self, db, salaried_employee, pay_period):
        _, pp = self._run_draft(db, salaried_employee, pay_period)
        with pytest.raises(ValueError, match="Cannot mark paid"):
            mark_period_paid(pp, db)

    def test_void_draft_paycheck(self, db, salaried_employee, pay_period):
        paychecks, _ = self._run_draft(db, salaried_employee, pay_period)
        void_paycheck(paychecks[0], "Entry error", db)
        db.refresh(paychecks[0])
        assert paychecks[0].status == "voided"
        assert paychecks[0].void_reason == "Entry error"
        assert paychecks[0].voided_at is not None

    def test_void_paid_check_raises(self, db, salaried_employee, pay_period):
        paychecks, pp = self._run_draft(db, salaried_employee, pay_period)
        approve_payroll_run(pp, db)
        db.refresh(pp)
        mark_period_paid(pp, db)
        db.refresh(paychecks[0])
        with pytest.raises(ValueError, match="paid"):
            void_paycheck(paychecks[0], "reason", db)

    def test_void_already_voided_raises(self, db, salaried_employee, pay_period):
        paychecks, _ = self._run_draft(db, salaried_employee, pay_period)
        void_paycheck(paychecks[0], "first", db)
        with pytest.raises(ValueError, match="already"):
            void_paycheck(paychecks[0], "second", db)


# ── Router tests ─────────────────────────────────────────────────────────────

class TestPayrollRoutes:
    def _create_pp(self, db, company):
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
        return pp

    def test_list_pay_periods(self, client):
        r = client.get("/payroll/")
        assert r.status_code == 200

    def test_new_pay_period_form(self, client):
        r = client.get("/payroll/new")
        assert r.status_code == 200

    def test_create_pay_period_redirects(self, client, company):
        r = client.post("/payroll/new", data={
            "company_id": company.id,
            "start_date": "2026-05-01",
            "end_date": "2026-05-14",
            "pay_date": "2026-05-20",
            "frequency": "biweekly",
        })
        assert r.status_code == 303
        assert "/payroll/" in r.headers["location"]

    def test_create_missing_dates_returns_422(self, client, company):
        r = client.post("/payroll/new", data={
            "company_id": company.id,
            "start_date": "",
            "end_date": "",
            "pay_date": "2026-05-20",
            "frequency": "biweekly",
        })
        assert r.status_code == 422

    def test_get_period_detail(self, client, db, company):
        pp = self._create_pp(db, company)
        r = client.get(f"/payroll/{pp.id}")
        assert r.status_code == 200

    def test_404_nonexistent_period(self, client):
        r = client.get("/payroll/99999")
        assert r.status_code == 404

    def test_calculate_draft(self, client, db, company, salaried_employee):
        pp = self._create_pp(db, company)
        r = client.post(f"/payroll/{pp.id}/calculate")
        assert r.status_code == 303
        db.refresh(pp)
        assert pp.status == "draft"
        count = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).count()
        assert count == 1

    def test_approve_period(self, client, db, company, salaried_employee):
        pp = self._create_pp(db, company)
        client.post(f"/payroll/{pp.id}/calculate")
        r = client.post(f"/payroll/{pp.id}/approve")
        assert r.status_code == 303
        db.refresh(pp)
        assert pp.status == "approved"

    def test_mark_paid_period(self, client, db, company, salaried_employee):
        pp = self._create_pp(db, company)
        client.post(f"/payroll/{pp.id}/calculate")
        client.post(f"/payroll/{pp.id}/approve")
        r = client.post(f"/payroll/{pp.id}/mark-paid")
        assert r.status_code == 303
        db.refresh(pp)
        assert pp.status == "paid"

    def test_paycheck_detail_page(self, client, db, company, salaried_employee):
        pp = self._create_pp(db, company)
        client.post(f"/payroll/{pp.id}/calculate")
        paycheck = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).first()
        r = client.get(f"/payroll/paychecks/{paycheck.id}")
        assert r.status_code == 200

    def test_void_paycheck_route(self, client, db, company, salaried_employee):
        pp = self._create_pp(db, company)
        client.post(f"/payroll/{pp.id}/calculate")
        paycheck = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).first()
        r = client.post(f"/payroll/paychecks/{paycheck.id}/void", data={"reason": "Test void"})
        assert r.status_code == 303
        db.refresh(paycheck)
        assert paycheck.status == "voided"
        assert paycheck.void_reason == "Test void"

    def test_timesheet_grid(self, client, db, company, hourly_employee):
        pp = self._create_pp(db, company)
        r = client.get(f"/payroll/{pp.id}/timesheets")
        assert r.status_code == 200

    def test_save_timesheet(self, client, db, company, hourly_employee):
        pp = self._create_pp(db, company)
        r = client.post(f"/payroll/{pp.id}/timesheets/{hourly_employee.id}", data={
            "regular_hours": "40",
            "overtime_hours": "5",
            "double_time_hours": "0",
            "pto_hours": "0",
            "sick_hours": "0",
            "holiday_hours": "0",
        })
        assert r.status_code == 303
        ts = db.query(Timesheet).filter(
            Timesheet.employee_id == hourly_employee.id,
            Timesheet.pay_period_id == pp.id,
        ).first()
        assert ts is not None
        assert float(ts.regular_hours) == 40.0
        assert float(ts.overtime_hours) == 5.0

    def test_save_timesheet_htmx_returns_partial(self, client, db, company, hourly_employee):
        pp = self._create_pp(db, company)
        r = client.post(
            f"/payroll/{pp.id}/timesheets/{hourly_employee.id}",
            data={"regular_hours": "40"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "ts-row-" in r.text

    def test_paycheck_pdf_returns_pdf(self, client, db, company, salaried_employee, monkeypatch):
        import sys, types
        # Stub out weasyprint so the test works without GTK installed
        fake_html_instance = types.SimpleNamespace(write_pdf=lambda: b"%PDF-1.4 stub")
        fake_weasyprint = types.ModuleType("weasyprint")
        fake_weasyprint.HTML = lambda string: fake_html_instance
        monkeypatch.setitem(sys.modules, "weasyprint", fake_weasyprint)

        pp = self._create_pp(db, company)
        client.post(f"/payroll/{pp.id}/calculate")
        paycheck = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).first()
        r = client.get(f"/payroll/paychecks/{paycheck.id}/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert b"%PDF" in r.content

    def test_paycheck_pdf_404_for_missing(self, client):
        r = client.get("/payroll/paychecks/99999/pdf")
        assert r.status_code == 404


# ── Garnishment route tests ─────────────────────────────────────────────────

class TestGarnishmentRoutes:
    def test_garnishment_list_page(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}/garnishments")
        assert r.status_code == 200
        assert "Garnishment" in r.text

    def test_create_garnishment(self, client, db, salaried_employee):
        r = client.post(f"/employees/{salaried_employee.id}/garnishments/new", data={
            "garnishment_type": "creditor",
            "payee_name": "Collections Inc",
            "amount": "200",
            "amount_type": "fixed",
            "effective_date": "2026-01-01",
        })
        assert r.status_code == 303
        order = db.query(GarnishmentOrder).filter(
            GarnishmentOrder.employee_id == salaried_employee.id,
        ).first()
        assert order is not None
        assert order.payee_name == "Collections Inc"
        assert float(order.amount) == 200.0

    def test_deactivate_garnishment(self, client, db, salaried_employee):
        from datetime import date as d
        order = GarnishmentOrder(
            employee_id=salaried_employee.id,
            garnishment_type="creditor",
            payee_name="Test Co",
            amount=100,
            amount_type="fixed",
            effective_date=d(2026, 1, 1),
            active=True,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.post(f"/employees/{salaried_employee.id}/garnishments/{order.id}/deactivate", data={
            "end_date": "2026-06-01",
        })
        assert r.status_code == 303
        db.refresh(order)
        assert order.active is False
        assert order.end_date == d(2026, 6, 1)


# ── Percent plans, employer match, client liabilities ───────────────────────

def _enroll(db, employee, **plan_kwargs):
    plan = BenefitPlan(company_id=employee.company_id, active=True, **plan_kwargs)
    db.add(plan)
    db.flush()
    db.add(EmployeeBenefitEnrollment(
        employee_id=employee.id, benefit_plan_id=plan.id, effective_date=date(2026, 1, 1),
    ))
    db.commit()
    return plan


class TestPercentPlansAndMatch:
    def test_percent_plan_deducts_percent_of_gross(self, db, salaried_employee, pay_period):
        _enroll(db, salaried_employee, name="401k", benefit_type="traditional_401k",
                employee_contribution_type="percent", employee_contribution_amount=5, pre_tax=True)
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        # $2,500 biweekly gross x 5%
        line = db.query(PaycheckLine).filter_by(paycheck_id=paycheck.id, description="401k").one()
        assert line.amount == Decimal("125.00")
        assert paycheck.total_deductions == Decimal("125.00")

    def test_percent_override_is_a_percent(self, db, salaried_employee, pay_period):
        plan = _enroll(db, salaried_employee, name="401k", benefit_type="traditional_401k",
                       employee_contribution_type="percent", employee_contribution_amount=5, pre_tax=True)
        enrollment = db.query(EmployeeBenefitEnrollment).filter_by(benefit_plan_id=plan.id).one()
        enrollment.employee_override_amount = 10
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        assert get_employee_pre_tax_deductions(emp, Decimal("2500")) == Decimal("250.00")

    def test_employer_match_line_capped(self, db, salaried_employee, pay_period):
        # Employee gives 6% ($150); match 100% up to 4% of gross ($100)
        _enroll(db, salaried_employee, name="401k", benefit_type="traditional_401k",
                employee_contribution_type="percent", employee_contribution_amount=6, pre_tax=True,
                employer_match_percent=100, employer_match_cap_percent=4)
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        match = db.query(PaycheckLine).filter_by(
            paycheck_id=paycheck.id, line_type="employer_contribution").one()
        assert match.amount == Decimal("100.00")
        assert match.description == "401k (Employer Match)"
        # Match is employer money: not part of the employee's deductions
        assert paycheck.total_deductions == Decimal("150.00")

    def test_no_match_line_without_match_settings(self, db, salaried_employee, benefit_plan, pay_period):
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        assert db.query(PaycheckLine).filter_by(
            paycheck_id=paycheck.id, line_type="employer_contribution").count() == 0


class TestClientLiabilityRows:
    def test_garnishment_creates_liability_for_payee(self, db, salaried_employee, pay_period):
        db.add(GarnishmentOrder(
            employee_id=salaried_employee.id, garnishment_type="child_support",
            payee_name="OK Child Support", amount=Decimal("200.00"), amount_type="fixed",
            effective_date=date(2026, 1, 1), active=True))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        db.commit()
        li = db.query(ClientLiability).filter_by(paycheck_id=paycheck.id).one()
        assert (li.payee_name, li.liability_type) == ("OK Child Support", "child_support_remittance")
        assert li.amount == Decimal("200.00")
        assert li.company_id == salaried_employee.company_id
        assert li.pay_period_id == pay_period.id

    def test_benefit_creates_liability_including_match(self, db, salaried_employee, pay_period):
        _enroll(db, salaried_employee, name="Roth", benefit_type="roth_401k",
                employee_contribution_type="fixed", employee_contribution_amount=100, pre_tax=False,
                employer_match_percent=50, employer_match_cap_percent=10)
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        db.commit()
        li = db.query(ClientLiability).filter_by(paycheck_id=paycheck.id).one()
        assert (li.payee_name, li.liability_type) == ("Roth", "retirement_deposit")
        assert li.amount == Decimal("150.00")  # 100 employee + 50 match

    def test_health_plan_is_benefit_premium(self, db, salaried_employee, benefit_plan, pay_period):
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        db.commit()
        emp = _load_employee(db, salaried_employee.id)
        draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        db.commit()
        assert db.query(ClientLiability).one().liability_type == "benefit_premium"

    def test_recalculate_replaces_liabilities(self, db, salaried_employee, benefit_plan, pay_period):
        db.add(EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id, benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1)))
        db.commit()
        for _ in range(2):
            emp = _load_employee(db, salaried_employee.id)
            draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
            db.commit()
        assert db.query(ClientLiability).count() == 1


class TestGrossOverride:
    def test_override_replaces_salary(self, db, salaried_employee, pay_period):
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(
            emp, _load_pay_period(db, pay_period.id), None, db,
            gross_override=Decimal("1000"), earning_label="Bonus")
        assert paycheck.gross_wages == Decimal("1000.00")
        line = db.query(PaycheckLine).filter_by(paycheck_id=paycheck.id, line_type="earning").one()
        assert (line.description, line.amount) == ("Bonus", Decimal("1000.00"))


class TestEmployerMatchDisplay:
    def test_match_shown_on_paycheck_page(self, client, db, salaried_employee, pay_period):
        _enroll(db, salaried_employee, name="401k", benefit_type="traditional_401k",
                employee_contribution_type="percent", employee_contribution_amount=4, pre_tax=True,
                employer_match_percent=100, employer_match_cap_percent=4)
        emp = _load_employee(db, salaried_employee.id)
        paycheck = draft_paycheck(emp, _load_pay_period(db, pay_period.id), None, db)
        db.commit()
        r = client.get(f"/payroll/paychecks/{paycheck.id}")
        assert r.status_code == 200
        assert "401k (Employer Match)" in r.text


# ── Variance flag, void route errors, PDF fallback ──────────────────────────

class TestVarianceFlag:
    def _run(self, db, company, employee, hours, pay_date, approve):
        pp = PayPeriod(company_id=company.id, start_date=pay_date, end_date=pay_date,
                       pay_date=pay_date, frequency="biweekly", status="open")
        db.add(pp)
        db.flush()
        db.add(Timesheet(employee_id=employee.id, pay_period_id=pp.id, regular_hours=hours))
        db.commit()
        calculate_payroll_run(pp, db)
        if approve:
            approve_payroll_run(pp, db)
        return pp

    def test_swing_over_20_percent_is_flagged(self, client, db, company, hourly_employee):
        self._run(db, company, hourly_employee, 80, date(2026, 5, 6), approve=True)
        current = self._run(db, company, hourly_employee, 40, date(2026, 5, 20), approve=False)
        assert "differ" in client.get(f"/payroll/{current.id}").text

    def test_swing_under_20_percent_not_flagged(self, client, db, company, hourly_employee):
        self._run(db, company, hourly_employee, 80, date(2026, 5, 6), approve=True)
        current = self._run(db, company, hourly_employee, 72, date(2026, 5, 20), approve=False)
        assert "differ" not in client.get(f"/payroll/{current.id}").text

    def test_no_prior_paycheck_not_flagged(self, client, db, company, hourly_employee):
        current = self._run(db, company, hourly_employee, 40, date(2026, 5, 20), approve=False)
        assert "differ" not in client.get(f"/payroll/{current.id}").text

    def test_only_approved_or_paid_priors_count(self, client, db, company, hourly_employee):
        # A prior period still in draft is not a baseline.
        self._run(db, company, hourly_employee, 80, date(2026, 5, 6), approve=False)
        current = self._run(db, company, hourly_employee, 40, date(2026, 5, 20), approve=False)
        assert "differ" not in client.get(f"/payroll/{current.id}").text


class TestVoidRoute:
    def _approved_check(self, db, salaried_employee, pay_period):
        pp = db.query(PayPeriod).options(joinedload(PayPeriod.company)).filter_by(id=pay_period.id).one()
        paycheck = calculate_payroll_run(pp, db)[0]
        approve_payroll_run(pp, db)
        return pp, paycheck

    def test_void_approved_check(self, client, db, salaried_employee, pay_period):
        pp, paycheck = self._approved_check(db, salaried_employee, pay_period)
        r = client.post(f"/payroll/paychecks/{paycheck.id}/void", data={"reason": "Wrong amount"})
        assert r.status_code == 303
        db.refresh(paycheck)
        assert paycheck.status == "voided"

    def test_void_twice_is_400(self, client, db, salaried_employee, pay_period):
        pp, paycheck = self._approved_check(db, salaried_employee, pay_period)
        client.post(f"/payroll/paychecks/{paycheck.id}/void", data={"reason": "first"})
        r = client.post(f"/payroll/paychecks/{paycheck.id}/void", data={"reason": "second"})
        assert r.status_code == 400
        assert "already voided" in r.text

    def test_void_paid_check_is_400(self, client, db, salaried_employee, pay_period):
        pp, paycheck = self._approved_check(db, salaried_employee, pay_period)
        mark_period_paid(pp, db)
        r = client.post(f"/payroll/paychecks/{paycheck.id}/void", data={"reason": "too late"})
        assert r.status_code == 400
        db.refresh(paycheck)
        assert paycheck.status == "paid"

    def test_void_requires_a_reason(self, client, db, salaried_employee, pay_period):
        pp, paycheck = self._approved_check(db, salaried_employee, pay_period)
        assert client.post(f"/payroll/paychecks/{paycheck.id}/void", data={}).status_code == 422


class TestPdfFallback:
    def test_missing_gtk_runtime_is_503_not_500(self, client, db, salaried_employee, pay_period, monkeypatch):
        import sys
        import types
        pp = db.query(PayPeriod).options(joinedload(PayPeriod.company)).filter_by(id=pay_period.id).one()
        paycheck = calculate_payroll_run(pp, db)[0]

        broken = types.ModuleType("weasyprint")

        def _no_gtk(name):
            raise OSError("cannot load library 'libgobject-2.0-0'")

        broken.__getattr__ = _no_gtk
        monkeypatch.setitem(sys.modules, "weasyprint", broken)
        r = client.get(f"/payroll/paychecks/{paycheck.id}/pdf")
        assert r.status_code == 503
        assert "GTK" in r.text
