"""
Tests for Oklahoma state income tax withholding (OTC formula method).

Formula: annualize wages → subtract $1,000/allowance → apply OK rate schedule → divide by periods.

Oklahoma rate schedule (2024+):
  0.25% on $0–$1,000
  0.75% on $1,000–$2,500
  1.75% on $2,500–$3,750
  2.75% on $3,750–$4,900
  3.75% on $4,900–$7,200
  4.75% over $7,200
"""
import pytest
from decimal import Decimal
from tax_engine.oklahoma import calc_ok_withholding
from tax_engine.models import OKWithholdingInput


def ok(filing_status="single", allowances=0, extra=0):
    return OKWithholdingInput(
        filing_status=filing_status,
        allowances=allowances,
        extra_withholding=Decimal(str(extra)),
    )


class TestOKWithholding:
    def test_zero_wages_no_tax(self):
        assert calc_ok_withholding(Decimal("0"), "biweekly", ok()) == Decimal("0.00")

    def test_no_allowances_single_biweekly(self):
        # $2,000 biweekly → $52,000 annual; 0 allowances → taxable = $52,000
        # Tax = $153.50 + ($52,000 - $7,200) × 4.75% = $153.50 + $44,800 × 0.0475
        # = $153.50 + $2,128 = $2,281.50
        # Per period: $2,281.50 / 26 = $87.75
        result = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", allowances=0))
        assert result == Decimal("87.75")

    def test_with_allowance_reduces_tax(self):
        no_allow = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 0))
        with_allow = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 1))
        assert with_allow < no_allow

    def test_one_allowance_calculation(self):
        # $2,000 biweekly → $52,000 annual; 1 allowance → taxable = $51,000
        # Tax = $153.50 + ($51,000 - $7,200) × 4.75% = $153.50 + $43,800 × 0.0475
        # = $153.50 + $2,080.50 = $2,234
        # Per period: $2,234 / 26 = $85.92 (rounded)
        result = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 1))
        assert result == Decimal("85.92")

    def test_many_allowances_reduces_to_zero(self):
        # $500 biweekly → $13,000 annual; 20 allowances → $13,000 - $20,000 < 0 → $0
        result = calc_ok_withholding(Decimal("500"), "biweekly", ok("single", 20))
        assert result == Decimal("0.00")

    def test_extra_withholding_added(self):
        base = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 1))
        extra = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 1, extra=25))
        assert extra == base + Decimal("25")

    def test_weekly_pay_frequency(self):
        # $1,000 weekly → $52,000 annual; should yield same annual total as biweekly $2,000
        biweekly = calc_ok_withholding(Decimal("2000"), "biweekly", ok("single", 0))
        weekly = calc_ok_withholding(Decimal("1000"), "weekly", ok("single", 0))
        annual_biweekly = biweekly * 26
        annual_weekly = weekly * 52
        # Should be within a few cents due to rounding
        assert abs(annual_biweekly - annual_weekly) < Decimal("2.00")

    def test_low_income_in_lowest_bracket(self):
        # $50/week → $2,600 annual; taxable = $2,600; in 0.75% bracket ($1,000–$2,500)... wait
        # $2,600 is in $2,500–$3,750 bracket (1.75%)
        # Tax = $13.75 + ($2,600 - $2,500) × 0.0175 = $13.75 + $1.75 = $15.50
        # Per period: $15.50 / 52 = $0.30 (rounded)
        result = calc_ok_withholding(Decimal("50"), "weekly", ok("single", 0))
        assert result == Decimal("0.30")

    def test_married_filing_status_accepted(self):
        # Filing status is stored but the rate schedule is the same; allowances do the differentiation
        result = calc_ok_withholding(Decimal("2000"), "biweekly", ok("married", 2))
        assert result >= Decimal("0.00")

    def test_in_3_75_percent_bracket(self):
        # $250/week → $13,000 annual; taxable = $13,000; in 4.75% bracket
        # Tax = $153.50 + ($13,000 - $7,200) × 4.75% = $153.50 + $5,800 × 0.0475
        # = $153.50 + $275.50 = $429
        # Per period: $429 / 52 = $8.25
        result = calc_ok_withholding(Decimal("250"), "weekly", ok("single", 0))
        assert result == Decimal("8.25")
