"""
Unemployment tax calculations.

FUTA: 6.0% gross rate on first $7,000 wages per employee per year.
      Net rate is 0.6% after the standard 5.4% state credit (assumes timely OK SUTA payments).

SUTA (Oklahoma): company-specific rate on wages up to the year's OESC taxable wage base.
"""
from decimal import Decimal, ROUND_HALF_UP

FUTA_GROSS_RATE = Decimal("0.060")
FUTA_NET_RATE = Decimal("0.006")   # after 5.4% state credit
FUTA_WAGE_BASE = Decimal("7000")  # statutory, not indexed
# The Oklahoma SUTA wage base changes every year; callers pass the pay year's
# figure (tax_years table, maintained under Tax Settings).


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calc_futa(wages: Decimal, ytd_futa_wages_prior: Decimal, *, net: bool = True) -> Decimal:
    """
    FUTA on wages up to $7,000. Uses net rate (0.6%) by default.
    Pass net=False to get the gross rate (6.0%) before the state credit.
    """
    rate = FUTA_NET_RATE if net else FUTA_GROSS_RATE
    subject = max(Decimal("0"), FUTA_WAGE_BASE - ytd_futa_wages_prior)
    taxable = min(wages, subject)
    return _round(taxable * rate)


def calc_suta(wages: Decimal, ytd_suta_wages_prior: Decimal, rate: Decimal, *, wage_base: Decimal) -> Decimal:
    """Oklahoma SUTA on wages up to the pay year's wage base at the company's assigned rate."""
    subject = max(Decimal("0"), wage_base - ytd_suta_wages_prior)
    taxable = min(wages, subject)
    return _round(taxable * rate)
