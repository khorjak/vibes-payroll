from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Date, Boolean, Numeric, ForeignKey, Text, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

if TYPE_CHECKING:
    from .company import Company
    from .employee import Employee

PAY_PERIOD_STATUSES = ["open", "draft", "approved", "paid", "closed"]
PAYCHECK_STATUSES = ["draft", "approved", "paid", "voided"]
EARNING_TYPES = [
    "regular", "overtime", "double_time", "pto", "sick",
    "holiday", "bonus", "commission", "reimbursement",
]
DEDUCTION_TYPES = [
    "health", "dental", "vision", "fsa", "hsa",
    "traditional_401k", "roth_401k", "garnishment", "child_support", "other",
]
LIABILITY_TYPES = [
    "garnishment_remittance", "child_support_remittance",
    "benefit_premium", "retirement_deposit", "other",
]


class PayPeriod(Base):
    __tablename__ = "pay_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    pay_date: Mapped[date] = mapped_column(Date)
    frequency: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="pay_periods")
    timesheets: Mapped[List["Timesheet"]] = relationship("Timesheet", back_populates="pay_period")
    paychecks: Mapped[List["Paycheck"]] = relationship("Paycheck", back_populates="pay_period")


class Timesheet(Base):
    __tablename__ = "timesheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    pay_period_id: Mapped[int] = mapped_column(ForeignKey("pay_periods.id"), nullable=False)
    regular_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    double_time_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    pto_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    sick_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    holiday_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    employee: Mapped["Employee"] = relationship("Employee")
    pay_period: Mapped["PayPeriod"] = relationship("PayPeriod", back_populates="timesheets")


class Paycheck(Base):
    __tablename__ = "paychecks"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    pay_period_id: Mapped[int] = mapped_column(ForeignKey("pay_periods.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    gross_wages: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_taxes_withheld: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    employer_fica: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    employer_futa: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    employer_suta: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    employer_workers_comp: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    ytd_gross: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    ytd_federal_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    ytd_state_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    ytd_fica_employee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    ytd_fica_employer: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    ytd_futa: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    ytd_suta: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    check_number: Mapped[Optional[str]] = mapped_column(String(20))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    void_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    employee: Mapped["Employee"] = relationship("Employee")
    pay_period: Mapped["PayPeriod"] = relationship("PayPeriod", back_populates="paychecks")
    lines: Mapped[List["PaycheckLine"]] = relationship("PaycheckLine", back_populates="paycheck")
    liabilities: Mapped[List["ClientLiability"]] = relationship("ClientLiability", back_populates="paycheck")


class PaycheckLine(Base):
    __tablename__ = "paycheck_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    paycheck_id: Mapped[int] = mapped_column(ForeignKey("paychecks.id"), nullable=False)
    line_type: Mapped[str] = mapped_column(String(20))  # earning, deduction, tax, employer_tax
    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_pre_tax: Mapped[bool] = mapped_column(Boolean, default=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    hours: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))

    paycheck: Mapped["Paycheck"] = relationship("Paycheck", back_populates="lines")


class ClientLiability(Base):
    __tablename__ = "client_liabilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    pay_period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pay_periods.id"))
    paycheck_id: Mapped[Optional[int]] = mapped_column(ForeignKey("paychecks.id"))
    liability_type: Mapped[str] = mapped_column(String(40))
    payee_name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    remitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    remittance_reference: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    paycheck: Mapped[Optional["Paycheck"]] = relationship("Paycheck", back_populates="liabilities")
