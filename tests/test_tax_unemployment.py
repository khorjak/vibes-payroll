"""Tests for FUTA and SUTA calculations."""
from decimal import Decimal
from tax_engine.unemployment import calc_futa, calc_suta, FUTA_WAGE_BASE, OK_SUTA_WAGE_BASE


class TestFUTA:
    def test_standard_net_rate(self):
        # $1,000 wages, no prior YTD → 0.6% net rate
        assert calc_futa(Decimal("1000"), Decimal("0")) == Decimal("6.00")

    def test_gross_rate_flag(self):
        # 6.0% gross rate before state credit
        assert calc_futa(Decimal("1000"), Decimal("0"), net=False) == Decimal("60.00")

    def test_partial_wage_base_remaining(self):
        # $5,500 prior, $2,000 wages → only $1,500 is subject to FUTA
        # $1,500 × 0.6% = $9.00
        result = calc_futa(Decimal("2000"), Decimal("5500"))
        assert result == Decimal("9.00")

    def test_at_wage_base_no_tax(self):
        result = calc_futa(Decimal("2000"), FUTA_WAGE_BASE)
        assert result == Decimal("0.00")

    def test_over_wage_base_no_tax(self):
        result = calc_futa(Decimal("5000"), FUTA_WAGE_BASE + Decimal("1000"))
        assert result == Decimal("0.00")

    def test_zero_wages(self):
        assert calc_futa(Decimal("0"), Decimal("0")) == Decimal("0.00")

    def test_full_first_paycheck_covers_partial_base(self):
        # First paycheck of year: $4,000 wages → all subject, $4,000 × 0.6% = $24
        result = calc_futa(Decimal("4000"), Decimal("0"))
        assert result == Decimal("24.00")

    def test_entire_wage_base_in_one_paycheck(self):
        # $10,000 wages, no prior → capped at $7,000; $7,000 × 0.6% = $42
        result = calc_futa(Decimal("10000"), Decimal("0"))
        assert result == Decimal("42.00")


class TestSUTA:
    def test_standard_suta(self):
        rate = Decimal("0.027")  # 2.7%
        # $2,000 wages, no prior → $2,000 × 2.7% = $54
        assert calc_suta(Decimal("2000"), Decimal("0"), rate) == Decimal("54.00")

    def test_partial_wage_base(self):
        rate = Decimal("0.027")
        # $25,000 prior, $4,000 wages → only $2,000 subject ($27,000 cap)
        result = calc_suta(Decimal("4000"), Decimal("25000"), rate)
        assert result == Decimal("54.00")

    def test_at_wage_base_no_tax(self):
        rate = Decimal("0.027")
        result = calc_suta(Decimal("2000"), OK_SUTA_WAGE_BASE, rate)
        assert result == Decimal("0.00")

    def test_zero_rate(self):
        result = calc_suta(Decimal("5000"), Decimal("0"), Decimal("0"))
        assert result == Decimal("0.00")

    def test_zero_wages(self):
        assert calc_suta(Decimal("0"), Decimal("0"), Decimal("0.027")) == Decimal("0.00")
