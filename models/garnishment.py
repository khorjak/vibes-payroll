from datetime import date
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Date, Numeric, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .employee import Employee

GARNISHMENT_TYPES = [
    "child_support",
    "federal_tax_levy",
    "state_tax_levy",
    "creditor",
    "student_loan",
    "bankruptcy",
    "other",
]


class GarnishmentOrder(Base, TimestampMixin):
    __tablename__ = "garnishment_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    garnishment_type: Mapped[str] = mapped_column(String(30))
    case_number: Mapped[Optional[str]] = mapped_column(String(100))
    payee_name: Mapped[str] = mapped_column(String(200))
    # Fixed dollar amount per pay period (used if amount_type = 'fixed')
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    # Percentage of disposable earnings (used if amount_type = 'percent')
    percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    amount_type: Mapped[str] = mapped_column(String(10), default="fixed")  # fixed | percent
    max_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    ytd_withheld: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    effective_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="garnishment_orders")
