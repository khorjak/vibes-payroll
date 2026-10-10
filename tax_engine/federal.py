"""
Federal income tax withholding: IRS Publication 15-T, Worksheet 1A (Percentage
Method for Automated Payroll Systems, Form W-4 from 2020 or later).

  1. Annualize the period's taxable wages.
  2. Add Step 4a (other_income), subtract Step 4b (deductions_amount), and
     subtract the line 1g amount when the Step 2 box is NOT checked.
  3. Look up the adjusted annual wage in the year's Annual Percentage Method table:
     STANDARD, or Step 2 Checkbox when the multiple-jobs box is checked.
  4. Subtract Step 3 (dependents_amount, an annual credit).
  5. Divide by pay periods; add Step 4c (extra_withholding per period).

The caller passes the pay year's tables (FederalTable): admins enter them under
Tax Settings, row for row from that year's Pub. 15-T.
"""
from decimal import Decimal, ROUND_HALF_UP
from .models import FederalTable, W4Input, PAY_PERIOD_FACTORS

SUPPLEMENTAL_RATE = Decimal("0.22")


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _status(filing_status: str) -> str:
    # Pub. 15-T groups MFS with single and QSS with married filing jointly.
    return {"married_filing_separately": "single",
            "qualifying_surviving_spouse": "married_filing_jointly"}.get(filing_status, filing_status)


def _apply_brackets(amount: Decimal, brackets: list) -> Decimal:
    if amount <= Decimal("0"):
        return Decimal("0")
    for floor, base_tax, rate in reversed(brackets):
        if amount >= floor:
            return base_tax + (amount - floor) * rate
    return Decimal("0")


def calc_federal_withholding(
    taxable_wages_per_period: Decimal,
    pay_frequency: str,
    w4: W4Input,
    *,
    table: FederalTable,
) -> Decimal:
    """
    Returns federal income tax to withhold for the pay period.
    taxable_wages_per_period should already exclude pre-tax deductions.
    """
    if w4.exempt:
        return Decimal("0")
    periods = PAY_PERIOD_FACTORS[pay_frequency]
    status = _status(w4.filing_status)

    # Step 1: Annualize and adjust (line 1g only when the Step 2 box is unchecked)
    annualized = taxable_wages_per_period * periods
    adjusted = annualized + w4.other_income - w4.deductions_amount
    if not w4.multiple_jobs:
        adjusted -= table.line_1g_mfj if status == "married_filing_jointly" else table.line_1g_other

    # Step 2: Tentative annual withholding from the year's table
    brackets = table.schedules["step2" if w4.multiple_jobs else "standard"][status]
    tentative = _apply_brackets(adjusted, brackets)

    # Step 3: Subtract dependents credit (Step 3 on W-4)
    annual_withholding = max(Decimal("0"), tentative - w4.dependents_amount)

    # Step 4: Divide by periods, add extra withholding
    per_period = _round(annual_withholding / periods) + w4.extra_withholding
    return max(Decimal("0"), _round(per_period))


def calc_supplemental_federal(wages: Decimal) -> Decimal:
    """Flat 22% rate for supplemental wages (bonuses, commissions) under $1M."""
    return _round(wages * SUPPLEMENTAL_RATE)
