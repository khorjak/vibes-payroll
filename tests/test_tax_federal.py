"""
Tests for federal income tax withholding (IRS Pub 15-T 2025 percentage method).

Test values are derived from hand calculations against the 2025 tax brackets:
  Single/MFS standard deduction $15,000; MFJ/QSS $30,000; HoH $22,500.
"""
import pytest
from decimal import Decimal
from tax_engine.federal import calc_federal_withholding, calc_supplemental_federal
from tax_engine.models import W4Input


def w4(filing_status="single", multiple_jobs=False, dependents=0, other=0, deductions=0, extra=0):
    return W4Input(
        filing_status=filing_status,
        multiple_jobs=multiple_jobs,
        dependents_amount=Decimal(str(dependents)),
        other_income=Decimal(str(other)),
        deductions_amount=Decimal(str(deductions)),
        extra_withholding=Decimal(str(extra)),
    )


class TestSingleStandard:
    def test_below_standard_deduction_no_withholding(self):
        # $500/week → $26,000 annual; adjusted = $26,000; below $26,925 threshold → 10% bracket
        # Tax = ($26,000 - $15,000) × 10% = $1,100 annual → $1,100/52 ≈ $21.15
        result = calc_federal_withholding(Decimal("500"), "weekly", w4("single"))
        assert result == Decimal("21.15")

    def test_in_12_percent_bracket(self):
        # $2,000 biweekly → $52,000 annual; adjusted = $52,000
        # In bracket $26,925–$63,475 (12%):
        # Tax = $1,192.50 + ($52,000 - $26,925) × 12% = $1,192.50 + $3,009 = $4,201.50
        # Per period: $4,201.50 / 26 = $161.60 (rounded)
        result = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        assert result == Decimal("161.60")

    def test_in_22_percent_bracket(self):
        # $4,000 biweekly → $104,000 annual; in $63,475–$118,350 (22%) bracket
        # Tax = $5,578.50 + ($104,000 - $63,475) × 22% = $5,578.50 + $8,915.50 = $14,494
        # Per period: $14,494 / 26 = $557.46
        result = calc_federal_withholding(Decimal("4000"), "biweekly", w4("single"))
        assert result == Decimal("557.46")

    def test_zero_wages_no_withholding(self):
        result = calc_federal_withholding(Decimal("0"), "biweekly", w4("single"))
        assert result == Decimal("0.00")

    def test_very_low_wages_no_withholding(self):
        # $500 biweekly → $13,000 annual; below $15,000 standard deduction → $0
        result = calc_federal_withholding(Decimal("500"), "biweekly", w4("single"))
        assert result == Decimal("0.00")

    def test_extra_withholding_added(self):
        base = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        with_extra = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", extra=50))
        assert with_extra == base + Decimal("50")

    def test_dependents_amount_reduces_withholding(self):
        base = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        # $4,000 dependents credit → reduces annual withholding by $4,000 → per period by $4,000/26 ≈ $153.85
        with_deps = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", dependents=4000))
        assert with_deps < base
        assert base - with_deps == pytest.approx(Decimal("153.85"), abs=Decimal("0.01"))

    def test_other_income_increases_withholding(self):
        base = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        with_other = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", other=5200))
        assert with_other > base

    def test_deductions_reduce_withholding(self):
        base = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        with_deductions = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", deductions=5200))
        assert with_deductions < base

    def test_withholding_cannot_go_negative(self):
        # Enormous dependents amount should floor at $0
        result = calc_federal_withholding(Decimal("500"), "biweekly", w4("single", dependents=99999))
        assert result == Decimal("0.00")


class TestMFJStandard:
    def test_in_10_percent_bracket(self):
        # $1,500 biweekly → $39,000 annual; MFJ $30,000–$53,850 bracket (10%)
        # Tax = ($39,000 - $30,000) × 10% = $900
        # Per period: $900 / 26 = $34.62
        result = calc_federal_withholding(Decimal("1500"), "biweekly", w4("married_filing_jointly"))
        assert result == Decimal("34.62")

    def test_in_12_percent_bracket(self):
        # $3,000 biweekly → $78,000 annual; MFJ $53,850–$126,950 (12%)
        # Tax = $2,385 + ($78,000 - $53,850) × 12% = $2,385 + $2,898 = $5,283
        # Per period: $5,283 / 26 = $203.19
        result = calc_federal_withholding(Decimal("3000"), "biweekly", w4("married_filing_jointly"))
        assert result == Decimal("203.19")

    def test_below_standard_deduction_no_withholding(self):
        # $1,000 biweekly → $26,000 annual; MFJ standard deduction = $30,000 → $0
        result = calc_federal_withholding(Decimal("1000"), "biweekly", w4("married_filing_jointly"))
        assert result == Decimal("0.00")


class TestFilingStatusAliases:
    def test_married_filing_separately_uses_single_table(self):
        mfs = calc_federal_withholding(Decimal("2000"), "biweekly", w4("married_filing_separately"))
        single = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single"))
        assert mfs == single

    def test_qualifying_surviving_spouse_uses_mfj_table(self):
        qss = calc_federal_withholding(Decimal("3000"), "biweekly", w4("qualifying_surviving_spouse"))
        mfj = calc_federal_withholding(Decimal("3000"), "biweekly", w4("married_filing_jointly"))
        assert qss == mfj


class TestHigherWithholding:
    def test_multiple_jobs_increases_withholding_for_single(self):
        # Step 2 checked halves the standard deduction offset → more income is taxable
        standard = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", multiple_jobs=False))
        high = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", multiple_jobs=True))
        assert high > standard

    def test_multiple_jobs_mfj_uses_high_table(self):
        standard = calc_federal_withholding(Decimal("3000"), "biweekly", w4("married_filing_jointly", multiple_jobs=False))
        high = calc_federal_withholding(Decimal("3000"), "biweekly", w4("married_filing_jointly", multiple_jobs=True))
        assert high > standard

    def test_single_high_withholding_calculation(self):
        # $2,000 biweekly → $52,000 annual; Step 2 checked → offset $7,500
        # In Single High bracket $19,425–$55,975 (12%)
        # Tax = $1,192.50 + ($52,000 - $19,425) × 12% = $1,192.50 + $3,909 = $5,101.50
        # Per period: $5,101.50 / 26 = $196.21
        result = calc_federal_withholding(Decimal("2000"), "biweekly", w4("single", multiple_jobs=True))
        assert result == Decimal("196.21")


class TestPayFrequencies:
    def test_weekly_withholding(self):
        result = calc_federal_withholding(Decimal("1000"), "weekly", w4("single"))
        assert result >= Decimal("0")

    def test_semi_monthly_withholding(self):
        result = calc_federal_withholding(Decimal("2500"), "semi_monthly", w4("single"))
        assert result >= Decimal("0")

    def test_monthly_withholding(self):
        result = calc_federal_withholding(Decimal("5000"), "monthly", w4("single"))
        assert result >= Decimal("0")

    def test_biweekly_and_semi_monthly_same_annual_income_similar_tax(self):
        # $2,600 biweekly (26 × $2,600 = $67,600) vs $2,817 semi-monthly (24 × $2,817 ≈ $67,608)
        # Should produce similar total annual withholding
        biweekly = calc_federal_withholding(Decimal("2600"), "biweekly", w4("single"))
        semi = calc_federal_withholding(Decimal("2817"), "semi_monthly", w4("single"))
        # Annual: biweekly × 26 ≈ semi × 24 (within ~$50)
        annual_biweekly = biweekly * 26
        annual_semi = semi * 24
        assert abs(annual_biweekly - annual_semi) < Decimal("60")


class TestSupplemental:
    def test_supplemental_rate_is_22_percent(self):
        result = calc_supplemental_federal(Decimal("1000"))
        assert result == Decimal("220.00")

    def test_supplemental_rounds_correctly(self):
        result = calc_supplemental_federal(Decimal("333.33"))
        assert result == Decimal("73.33")
