"""
Oklahoma state income tax withholding: OTC Packet OW-2, percentage formula method.

  1. Annualize the period's taxable wages.
  2. Subtract the withholding allowance amount for each OK-W-4 allowance.
  3. Look up the result in the year's annual table (Table 7) for the filing status:
     single, or married. "Married, but withhold at higher Single rate" uses single.
  4. Divide the annual amount by pay periods and round to the nearest whole dollar,
     as OW-2 requires; add any extra per-period withholding.

The caller passes the pay year's tables (OKTable): admins enter them under Tax
Settings from that year's OW-2. Their first band is $0 tax: it covers the Oklahoma
standard deduction (and, from 2026, the 0% bracket).
"""
from decimal import Decimal, ROUND_HALF_UP
from .models import OKTable, OKWithholdingInput, PAY_PERIOD_FACTORS


def _apply_brackets(amount: Decimal, brackets: list[tuple]) -> Decimal:
    if amount <= Decimal("0"):
        return Decimal("0")
    for floor, base_tax, rate in reversed(brackets):
        if amount >= floor:
            return base_tax + (amount - floor) * rate
    return Decimal("0")


def calc_ok_withholding(
    taxable_wages_per_period: Decimal,
    pay_frequency: str,
    ok: OKWithholdingInput,
    *,
    table: OKTable,
) -> Decimal:
    """Returns the Oklahoma income tax to withhold for this pay period."""
    if ok.exempt:
        return Decimal("0")
    periods = PAY_PERIOD_FACTORS[pay_frequency]
    annualized = taxable_wages_per_period * periods
    ok_taxable = max(Decimal("0"), annualized - table.allowance * ok.allowances)

    status = "married" if ok.filing_status == "married" else "single"
    annual_tax = _apply_brackets(ok_taxable, table.schedules[status])
    per_period = (annual_tax / periods).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(Decimal("0"), per_period + ok.extra_withholding).quantize(Decimal("0.01"))
