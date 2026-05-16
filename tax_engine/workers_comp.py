"""Workers compensation premium calculation."""
from decimal import Decimal, ROUND_HALF_UP


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calc_workers_comp(gross_wages: Decimal, rate_per_100: Decimal) -> Decimal:
    """Workers comp premium: rate per $100 of gross wages (NCCI code rate)."""
    return _round(gross_wages / Decimal("100") * rate_per_100)
