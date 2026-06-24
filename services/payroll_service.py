"""
Payroll run service: gross wage computation, YTD accumulation, draft/approve/void workflows.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models.employee import Employee
from models.payroll import PayPeriod, Timesheet, Paycheck, PaycheckLine
from models.benefit import EmployeeBenefitEnrollment
from models.garnishment import GarnishmentOrder
from models.company import Company
from tax_engine.models import PAY_PERIOD_FACTORS, PaycheckInput, W4Input, OKWithholdingInput, GarnishmentInputItem
from tax_engine.calculator import calculate_paycheck

_TWO = Decimal("0.01")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def get_pay_frequency(employee: Employee, company: Company) -> str:
    return employee.pay_frequency or company.pay_frequency


def calc_employee_gross(
    employee: Employee,
    timesheet: Optional[Timesheet],
    frequency: str,
) -> Decimal:
    """Gross wages for one employee for one pay period."""
    if employee.employment_type == "salaried":
        periods = PAY_PERIOD_FACTORS[frequency]
        return _round2(Decimal(str(employee.pay_rate)) / Decimal(str(periods)))

    if not timesheet:
        return Decimal("0.00")

    rate = Decimal(str(employee.pay_rate))
    regular = Decimal(str(timesheet.regular_hours or 0)) * rate
    overtime = Decimal(str(timesheet.overtime_hours or 0)) * rate * Decimal("1.5")
    double_time = Decimal(str(timesheet.double_time_hours or 0)) * rate * Decimal("2")
    pto = Decimal(str(timesheet.pto_hours or 0)) * rate
    sick = Decimal(str(timesheet.sick_hours or 0)) * rate
    holiday = Decimal(str(timesheet.holiday_hours or 0)) * rate
    return _round2(regular + overtime + double_time + pto + sick + holiday)


def _sum_employee_deductions(employee: Employee, pre_tax: bool) -> Decimal:
    total = Decimal("0")
    for enrollment in employee.benefit_enrollments:
        if enrollment.end_date:
            continue
        plan = enrollment.plan
        if plan.pre_tax != pre_tax or not plan.active:
            continue
        if plan.employee_contribution_type != "fixed":
            continue
        amount = (
            Decimal(str(enrollment.employee_override_amount))
            if enrollment.employee_override_amount is not None
            else Decimal(str(plan.employee_contribution_amount))
        )
        total += amount
    return total


def get_employee_pre_tax_deductions(employee: Employee) -> Decimal:
    return _sum_employee_deductions(employee, pre_tax=True)


def get_employee_post_tax_deductions(employee: Employee) -> Decimal:
    return _sum_employee_deductions(employee, pre_tax=False)


def get_active_garnishments(employee: Employee) -> list[GarnishmentInputItem]:
    """Build garnishment inputs from active orders."""
    items = []
    for order in getattr(employee, "garnishment_orders", []):
        if not order.active or order.end_date:
            continue
        items.append(GarnishmentInputItem(
            garnishment_type=order.garnishment_type,
            amount=Decimal(str(order.amount or 0)),
            percent=Decimal(str(order.percent or 0)),
            amount_type=order.amount_type,
            max_total=Decimal(str(order.max_total or 0)),
            ytd_withheld=Decimal(str(order.ytd_withheld or 0)),
            order_id=order.id,
        ))
    return items


def get_ytd_prior(employee_id: int, pay_period: PayPeriod, db: Session) -> dict:
    """
    Sum wages from all non-voided paychecks in the same calendar year whose
    pay period's pay_date precedes the current pay period's pay_date.
    """
    year = pay_period.pay_date.year
    year_start = date(year, 1, 1)

    prior_filter = [
        Paycheck.employee_id == employee_id,
        Paycheck.status != "voided",
        PayPeriod.pay_date < pay_period.pay_date,
        PayPeriod.pay_date >= year_start,
    ]

    row = (
        db.query(
            func.coalesce(func.sum(Paycheck.gross_wages), 0).label("gross"),
            func.coalesce(
                func.sum(Paycheck.gross_wages - Paycheck.total_deductions), 0
            ).label("taxable"),
        )
        .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
        .filter(*prior_filter)
        .one()
    )

    tax_sums = (
        db.query(
            PaycheckLine.description,
            func.coalesce(func.sum(PaycheckLine.amount), 0).label("total"),
        )
        .join(Paycheck, PaycheckLine.paycheck_id == Paycheck.id)
        .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
        .filter(
            *prior_filter,
            PaycheckLine.line_type.in_(["tax", "employer_tax"]),
        )
        .group_by(PaycheckLine.description)
        .all()
    )
    tax_map = {r.description: Decimal(str(r.total)) for r in tax_sums}

    gross = Decimal(str(row.gross))
    taxable = Decimal(str(row.taxable))
    zero = Decimal("0")
    return {
        "gross": gross,
        "ss_wages": taxable,
        "futa_wages": taxable,
        "suta_wages": taxable,
        "federal_tax": tax_map.get("Federal Income Tax", zero),
        "state_tax": tax_map.get("Oklahoma Income Tax", zero),
        "fica_employee": (
            tax_map.get("Social Security (Employee)", zero)
            + tax_map.get("Medicare (Employee)", zero)
        ),
        "fica_employer": (
            tax_map.get("Social Security (Employer)", zero)
            + tax_map.get("Medicare (Employer)", zero)
        ),
        "futa": tax_map.get("FUTA", zero),
        "suta": tax_map.get("SUTA", zero),
    }


def _add_hour_line(
    lines: list,
    paycheck_id: int,
    description: str,
    hours,
    pay_rate: Decimal,
) -> None:
    if not hours:
        return
    h = Decimal(str(hours))
    if h == 0:
        return
    lines.append(
        PaycheckLine(
            paycheck_id=paycheck_id,
            line_type="earning",
            description=description,
            amount=_round2(h * pay_rate),
            hours=hours,
            rate=pay_rate,
            is_pre_tax=False,
            is_taxable=True,
        )
    )


def _create_paycheck_lines(
    paycheck: Paycheck,
    employee: Employee,
    timesheet: Optional[Timesheet],
    result,
    db: Session,
) -> None:
    lines = []
    rate = Decimal(str(employee.pay_rate))

    # Earnings
    if employee.employment_type == "salaried":
        lines.append(
            PaycheckLine(
                paycheck_id=paycheck.id,
                line_type="earning",
                description="Regular Salary",
                amount=result.gross_wages,
                is_pre_tax=False,
                is_taxable=True,
            )
        )
    elif timesheet:
        _add_hour_line(lines, paycheck.id, "Regular Pay", timesheet.regular_hours, rate)
        _add_hour_line(lines, paycheck.id, "Overtime Pay", timesheet.overtime_hours, rate * Decimal("1.5"))
        _add_hour_line(lines, paycheck.id, "Double Time", timesheet.double_time_hours, rate * Decimal("2"))
        _add_hour_line(lines, paycheck.id, "PTO", timesheet.pto_hours, rate)
        _add_hour_line(lines, paycheck.id, "Sick Pay", timesheet.sick_hours, rate)
        _add_hour_line(lines, paycheck.id, "Holiday Pay", timesheet.holiday_hours, rate)

    # Pre-tax deductions
    for enrollment in employee.benefit_enrollments:
        if enrollment.end_date or not enrollment.plan.pre_tax or not enrollment.plan.active:
            continue
        if enrollment.plan.employee_contribution_type != "fixed":
            continue
        amt = (
            Decimal(str(enrollment.employee_override_amount))
            if enrollment.employee_override_amount is not None
            else Decimal(str(enrollment.plan.employee_contribution_amount))
        )
        lines.append(
            PaycheckLine(
                paycheck_id=paycheck.id,
                line_type="deduction",
                description=enrollment.plan.name,
                amount=amt,
                is_pre_tax=True,
                is_taxable=False,
            )
        )

    # Post-tax deductions
    for enrollment in employee.benefit_enrollments:
        if enrollment.end_date or enrollment.plan.pre_tax or not enrollment.plan.active:
            continue
        if enrollment.plan.employee_contribution_type != "fixed":
            continue
        amt = (
            Decimal(str(enrollment.employee_override_amount))
            if enrollment.employee_override_amount is not None
            else Decimal(str(enrollment.plan.employee_contribution_amount))
        )
        lines.append(
            PaycheckLine(
                paycheck_id=paycheck.id,
                line_type="deduction",
                description=enrollment.plan.name,
                amount=amt,
                is_pre_tax=False,
                is_taxable=False,
            )
        )

    # Garnishment lines
    for gr in getattr(result, "garnishment_results", []):
        if gr.amount > 0:
            label = gr.garnishment_type.replace("_", " ").title()
            lines.append(
                PaycheckLine(
                    paycheck_id=paycheck.id,
                    line_type="deduction",
                    description=f"Garnishment - {label}",
                    amount=gr.amount,
                    is_pre_tax=False,
                    is_taxable=False,
                )
            )

    t = result.taxes
    for desc, amount in [
        ("Federal Income Tax", t.federal_income_tax),
        ("Oklahoma Income Tax", t.ok_income_tax),
        ("Social Security (Employee)", t.ss_employee),
        ("Medicare (Employee)", t.medicare_employee),
    ]:
        if amount > 0:
            lines.append(
                PaycheckLine(
                    paycheck_id=paycheck.id,
                    line_type="tax",
                    description=desc,
                    amount=amount,
                    is_pre_tax=False,
                    is_taxable=False,
                )
            )

    for desc, amount in [
        ("Social Security (Employer)", t.ss_employer),
        ("Medicare (Employer)", t.medicare_employer),
        ("FUTA", t.futa),
        ("SUTA", t.suta),
        ("Workers Comp", t.workers_comp),
    ]:
        if amount > 0:
            lines.append(
                PaycheckLine(
                    paycheck_id=paycheck.id,
                    line_type="employer_tax",
                    description=desc,
                    amount=amount,
                    is_pre_tax=False,
                    is_taxable=False,
                )
            )

    for line in lines:
        db.add(line)


def draft_paycheck(
    employee: Employee,
    pay_period: PayPeriod,
    timesheet: Optional[Timesheet],
    db: Session,
) -> Paycheck:
    """Calculate and save a draft Paycheck, replacing any existing draft for this employee/period."""
    existing = (
        db.query(Paycheck)
        .filter(
            Paycheck.employee_id == employee.id,
            Paycheck.pay_period_id == pay_period.id,
            Paycheck.status == "draft",
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    company = pay_period.company
    frequency = get_pay_frequency(employee, company)
    gross = calc_employee_gross(employee, timesheet, frequency)
    ytd = get_ytd_prior(employee.id, pay_period, db)
    pre_tax = get_employee_pre_tax_deductions(employee)
    post_tax = get_employee_post_tax_deductions(employee)
    garnishment_items = get_active_garnishments(employee)

    w4 = None
    if employee.active_w4:
        e = employee.active_w4
        w4 = W4Input(
            filing_status=e.filing_status,
            multiple_jobs=bool(e.multiple_jobs),
            dependents_amount=Decimal(str(e.dependents_amount)),
            other_income=Decimal(str(e.other_income)),
            deductions_amount=Decimal(str(e.deductions_amount)),
            extra_withholding=Decimal(str(e.extra_withholding)),
        )

    ok_w = None
    if employee.active_ok_withholding:
        e = employee.active_ok_withholding
        ok_w = OKWithholdingInput(
            filing_status=e.filing_status,
            allowances=e.allowances,
            extra_withholding=Decimal(str(e.extra_withholding)),
        )

    suta_rate = Decimal(str(company.suta_rate or "0.027"))
    wc_rate = Decimal("0")
    if employee.workers_comp_code:
        wc_rate = Decimal(str(employee.workers_comp_code.rate_per_100_wages or 0))

    inp = PaycheckInput(
        gross_wages=gross,
        pay_frequency=frequency,
        ytd_gross_prior=ytd["gross"],
        ytd_ss_wages_prior=ytd["ss_wages"],
        ytd_futa_wages_prior=ytd["futa_wages"],
        ytd_suta_wages_prior=ytd["suta_wages"],
        pre_tax_deductions=pre_tax,
        post_tax_deductions=post_tax,
        garnishments=garnishment_items,
        w4=w4,
        ok_withholding=ok_w,
        suta_rate=suta_rate,
        workers_comp_rate=wc_rate,
    )

    result = calculate_paycheck(inp)
    t = result.taxes

    paycheck = Paycheck(
        employee_id=employee.id,
        pay_period_id=pay_period.id,
        status="draft",
        gross_wages=result.gross_wages,
        total_deductions=result.total_deductions,
        total_taxes_withheld=result.total_employee_taxes,
        net_pay=result.net_pay,
        employer_fica=t.ss_employer + t.medicare_employer,
        employer_futa=t.futa,
        employer_suta=t.suta,
        employer_workers_comp=t.workers_comp,
        ytd_gross=ytd["gross"] + result.gross_wages,
        ytd_federal_tax=ytd["federal_tax"] + t.federal_income_tax,
        ytd_state_tax=ytd["state_tax"] + t.ok_income_tax,
        ytd_fica_employee=ytd["fica_employee"] + t.ss_employee + t.medicare_employee,
        ytd_fica_employer=ytd["fica_employer"] + t.ss_employer + t.medicare_employer,
        ytd_futa=ytd["futa"] + t.futa,
        ytd_suta=ytd["suta"] + t.suta,
    )
    db.add(paycheck)
    db.flush()

    _create_paycheck_lines(paycheck, employee, timesheet, result, db)
    return paycheck


def calculate_payroll_run(pay_period: PayPeriod, db: Session) -> list:
    """Draft all active employees for the pay period. Sets status to 'draft'."""
    employees = (
        db.query(Employee)
        .options(
            joinedload(Employee.w4_elections),
            joinedload(Employee.ok_withholding_elections),
            joinedload(Employee.benefit_enrollments).joinedload(EmployeeBenefitEnrollment.plan),
            joinedload(Employee.workers_comp_code),
            joinedload(Employee.garnishment_orders),
        )
        .filter(
            Employee.company_id == pay_period.company_id,
            Employee.status == "active",
        )
        .all()
    )

    timesheets_by_emp = {
        ts.employee_id: ts
        for ts in db.query(Timesheet).filter(
            Timesheet.pay_period_id == pay_period.id,
        ).all()
    }

    paychecks = []
    for employee in employees:
        timesheet = timesheets_by_emp.get(employee.id)
        paycheck = draft_paycheck(employee, pay_period, timesheet, db)
        paychecks.append(paycheck)

    pay_period.status = "draft"
    db.commit()
    return paychecks


def approve_payroll_run(pay_period: PayPeriod, db: Session) -> None:
    """Approve all draft paychecks and lock the pay period."""
    if pay_period.status != "draft":
        raise ValueError(f"Cannot approve: pay period is '{pay_period.status}'")

    now = datetime.now(timezone.utc)
    for paycheck in pay_period.paychecks:
        if paycheck.status == "draft":
            paycheck.status = "approved"
            paycheck.approved_at = now

    pay_period.status = "approved"
    db.commit()


def mark_period_paid(pay_period: PayPeriod, db: Session) -> None:
    """Mark all approved paychecks as paid and transition the pay period to 'paid'."""
    if pay_period.status != "approved":
        raise ValueError(f"Cannot mark paid: pay period is '{pay_period.status}'")

    now = datetime.now(timezone.utc)
    for paycheck in pay_period.paychecks:
        if paycheck.status == "approved":
            paycheck.status = "paid"
            paycheck.paid_at = now

    pay_period.status = "paid"
    db.commit()


def void_paycheck(paycheck: Paycheck, reason: str, db: Session) -> None:
    """Void a single paycheck. Raises ValueError if already voided or paid."""
    if paycheck.status == "voided":
        raise ValueError("Paycheck is already voided")
    if paycheck.status == "paid":
        raise ValueError("Cannot void a paid paycheck")

    paycheck.status = "voided"
    paycheck.void_reason = reason.strip()
    paycheck.voided_at = datetime.now(timezone.utc)
    db.commit()
