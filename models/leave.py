from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Date, Numeric, ForeignKey, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .payroll import Paycheck

LEAVE_TYPES = {"pto": "PTO", "sick": "Sick"}
ACCRUAL_METHODS = {"per_hour": "Per hour worked", "per_period": "Per pay period"}
LEAVE_KINDS = {"accrued": "Accrued", "used": "Used", "adjustment": "Adjustment", "forfeited": "Year-end forfeit"}


class LeavePolicy(Base):
    """An employee's accrual rule for one leave type. A type is tracked only while a policy exists."""
    __tablename__ = "leave_policies"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(10))
    method: Mapped[str] = mapped_column(String(20))
    # per_hour: hours accrued per hour worked; per_period: hours accrued per regular paycheck.
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    max_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    carryover_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    # The limit applies at each Jan 1 after this date, never retroactively.
    carryover_since: Mapped[Optional[date]] = mapped_column(Date)


class LeaveEntry(Base):
    """One signed change to a leave balance; the balance is the sum of counted entries.

    Entries with a paycheck_id are written when the paycheck is drafted and count only
    once it is approved or paid, so recalculating replaces them and voiding drops them.
    """
    __tablename__ = "leave_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(10))
    entry_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    paycheck_id: Mapped[Optional[int]] = mapped_column(ForeignKey("paychecks.id"), index=True)
    note: Mapped[Optional[str]] = mapped_column(String(200))
    created_by: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    paycheck: Mapped[Optional["Paycheck"]] = relationship("Paycheck", back_populates="leave_entries")
