"""
Garnishment calculation with CCPA (Consumer Credit Protection Act) limits.

Priority order (federal law):
  1. Child support / alimony
  2. Federal tax levies
  3. State tax levies
  4. Federal student loans
  5. Creditor garnishments / bankruptcy / other

CCPA disposable earnings = gross - mandatory deductions (taxes + pre-tax benefits).
Max garnishment per pay period:
  - Non-child-support: lesser of 25% of disposable earnings OR disposable minus 30× federal min wage
  - Child support (not in arrears): 50% if supporting another spouse/child, else 60%
  - Child support (in arrears 12+ weeks): add 5% to above
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import List

FEDERAL_MIN_WAGE = Decimal("7.25")
_TWO = Decimal("0.01")

PRIORITY_ORDER = {
    "child_support": 1,
    "federal_tax_levy": 2,
    "state_tax_levy": 3,
    "student_loan": 4,
    "creditor": 5,
    "bankruptcy": 5,
    "other": 6,
}


@dataclass
class GarnishmentInput:
    garnishment_type: str
    amount: Decimal  # requested amount per period (fixed)
    percent: Decimal = field(default_factory=lambda: Decimal("0"))  # requested percent of disposable
    amount_type: str = "fixed"  # fixed | percent
    max_total: Decimal = field(default_factory=lambda: Decimal("0"))
    ytd_withheld: Decimal = field(default_factory=lambda: Decimal("0"))
    order_id: int = 0


@dataclass
class GarnishmentResult:
    order_id: int
    garnishment_type: str
    amount: Decimal


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def calc_garnishments(
    disposable_earnings: Decimal,
    garnishments: List[GarnishmentInput],
    pay_frequency: str = "biweekly",
) -> List[GarnishmentResult]:
    if not garnishments or disposable_earnings <= Decimal("0"):
        return []

    sorted_garn = sorted(garnishments, key=lambda g: PRIORITY_ORDER.get(g.garnishment_type, 99))

    # CCPA limits by category
    child_support_limit = _round2(disposable_earnings * Decimal("0.50"))
    non_cs_25pct = _round2(disposable_earnings * Decimal("0.25"))

    # 30× federal minimum wage per week, scaled by pay frequency
    weekly_factors = {"weekly": 1, "biweekly": 2, "semi_monthly": Decimal("2.1667"), "monthly": Decimal("4.3333")}
    factor = Decimal(str(weekly_factors.get(pay_frequency, 2)))
    thirty_times_min = _round2(FEDERAL_MIN_WAGE * Decimal("30") * factor)
    non_cs_excess = max(Decimal("0"), disposable_earnings - thirty_times_min)
    non_cs_limit = min(non_cs_25pct, non_cs_excess)

    results: List[GarnishmentResult] = []
    cs_total = Decimal("0")
    non_cs_total = Decimal("0")

    for g in sorted_garn:
        is_child_support = g.garnishment_type == "child_support"

        if g.amount_type == "percent" and g.percent > 0:
            requested = _round2(disposable_earnings * g.percent / Decimal("100"))
        else:
            requested = g.amount

        # Cap by max_total remaining
        if g.max_total and g.max_total > 0:
            remaining = g.max_total - g.ytd_withheld
            if remaining <= 0:
                continue
            requested = min(requested, remaining)

        if requested <= 0:
            continue

        if is_child_support:
            available = child_support_limit - cs_total
            actual = min(requested, max(Decimal("0"), available))
            cs_total += actual
        else:
            available = non_cs_limit - non_cs_total
            actual = min(requested, max(Decimal("0"), available))
            non_cs_total += actual

        if actual > 0:
            results.append(GarnishmentResult(
                order_id=g.order_id,
                garnishment_type=g.garnishment_type,
                amount=_round2(actual),
            ))

    return results
