"""
Oklahoma state income tax withholding.

Uses the OTC formula method (OW-9 allowances):
  1. Annualize gross wages for the pay period.
  2. Subtract $1,000 per allowance claimed.
  3. Apply the Oklahoma rate schedule.
  4. Divide annual tax by pay periods; add any extra per-period withholding.

Oklahoma rate schedule (2024 onward after HB 2962 rate reductions):
  0.25% on first $1,000 of taxable income
  0.75% on $1,001–$2,500
  1.75% on $2,501–$3,750
  2.75% on $3,751–$4,900
  3.75% on $4,901–$7,200
  4.75% on income over $7,200

Source: Oklahoma Tax Commission Employer's Withholding Tax Guide.
"""
from decimal import Decimal, ROUND_HALF_UP
from .models import OKWithholdingInput, PAY_PERIOD_FACTORS

ALLOWANCE_VALUE = Decimal("1000")  # annual exemption per allowance

# (floor, base_tax, rate) — floor is annual taxable income lower bound
_OK_BRACKETS: list[tuple[Decimal, Decimal, Decimal]] = [
    (Decimal("0"),    Decimal("0"),      Decimal("0.0025")),
    (Decimal("1000"), Decimal("2.50"),   Decimal("0.0075")),
    (Decimal("2500"), Decimal("13.75"),  Decimal("0.0175")),
    (Decimal("3750"), Decimal("35.625"), Decimal("0.0275")),
    (Decimal("4900"), Decimal("67.25"),  Decimal("0.0375")),
    (Decimal("7200"), Decimal("153.50"), Decimal("0.0475")),
]


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
) -> Decimal:
    """Returns the Oklahoma income tax to withhold for this pay period."""
    periods = PAY_PERIOD_FACTORS[pay_frequency]
    annualized = taxable_wages_per_period * periods
    exemption = ALLOWANCE_VALUE * ok.allowances
    ok_taxable = max(Decimal("0"), annualized - exemption)

    annual_tax = _apply_brackets(ok_taxable, _OK_BRACKETS)
    per_period = _round(annual_tax / periods)
    return max(Decimal("0"), per_period + ok.extra_withholding)
