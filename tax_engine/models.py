from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

PAY_PERIOD_FACTORS: dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "semi_monthly": 24,
    "monthly": 12,
}


@dataclass
class W4Input:
    filing_status: str  # single | married_filing_jointly | married_filing_separately | head_of_household | qualifying_surviving_spouse
    multiple_jobs: bool = False
    dependents_amount: Decimal = field(default_factory=lambda: Decimal("0"))  # Step 3 annual credit
    other_income: Decimal = field(default_factory=lambda: Decimal("0"))       # Step 4a annual
    deductions_amount: Decimal = field(default_factory=lambda: Decimal("0"))  # Step 4b annual
    extra_withholding: Decimal = field(default_factory=lambda: Decimal("0"))  # Step 4c per-period


@dataclass
class OKWithholdingInput:
    filing_status: str  # single | married
    allowances: int = 0
    extra_withholding: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class PaycheckInput:
    gross_wages: Decimal
    pay_frequency: str  # weekly | biweekly | semi_monthly | monthly

    # YTD accumulators *before* this paycheck
    ytd_gross_prior: Decimal = field(default_factory=lambda: Decimal("0"))
    ytd_ss_wages_prior: Decimal = field(default_factory=lambda: Decimal("0"))
    ytd_futa_wages_prior: Decimal = field(default_factory=lambda: Decimal("0"))
    ytd_suta_wages_prior: Decimal = field(default_factory=lambda: Decimal("0"))

    # Section 125 / cafeteria-plan deductions (reduce federal, state, and FICA taxable wages)
    pre_tax_deductions: Decimal = field(default_factory=lambda: Decimal("0"))

    w4: Optional[W4Input] = None
    ok_withholding: Optional[OKWithholdingInput] = None

    suta_rate: Decimal = field(default_factory=lambda: Decimal("0.027"))
    workers_comp_rate: Decimal = field(default_factory=lambda: Decimal("0"))  # rate per $100 wages

    is_supplemental: bool = False  # True for bonuses — uses flat 22% federal rate


@dataclass
class TaxResult:
    federal_income_tax: Decimal = field(default_factory=lambda: Decimal("0"))
    ok_income_tax: Decimal = field(default_factory=lambda: Decimal("0"))
    ss_employee: Decimal = field(default_factory=lambda: Decimal("0"))
    medicare_employee: Decimal = field(default_factory=lambda: Decimal("0"))
    ss_employer: Decimal = field(default_factory=lambda: Decimal("0"))
    medicare_employer: Decimal = field(default_factory=lambda: Decimal("0"))
    futa: Decimal = field(default_factory=lambda: Decimal("0"))
    suta: Decimal = field(default_factory=lambda: Decimal("0"))
    workers_comp: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class PaycheckResult:
    gross_wages: Decimal
    pre_tax_deductions: Decimal
    taxable_wages: Decimal  # gross - pre_tax_deductions (used for income tax and FICA)
    taxes: TaxResult

    @property
    def total_employee_taxes(self) -> Decimal:
        t = self.taxes
        return t.federal_income_tax + t.ok_income_tax + t.ss_employee + t.medicare_employee

    @property
    def total_employer_taxes(self) -> Decimal:
        t = self.taxes
        return t.ss_employer + t.medicare_employer + t.futa + t.suta + t.workers_comp

    @property
    def net_pay(self) -> Decimal:
        return self.gross_wages - self.pre_tax_deductions - self.total_employee_taxes
