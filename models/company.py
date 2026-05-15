from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .employee import Employee
    from .benefit import BenefitPlan
    from .payroll import PayPeriod

PAY_FREQUENCIES = ["weekly", "biweekly", "semi_monthly", "monthly"]


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    ein: Mapped[Optional[str]] = mapped_column(String(11))
    address: Mapped[Optional[str]] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2), default="OK")
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    pay_frequency: Mapped[str] = mapped_column(String(20), default="biweekly")
    suta_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    workers_comp_policy: Mapped[Optional[str]] = mapped_column(String(100))

    employees: Mapped[List["Employee"]] = relationship("Employee", back_populates="company")
    benefit_plans: Mapped[List["BenefitPlan"]] = relationship("BenefitPlan", back_populates="company")
    pay_periods: Mapped[List["PayPeriod"]] = relationship("PayPeriod", back_populates="company")
