"""Tests for garnishment calculation and CCPA limits."""
from decimal import Decimal
import pytest
from tax_engine.garnishments import calc_garnishments, GarnishmentInput, FEDERAL_MIN_WAGE
from tax_engine.calculator import calculate_paycheck
from tax_engine.models import PaycheckInput, W4Input, OKWithholdingInput, GarnishmentInputItem


# ── calc_garnishments unit tests ─────────────────────────────────────────────

class TestCalcGarnishments:
    def test_no_garnishments_returns_empty(self):
        results = calc_garnishments(Decimal("2000"), [])
        assert results == []

    def test_zero_disposable_returns_empty(self):
        g = GarnishmentInput(garnishment_type="creditor", amount=Decimal("100"))
        results = calc_garnishments(Decimal("0"), [g])
        assert results == []

    def test_single_creditor_under_limit(self):
        disposable = Decimal("2000")
        g = GarnishmentInput(garnishment_type="creditor", amount=Decimal("100"), order_id=1)
        results = calc_garnishments(disposable, [g], "biweekly")
        assert len(results) == 1
        assert results[0].amount == Decimal("100.00")

    def test_creditor_capped_at_25pct(self):
        disposable = Decimal("1000")
        g = GarnishmentInput(garnishment_type="creditor", amount=Decimal("500"), order_id=1)
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results[0].amount == Decimal("250.00")

    def test_creditor_capped_by_30x_min_wage(self):
        # Biweekly: 30 × $7.25 × 2 = $435
        # Disposable = $500, excess over $435 = $65
        # 25% of $500 = $125 → min($125, $65) = $65
        disposable = Decimal("500")
        g = GarnishmentInput(garnishment_type="creditor", amount=Decimal("200"), order_id=1)
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results[0].amount == Decimal("65.00")

    def test_child_support_gets_50pct_limit(self):
        disposable = Decimal("2000")
        g = GarnishmentInput(garnishment_type="child_support", amount=Decimal("1500"), order_id=1)
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results[0].amount == Decimal("1000.00")

    def test_child_support_priority_over_creditor(self):
        disposable = Decimal("2000")
        garnishments = [
            GarnishmentInput(garnishment_type="creditor", amount=Decimal("400"), order_id=2),
            GarnishmentInput(garnishment_type="child_support", amount=Decimal("800"), order_id=1),
        ]
        results = calc_garnishments(disposable, garnishments, "biweekly")
        # Child support first (priority 1), creditor second (priority 5)
        assert results[0].garnishment_type == "child_support"
        assert results[0].amount == Decimal("800.00")
        assert results[1].garnishment_type == "creditor"
        assert results[1].amount == Decimal("400.00")

    def test_multiple_creditors_share_limit(self):
        disposable = Decimal("2000")
        garnishments = [
            GarnishmentInput(garnishment_type="creditor", amount=Decimal("400"), order_id=1),
            GarnishmentInput(garnishment_type="creditor", amount=Decimal("400"), order_id=2),
        ]
        results = calc_garnishments(disposable, garnishments, "biweekly")
        total = sum(r.amount for r in results)
        # 25% of $2000 = $500
        assert total == Decimal("500.00")
        assert results[0].amount == Decimal("400.00")
        assert results[1].amount == Decimal("100.00")

    def test_percent_based_garnishment(self):
        disposable = Decimal("2000")
        g = GarnishmentInput(
            garnishment_type="creditor",
            amount=Decimal("0"),
            percent=Decimal("10"),
            amount_type="percent",
            order_id=1,
        )
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results[0].amount == Decimal("200.00")

    def test_max_total_caps_remaining(self):
        disposable = Decimal("2000")
        g = GarnishmentInput(
            garnishment_type="creditor",
            amount=Decimal("300"),
            max_total=Decimal("1000"),
            ytd_withheld=Decimal("900"),
            order_id=1,
        )
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results[0].amount == Decimal("100.00")

    def test_max_total_fully_satisfied_skipped(self):
        disposable = Decimal("2000")
        g = GarnishmentInput(
            garnishment_type="creditor",
            amount=Decimal("300"),
            max_total=Decimal("1000"),
            ytd_withheld=Decimal("1000"),
            order_id=1,
        )
        results = calc_garnishments(disposable, [g], "biweekly")
        assert results == []

    def test_weekly_frequency_30x_factor(self):
        # Weekly: 30 × $7.25 × 1 = $217.50
        # Disposable = $300, excess = $82.50
        # 25% of $300 = $75 → min($75, $82.50) = $75
        disposable = Decimal("300")
        g = GarnishmentInput(garnishment_type="creditor", amount=Decimal("200"), order_id=1)
        results = calc_garnishments(disposable, [g], "weekly")
        assert results[0].amount == Decimal("75.00")


# ── Calculator integration tests ─────────────────────────────────────────────

class TestCalculatorGarnishmentIntegration:
    def test_garnishment_reduces_net_pay(self):
        inp = PaycheckInput(
            gross_wages=Decimal("2000"),
            pay_frequency="biweekly",
            w4=W4Input(filing_status="single"),
            ok_withholding=OKWithholdingInput(filing_status="single", allowances=1),
            garnishments=[
                GarnishmentInputItem(
                    garnishment_type="creditor",
                    amount=Decimal("200"),
                    amount_type="fixed",
                    order_id=1,
                ),
            ],
        )
        result = calculate_paycheck(inp)
        assert result.garnishment_total == Decimal("200.00")
        assert result.net_pay == (
            result.gross_wages
            - result.pre_tax_deductions
            - result.total_employee_taxes
            - result.post_tax_deductions
            - result.garnishment_total
        )

    def test_no_garnishments_zero_total(self):
        inp = PaycheckInput(
            gross_wages=Decimal("2000"),
            pay_frequency="biweekly",
            w4=W4Input(filing_status="single"),
        )
        result = calculate_paycheck(inp)
        assert result.garnishment_total == Decimal("0")
        assert result.garnishment_results == []

    def test_garnishment_result_items_populated(self):
        inp = PaycheckInput(
            gross_wages=Decimal("3000"),
            pay_frequency="biweekly",
            w4=W4Input(filing_status="single"),
            garnishments=[
                GarnishmentInputItem(
                    garnishment_type="child_support",
                    amount=Decimal("500"),
                    amount_type="fixed",
                    order_id=10,
                ),
                GarnishmentInputItem(
                    garnishment_type="creditor",
                    amount=Decimal("100"),
                    amount_type="fixed",
                    order_id=20,
                ),
            ],
        )
        result = calculate_paycheck(inp)
        assert len(result.garnishment_results) == 2
        assert result.garnishment_results[0].garnishment_type == "child_support"
        assert result.garnishment_results[1].garnishment_type == "creditor"
