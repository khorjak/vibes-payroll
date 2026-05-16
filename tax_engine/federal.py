"""
Federal income tax withholding — IRS Publication 15-T (2025).

Uses the Percentage Method for Automated Payroll Systems (Worksheet 1).

Step-by-step per the IRS worksheet:
  1. Annualize gross wages for the period.
  2. Add Step 4a (other_income) and subtract Step 4b (deductions_amount) → adjusted annual wage.
  3. Look up adjusted annual wage in the appropriate percentage method table
     (selected by filing_status × whether Step 2 multiple-jobs box is checked).
  4. Subtract Step 3 (dependents_amount — a dollar credit, not a wage reduction).
  5. Divide annual withholding by number of pay periods.
  6. Add Step 4c (extra_withholding per period).

Tables reflect 2025 tax brackets and standard deductions:
  Single / MFS standard deduction: $15,000  → standard table offset $15,000
  MFJ / QSS standard deduction:   $30,000  → standard table offset $30,000
  HoH standard deduction:          $22,500  → standard table offset $22,500

For "higher withholding" (Step 2 checked), the offset is halved:
  Single / MFS: $7,500   MFJ / QSS: $15,000   HoH: $11,250

Source: IRS Publication 15-T, 2025 edition, Table for Percentage Method Tables.
"""
from decimal import Decimal, ROUND_HALF_UP
from .models import W4Input, PAY_PERIOD_FACTORS

SUPPLEMENTAL_RATE = Decimal("0.22")


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Each entry: (floor, base_tax, rate)
#   floor:     lower bound of this bracket in adjusted annual wages
#   base_tax:  cumulative tax already owed at the floor
#   rate:      marginal rate for this bracket

# ── Standard withholding (Step 2 NOT checked) ────────────────────────────────

_SINGLE_STANDARD = [
    (Decimal("0"),       Decimal("0"),          Decimal("0.00")),
    (Decimal("15000"),   Decimal("0"),           Decimal("0.10")),
    (Decimal("26925"),   Decimal("1192.50"),     Decimal("0.12")),
    (Decimal("63475"),   Decimal("5578.50"),     Decimal("0.22")),
    (Decimal("118350"),  Decimal("17651.00"),    Decimal("0.24")),
    (Decimal("212300"),  Decimal("40199.00"),    Decimal("0.32")),
    (Decimal("265525"),  Decimal("57231.00"),    Decimal("0.35")),
    (Decimal("641350"),  Decimal("188769.75"),   Decimal("0.37")),
]

_MFJ_STANDARD = [
    (Decimal("0"),       Decimal("0"),           Decimal("0.00")),
    (Decimal("30000"),   Decimal("0"),            Decimal("0.10")),
    (Decimal("53850"),   Decimal("2385.00"),      Decimal("0.12")),
    (Decimal("126950"),  Decimal("11157.00"),     Decimal("0.22")),
    (Decimal("236700"),  Decimal("35302.00"),     Decimal("0.24")),
    (Decimal("424600"),  Decimal("80398.00"),     Decimal("0.32")),
    (Decimal("531050"),  Decimal("114462.00"),    Decimal("0.35")),
    (Decimal("781600"),  Decimal("202154.50"),    Decimal("0.37")),
]

_HOH_STANDARD = [
    (Decimal("0"),       Decimal("0"),           Decimal("0.00")),
    (Decimal("22500"),   Decimal("0"),            Decimal("0.10")),
    (Decimal("39500"),   Decimal("1700.00"),      Decimal("0.12")),
    (Decimal("87350"),   Decimal("7442.00"),      Decimal("0.22")),
    (Decimal("125850"),  Decimal("15912.00"),     Decimal("0.24")),
    (Decimal("219800"),  Decimal("38460.00"),     Decimal("0.32")),
    (Decimal("273000"),  Decimal("55484.00"),     Decimal("0.35")),
    (Decimal("648850"),  Decimal("187031.50"),    Decimal("0.37")),
]

# ── Higher withholding (Step 2 IS checked) ───────────────────────────────────

_SINGLE_HIGH = [
    (Decimal("0"),       Decimal("0"),           Decimal("0.00")),
    (Decimal("7500"),    Decimal("0"),            Decimal("0.10")),
    (Decimal("19425"),   Decimal("1192.50"),      Decimal("0.12")),
    (Decimal("55975"),   Decimal("5578.50"),      Decimal("0.22")),
    (Decimal("110850"),  Decimal("17651.00"),     Decimal("0.24")),
    (Decimal("204800"),  Decimal("40199.00"),     Decimal("0.32")),
    (Decimal("258025"),  Decimal("57231.00"),     Decimal("0.35")),
    (Decimal("633850"),  Decimal("188769.75"),    Decimal("0.37")),
]

_MFJ_HIGH = [
    (Decimal("0"),       Decimal("0"),           Decimal("0.00")),
    (Decimal("15000"),   Decimal("0"),            Decimal("0.10")),
    (Decimal("38850"),   Decimal("2385.00"),      Decimal("0.12")),
    (Decimal("111950"),  Decimal("11157.00"),     Decimal("0.22")),
    (Decimal("221700"),  Decimal("35302.00"),     Decimal("0.24")),
    (Decimal("409600"),  Decimal("80398.00"),     Decimal("0.32")),
    (Decimal("516050"),  Decimal("114462.00"),    Decimal("0.35")),
    (Decimal("766600"),  Decimal("202154.50"),    Decimal("0.37")),
]

_HOH_HIGH = [
    (Decimal("0"),       Decimal("0"),           Decimal("0.00")),
    (Decimal("11250"),   Decimal("0"),            Decimal("0.10")),
    (Decimal("28250"),   Decimal("1700.00"),      Decimal("0.12")),
    (Decimal("76100"),   Decimal("7442.00"),      Decimal("0.22")),
    (Decimal("114600"),  Decimal("15912.00"),     Decimal("0.24")),
    (Decimal("208550"),  Decimal("38460.00"),     Decimal("0.32")),
    (Decimal("261750"),  Decimal("55484.00"),     Decimal("0.35")),
    (Decimal("637600"),  Decimal("187031.50"),    Decimal("0.37")),
]


def _get_brackets(filing_status: str, multiple_jobs: bool) -> list:
    # Normalize aliases
    if filing_status in ("married_filing_separately",):
        filing_status = "single"
    elif filing_status in ("qualifying_surviving_spouse",):
        filing_status = "married_filing_jointly"

    if multiple_jobs:
        return {
            "single": _SINGLE_HIGH,
            "married_filing_jointly": _MFJ_HIGH,
            "head_of_household": _HOH_HIGH,
        }[filing_status]
    else:
        return {
            "single": _SINGLE_STANDARD,
            "married_filing_jointly": _MFJ_STANDARD,
            "head_of_household": _HOH_STANDARD,
        }[filing_status]


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
) -> Decimal:
    """
    Returns federal income tax to withhold for the pay period.
    taxable_wages_per_period should already exclude pre-tax deductions.
    """
    periods = PAY_PERIOD_FACTORS[pay_frequency]

    # Step 1: Annualize and adjust
    annualized = taxable_wages_per_period * periods
    adjusted = annualized + w4.other_income - w4.deductions_amount

    # Step 2: Tentative annual withholding from table
    brackets = _get_brackets(w4.filing_status, w4.multiple_jobs)
    tentative = _apply_brackets(adjusted, brackets)

    # Step 3: Subtract dependents credit (Step 3 on W-4)
    annual_withholding = max(Decimal("0"), tentative - w4.dependents_amount)

    # Step 4: Divide by periods, add extra withholding
    per_period = _round(annual_withholding / periods) + w4.extra_withholding
    return max(Decimal("0"), _round(per_period))


def calc_supplemental_federal(wages: Decimal) -> Decimal:
    """Flat 22% rate for supplemental wages (bonuses, commissions) under $1M."""
    return _round(wages * SUPPLEMENTAL_RATE)
