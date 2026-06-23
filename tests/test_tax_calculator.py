"""
Integration tests for the full paycheck calculator.
Verifies that all tax components combine correctly.
"""
from decimal import Decimal
import pytest
from tax_engine.calculator import calculate_paycheck
from tax_engine.models import PaycheckInput, W4Input, OKWithholdingInput


def make_input(**kwargs):
    defaults = dict(
        gross_wages=Decimal("2000"),
        pay_frequency="biweekly",
        w4=W4Input(filing_status="single"),
        ok_withholding=OKWithholdingInput(filing_status="single", allowances=1),
        suta_rate=Decimal("0.027"),
    )
    defaults.update(kwargs)
    return PaycheckInput(**defaults)


class TestBasicPaycheck:
    def test_result_has_all_tax_fields(self):
        result = calculate_paycheck(make_input())
        taxes = result.taxes
        assert taxes.federal_income_tax >= Decimal("0")
        assert taxes.ok_income_tax >= Decimal("0")
        assert taxes.ss_employee >= Decimal("0")
        assert taxes.medicare_employee >= Decimal("0")
        assert taxes.ss_employer >= Decimal("0")
        assert taxes.medicare_employer >= Decimal("0")
        assert taxes.futa >= Decimal("0")
        assert taxes.suta >= Decimal("0")
        assert taxes.workers_comp >= Decimal("0")

    def test_net_pay_is_gross_minus_pretax_minus_employee_taxes(self):
        inp = make_input(gross_wages=Decimal("2000"), pre_tax_deductions=Decimal("150"))
        result = calculate_paycheck(inp)
        expected_net = Decimal("2000") - Decimal("150") - result.total_employee_taxes
        assert result.net_pay == expected_net

    def test_taxable_wages_is_gross_minus_pretax(self):
        inp = make_input(gross_wages=Decimal("3000"), pre_tax_deductions=Decimal("200"))
        result = calculate_paycheck(inp)
        assert result.taxable_wages == Decimal("2800")

    def test_fica_uses_taxable_wages(self):
        # With pre-tax deductions, FICA base should be reduced
        inp_no_pretax = make_input(gross_wages=Decimal("2000"), pre_tax_deductions=Decimal("0"))
        inp_with_pretax = make_input(gross_wages=Decimal("2000"), pre_tax_deductions=Decimal("200"))
        r1 = calculate_paycheck(inp_no_pretax)
        r2 = calculate_paycheck(inp_with_pretax)
        assert r2.taxes.ss_employee < r1.taxes.ss_employee

    def test_workers_comp_uses_gross_wages(self):
        # Workers comp is on gross wages, not taxable wages
        inp = make_input(
            gross_wages=Decimal("2000"),
            pre_tax_deductions=Decimal("500"),
            workers_comp_rate=Decimal("1.00"),  # $1 per $100
        )
        result = calculate_paycheck(inp)
        # $2,000 gross / 100 × $1.00 = $20.00
        assert result.taxes.workers_comp == Decimal("20.00")

    def test_employer_ss_matches_employee_ss(self):
        result = calculate_paycheck(make_input())
        assert result.taxes.ss_employer == result.taxes.ss_employee

    def test_net_pay_is_positive_for_normal_wages(self):
        result = calculate_paycheck(make_input(gross_wages=Decimal("2000")))
        assert result.net_pay > Decimal("0")


class TestNoW4OrOKWithholding:
    def test_no_w4_means_no_federal_withholding(self):
        inp = make_input(w4=None)
        result = calculate_paycheck(inp)
        assert result.taxes.federal_income_tax == Decimal("0")

    def test_no_ok_withholding_means_no_state_withholding(self):
        inp = make_input(ok_withholding=None)
        result = calculate_paycheck(inp)
        assert result.taxes.ok_income_tax == Decimal("0")

    def test_fica_still_applies_without_w4(self):
        inp = make_input(w4=None, ok_withholding=None)
        result = calculate_paycheck(inp)
        assert result.taxes.ss_employee > Decimal("0")
        assert result.taxes.medicare_employee > Decimal("0")


class TestSupplementalWages:
    def test_supplemental_uses_22_percent(self):
        inp = make_input(
            gross_wages=Decimal("1000"),
            is_supplemental=True,
            w4=W4Input(filing_status="single"),  # ignored for supplemental
        )
        result = calculate_paycheck(inp)
        assert result.taxes.federal_income_tax == Decimal("220.00")


class TestYTDWageBases:
    def test_ss_stops_at_wage_base(self):
        # Already at SS wage base — no more SS
        inp = make_input(
            gross_wages=Decimal("5000"),
            ytd_ss_wages_prior=Decimal("176100"),
        )
        result = calculate_paycheck(inp)
        assert result.taxes.ss_employee == Decimal("0.00")
        assert result.taxes.ss_employer == Decimal("0.00")

    def test_futa_stops_at_wage_base(self):
        inp = make_input(
            gross_wages=Decimal("2000"),
            ytd_futa_wages_prior=Decimal("7000"),
        )
        result = calculate_paycheck(inp)
        assert result.taxes.futa == Decimal("0.00")

    def test_suta_stops_at_wage_base(self):
        inp = make_input(
            gross_wages=Decimal("2000"),
            ytd_suta_wages_prior=Decimal("27000"),
        )
        result = calculate_paycheck(inp)
        assert result.taxes.suta == Decimal("0.00")


class TestPostTaxDeductions:
    def test_post_tax_reduces_net_pay(self):
        inp = make_input(gross_wages=Decimal("2000"), post_tax_deductions=Decimal("100"))
        result = calculate_paycheck(inp)
        expected_net = Decimal("2000") - result.total_employee_taxes - Decimal("100")
        assert result.net_pay == expected_net

    def test_post_tax_does_not_affect_taxable_wages(self):
        inp_no = make_input(gross_wages=Decimal("2000"), post_tax_deductions=Decimal("0"))
        inp_with = make_input(gross_wages=Decimal("2000"), post_tax_deductions=Decimal("200"))
        r1 = calculate_paycheck(inp_no)
        r2 = calculate_paycheck(inp_with)
        assert r1.taxable_wages == r2.taxable_wages
        assert r1.taxes.ss_employee == r2.taxes.ss_employee

    def test_post_tax_stored_in_result(self):
        inp = make_input(post_tax_deductions=Decimal("75"))
        result = calculate_paycheck(inp)
        assert result.post_tax_deductions == Decimal("75")

    def test_total_deductions_sums_both(self):
        inp = make_input(pre_tax_deductions=Decimal("150"), post_tax_deductions=Decimal("100"))
        result = calculate_paycheck(inp)
        assert result.total_deductions == Decimal("250")

    def test_combined_pre_and_post_tax_net_pay(self):
        inp = make_input(
            gross_wages=Decimal("3000"),
            pre_tax_deductions=Decimal("200"),
            post_tax_deductions=Decimal("100"),
        )
        result = calculate_paycheck(inp)
        expected = Decimal("3000") - Decimal("200") - result.total_employee_taxes - Decimal("100")
        assert result.net_pay == expected


class TestTotals:
    def test_total_employee_taxes_sums_correctly(self):
        result = calculate_paycheck(make_input())
        t = result.taxes
        expected = (t.federal_income_tax + t.ok_income_tax +
                    t.ss_employee + t.medicare_employee)
        assert result.total_employee_taxes == expected

    def test_total_employer_taxes_sums_correctly(self):
        result = calculate_paycheck(make_input())
        t = result.taxes
        expected = (t.ss_employer + t.medicare_employer +
                    t.futa + t.suta + t.workers_comp)
        assert result.total_employer_taxes == expected
