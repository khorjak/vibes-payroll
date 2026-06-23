from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Date, Boolean, Numeric, ForeignKey, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .company import Company
    from .benefit import EmployeeBenefitEnrollment
    from .workers_comp import WorkersCompCode
    from .payroll import Timesheet, Paycheck
    from .garnishment import GarnishmentOrder

EMPLOYMENT_TYPES = ["salaried", "hourly", "part_time"]
EMPLOYEE_STATUSES = ["active", "terminated", "on_leave"]
FILING_STATUSES = ["single", "married_filing_jointly", "married_filing_separately", "head_of_household", "qualifying_surviving_spouse"]


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    ssn_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2), default="OK")
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    termination_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    employment_type: Mapped[str] = mapped_column(String(20))
    flsa_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    pay_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    pay_frequency: Mapped[Optional[str]] = mapped_column(String(20))
    department: Mapped[Optional[str]] = mapped_column(String(100))
    job_title: Mapped[Optional[str]] = mapped_column(String(100))
    workers_comp_code_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers_comp_codes.id"))
    routing_number_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    account_number_encrypted: Mapped[Optional[str]] = mapped_column(Text)

    company: Mapped["Company"] = relationship("Company", back_populates="employees")
    w4_elections: Mapped[List["W4Election"]] = relationship(
        "W4Election", back_populates="employee", order_by="W4Election.effective_date.desc()"
    )
    ok_withholding_elections: Mapped[List["OKWithholdingElection"]] = relationship(
        "OKWithholdingElection", back_populates="employee", order_by="OKWithholdingElection.effective_date.desc()"
    )
    benefit_enrollments: Mapped[List["EmployeeBenefitEnrollment"]] = relationship(
        "EmployeeBenefitEnrollment", back_populates="employee"
    )
    workers_comp_code: Mapped[Optional["WorkersCompCode"]] = relationship("WorkersCompCode")
    garnishment_orders: Mapped[List["GarnishmentOrder"]] = relationship(
        "GarnishmentOrder", back_populates="employee", order_by="GarnishmentOrder.effective_date"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def active_w4(self) -> Optional["W4Election"]:
        return self.w4_elections[0] if self.w4_elections else None

    @property
    def active_ok_withholding(self) -> Optional["OKWithholdingElection"]:
        return self.ok_withholding_elections[0] if self.ok_withholding_elections else None


class W4Election(Base):
    __tablename__ = "w4_elections"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date)
    filing_status: Mapped[str] = mapped_column(String(40), default="single")
    multiple_jobs: Mapped[bool] = mapped_column(Boolean, default=False)
    dependents_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    other_income: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    deductions_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    extra_withholding: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="w4_elections")


class OKWithholdingElection(Base):
    __tablename__ = "ok_withholding_elections"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date)
    filing_status: Mapped[str] = mapped_column(String(40), default="single")
    allowances: Mapped[int] = mapped_column(Integer, default=0)
    extra_withholding: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)

    employee: Mapped["Employee"] = relationship("Employee", back_populates="ok_withholding_elections")
