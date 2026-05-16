"""
FICA calculations for 2025.

Social Security: 6.2% employee + 6.2% employer on wages up to $176,100.
Medicare: 1.45% employee + 1.45% employer on all wages.
Additional Medicare: 0.9% employee-only on wages above $200,000 YTD.
"""
from decimal import Decimal, ROUND_HALF_UP

SS_RATE = Decimal("0.062")
MEDICARE_RATE = Decimal("0.0145")
ADDITIONAL_MEDICARE_RATE = Decimal("0.009")

SS_WAGE_BASE = Decimal("176100")           # 2025
ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000")


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calc_ss_employee(wages: Decimal, ytd_ss_wages_prior: Decimal) -> Decimal:
    """Employee Social Security: 6.2% on wages up to annual wage base."""
    subject = max(Decimal("0"), SS_WAGE_BASE - ytd_ss_wages_prior)
    taxable = min(wages, subject)
    return _round(taxable * SS_RATE)


def calc_ss_employer(wages: Decimal, ytd_ss_wages_prior: Decimal) -> Decimal:
    """Employer Social Security matches employee exactly."""
    return calc_ss_employee(wages, ytd_ss_wages_prior)


def calc_medicare_employee(wages: Decimal, ytd_gross_prior: Decimal) -> Decimal:
    """
    Employee Medicare: 1.45% flat + 0.9% additional on wages over $200,000 YTD.
    The additional 0.9% applies only to the employee, not the employer.
    """
    base = _round(wages * MEDICARE_RATE)

    ytd_after = ytd_gross_prior + wages
    if ytd_after > ADDITIONAL_MEDICARE_THRESHOLD:
        above_threshold = ytd_after - max(ytd_gross_prior, ADDITIONAL_MEDICARE_THRESHOLD)
        additional = _round(above_threshold * ADDITIONAL_MEDICARE_RATE)
    else:
        additional = Decimal("0")

    return base + additional


def calc_medicare_employer(wages: Decimal) -> Decimal:
    """Employer Medicare: 1.45% flat (no additional Medicare obligation for employer)."""
    return _round(wages * MEDICARE_RATE)
