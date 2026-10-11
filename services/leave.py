"""PTO and sick leave balances: a ledger of signed LeaveEntry rows per employee and type.

Paycheck entries are written when the paycheck is drafted (like ClientLiability rows) and
count toward the balance only once the paycheck is approved or paid.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.leave import LEAVE_TYPES, LeaveEntry, LeavePolicy
from models.payroll import Paycheck
from tax_engine.models import PAY_PERIOD_FACTORS

STANDARD_ANNUAL_HOURS = Decimal("2080")  # a salaried employee's hours worked, for per-hour accrual


def _counted(db: Session, employee_ids, leave_type: str | None = None):
    q = (
        db.query(LeaveEntry)
        .outerjoin(Paycheck, LeaveEntry.paycheck_id == Paycheck.id)
        .filter(LeaveEntry.employee_id.in_(employee_ids),
                or_(LeaveEntry.paycheck_id.is_(None), Paycheck.status.in_(("approved", "paid"))))
    )
    return q.filter(LeaveEntry.leave_type == leave_type) if leave_type else q


def balance(db: Session, employee_id: int, leave_type: str, before: date | None = None) -> Decimal:
    q = _counted(db, [employee_id], leave_type)
    if before:
        q = q.filter(LeaveEntry.entry_date < before)
    return Decimal(str(q.with_entities(func.coalesce(func.sum(LeaveEntry.hours), 0)).scalar()))


def balances(db: Session, employee_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """{employee_id: {leave_type: balance}} for every tracked type (one with a policy)."""
    tracked = db.query(LeavePolicy.employee_id, LeavePolicy.leave_type).filter(
        LeavePolicy.employee_id.in_(employee_ids)).all()
    out = {emp_id: {} for emp_id in employee_ids}
    for emp_id, leave_type in tracked:
        out[emp_id][leave_type] = Decimal("0.00")
    sums = (_counted(db, employee_ids)
            .with_entities(LeaveEntry.employee_id, LeaveEntry.leave_type, func.sum(LeaveEntry.hours))
            .group_by(LeaveEntry.employee_id, LeaveEntry.leave_type).all())
    for emp_id, leave_type, total in sums:
        if leave_type in out[emp_id]:
            out[emp_id][leave_type] = Decimal(str(total))
    return out


def _close_year(db: Session, policy: LeavePolicy, year: int) -> None:
    """Forfeit hours over the carryover limit on Jan 1 of `year`, once.

    A 0-hour entry still marks the year as done. ponytail: a December paycheck approved
    after this ran is not re-forfeited; adjust by hand if that happens.
    """
    jan1 = date(year, 1, 1)
    if policy.carryover_limit is None or not policy.carryover_since or policy.carryover_since >= jan1:
        return
    done = db.query(LeaveEntry.id).filter(
        LeaveEntry.employee_id == policy.employee_id, LeaveEntry.leave_type == policy.leave_type,
        LeaveEntry.kind == "forfeited", LeaveEntry.entry_date == jan1).first()
    if done:
        return
    over = balance(db, policy.employee_id, policy.leave_type, before=jan1) - policy.carryover_limit
    db.add(LeaveEntry(
        employee_id=policy.employee_id, leave_type=policy.leave_type, entry_date=jan1,
        kind="forfeited", hours=-max(over, Decimal("0")),
        note=f"Over the {policy.carryover_limit:,} hour carryover limit",
    ))
    db.flush()


def _hours(value) -> Decimal:
    return Decimal(str(value or 0))


def record_paycheck_leave(db: Session, employee, pay_period, timesheet, paycheck, frequency: str) -> None:
    """Write the paycheck's used and accrued hours for each tracked leave type.

    Off-cycle payments (a one-day period) record hours used but accrue nothing.
    """
    policies = db.query(LeavePolicy).filter(LeavePolicy.employee_id == employee.id).all()
    off_cycle = pay_period.start_date == pay_period.end_date == pay_period.pay_date
    used_by_type = {"pto": _hours(timesheet and timesheet.pto_hours),
                    "sick": _hours(timesheet and timesheet.sick_hours)}
    if employee.employment_type == "salaried":
        worked = STANDARD_ANNUAL_HOURS / Decimal(str(PAY_PERIOD_FACTORS[frequency]))
    else:
        worked = sum((_hours(timesheet and getattr(timesheet, f))
                      for f in ("regular_hours", "overtime_hours", "double_time_hours")), Decimal("0"))

    for policy in policies:
        _close_year(db, policy, pay_period.pay_date.year)
        entry = dict(employee_id=employee.id, leave_type=policy.leave_type,
                     entry_date=pay_period.pay_date, paycheck_id=paycheck.id)
        used = used_by_type.get(policy.leave_type, Decimal("0"))
        if used:
            db.add(LeaveEntry(**entry, kind="used", hours=-used))
        if off_cycle:
            continue
        rate = Decimal(str(policy.rate))
        earned = worked * rate if policy.method == "per_hour" else rate
        if policy.max_balance is not None:
            # Accrual pauses at the cap. ponytail: other unapproved drafts are not counted.
            room = Decimal(str(policy.max_balance)) - (balance(db, employee.id, policy.leave_type) - used)
            earned = min(earned, max(room, Decimal("0")))
        earned = earned.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if earned > 0:
            db.add(LeaveEntry(**entry, kind="accrued", hours=earned))
    db.flush()


def paycheck_leave_summary(db: Session, paycheck) -> list[dict]:
    """Per tracked type: hours accrued and used on this paycheck and the balance after it."""
    pay_date = paycheck.pay_period.pay_date
    types = {p.leave_type for p in db.query(LeavePolicy).filter(LeavePolicy.employee_id == paycheck.employee_id)}
    types |= {e.leave_type for e in paycheck.leave_entries}
    rows = []
    for leave_type in [t for t in LEAVE_TYPES if t in types]:
        own = [e for e in paycheck.leave_entries if e.leave_type == leave_type]
        after = (_counted(db, [paycheck.employee_id], leave_type)
                 .filter(LeaveEntry.entry_date <= pay_date,
                         or_(LeaveEntry.paycheck_id.is_(None), LeaveEntry.paycheck_id != paycheck.id))
                 .with_entities(func.coalesce(func.sum(LeaveEntry.hours), 0)).scalar())
        after = Decimal(str(after))
        if paycheck.status != "voided":
            after += sum((e.hours for e in own), Decimal("0"))
        rows.append({
            "label": LEAVE_TYPES[leave_type],
            "accrued": sum((e.hours for e in own if e.kind == "accrued"), Decimal("0")),
            "used": -sum((e.hours for e in own if e.kind == "used"), Decimal("0")),
            "balance": after,
        })
    return rows
