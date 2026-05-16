"""Tests for FICA calculations (Social Security and Medicare)."""
import pytest
from decimal import Decimal
from tax_engine.fica import (
    calc_ss_employee, calc_ss_employer,
    calc_medicare_employee, calc_medicare_employer,
    SS_WAGE_BASE, ADDITIONAL_MEDICARE_THRESHOLD,
)


class TestSocialSecurity:
    def test_standard_withholding_no_prior_ytd(self):
        # 6.2% of $2,000
        assert calc_ss_employee(Decimal("2000"), Decimal("0")) == Decimal("124.00")

    def test_employer_matches_employee(self):
        wages = Decimal("2000")
        assert calc_ss_employee(wages, Decimal("0")) == calc_ss_employer(wages, Decimal("0"))

    def test_partial_wage_base_remaining(self):
        # $1,000 remaining before cap: only $1,000 is taxable
        prior = SS_WAGE_BASE - Decimal("1000")
        result = calc_ss_employee(Decimal("2000"), prior)
        assert result == Decimal("62.00")  # $1,000 × 6.2%

    def test_at_wage_base_no_tax(self):
        # YTD already at cap — no SS owed
        result = calc_ss_employee(Decimal("2000"), SS_WAGE_BASE)
        assert result == Decimal("0.00")

    def test_over_wage_base_no_tax(self):
        result = calc_ss_employee(Decimal("5000"), SS_WAGE_BASE + Decimal("1000"))
        assert result == Decimal("0.00")

    def test_exact_wage_base_in_single_paycheck(self):
        result = calc_ss_employee(SS_WAGE_BASE, Decimal("0"))
        expected = (SS_WAGE_BASE * Decimal("0.062")).quantize(Decimal("0.01"))
        assert result == expected

    def test_zero_wages(self):
        assert calc_ss_employee(Decimal("0"), Decimal("0")) == Decimal("0.00")

    def test_small_wages_rounds_correctly(self):
        # $100 × 6.2% = $6.20
        assert calc_ss_employee(Decimal("100"), Decimal("0")) == Decimal("6.20")


class TestMedicare:
    def test_standard_medicare_no_additional(self):
        # 1.45% of $2,000 = $29.00, YTD well below $200k
        result = calc_medicare_employee(Decimal("2000"), Decimal("0"))
        assert result == Decimal("29.00")

    def test_employer_medicare_no_additional(self):
        result = calc_medicare_employer(Decimal("2000"))
        assert result == Decimal("29.00")

    def test_employer_has_no_additional_medicare(self):
        # Employer never pays the 0.9% additional Medicare
        high_ytd = Decimal("210000")
        employer = calc_medicare_employer(Decimal("10000"))
        assert employer == Decimal("145.00")  # flat 1.45% only

    def test_additional_medicare_kicks_in_when_ytd_crosses_threshold(self):
        # YTD prior = $195,000; this paycheck = $10,000 → crosses $200k threshold
        # $5,000 is above threshold → additional = $5,000 × 0.9% = $45
        # Base: $10,000 × 1.45% = $145
        result = calc_medicare_employee(Decimal("10000"), Decimal("195000"))
        assert result == Decimal("190.00")  # $145 + $45

    def test_additional_medicare_fully_above_threshold(self):
        # YTD prior = $205,000; entire paycheck is above threshold
        # Base: $5,000 × 1.45% = $72.50; Additional: $5,000 × 0.9% = $45
        result = calc_medicare_employee(Decimal("5000"), Decimal("205000"))
        assert result == Decimal("117.50")

    def test_no_additional_medicare_below_threshold(self):
        result = calc_medicare_employee(Decimal("5000"), Decimal("150000"))
        assert result == Decimal("72.50")  # 1.45% only

    def test_zero_wages(self):
        assert calc_medicare_employee(Decimal("0"), Decimal("0")) == Decimal("0.00")
        assert calc_medicare_employer(Decimal("0")) == Decimal("0.00")
