from datetime import date
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, ForeignKey, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .company import Company
    from .employee import Employee

BENEFIT_TYPES = [
    "health", "dental", "vision", "fsa", "hsa",
    "traditional_401k", "roth_401k", "life_insurance", "other",
]

CONTRIBUTION_TYPES = ["fixed", "percent"]


class BenefitPlan(Base, TimestampMixin):
    __tablename__ = "benefit_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200))
    benefit_type: Mapped[str] = mapped_column(String(30))
    employee_contribution_type: Mapped[str] = mapped_column(String(10), default="fixed")
    employee_contribution_amount: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    employer_match_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    employer_match_cap_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    pre_tax: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped["Company"] = relationship("Company", back_populates="benefit_plans")
    enrollments: Mapped[List["EmployeeBenefitEnrollment"]] = relationship(
        "EmployeeBenefitEnrollment", back_populates="plan"
    )


class EmployeeBenefitEnrollment(Base):
    __tablename__ = "employee_benefit_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    benefit_plan_id: Mapped[int] = mapped_column(ForeignKey("benefit_plans.id"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    employee_override_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))

    employee: Mapped["Employee"] = relationship("Employee", back_populates="benefit_enrollments")
    plan: Mapped["BenefitPlan"] = relationship("BenefitPlan", back_populates="enrollments")
