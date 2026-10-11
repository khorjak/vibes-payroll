"""
Oklahoma withholding: OTC Packet OW-2 percentage formula, annual tables (Table 7).

Annualize wages -> subtract $1,000 per allowance -> single or married annual table
-> divide by pay periods -> round to the nearest whole dollar (OW-2) -> add extra.
Expected values are hand-computed from the 2025 and 2026 OW-2 annual tables and
agree with OW-2's per-period tables.
"""
import pytest
from decimal import Decimal

from models.oklahoma_withholding import DEFAULT_OKLAHOMA_TABLES
from services.tax_years import check_ok_data
from tax_engine.models import OKTable, OKWithholdingInput
from tax_engine.oklahoma import calc_ok_withholding

T2025 = OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[2025])
T2026 = OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[2026])


def ok(filing_status="single", allowances=0, extra=0):
    return OKWithholdingInput(filing_status=filing_status, allowances=allowances,
                              extra_withholding=Decimal(str(extra)))


def calc(wages, frequency, election, table=T2026):
    return calc_ok_withholding(Decimal(str(wages)), frequency, election, table=table)


class TestOK2026:
    def test_otc_worked_example(self):
        # OW-2 (2026) sample computation: $1,825 semi-monthly, married, 2 allowances -> $37.00.
        # Annual: 43,800 - 2,000 = 41,800; 218.50 + 4.5% x 14,700 = 880.00 / 24 = 36.67
        assert calc(1825, "semi_monthly", ok("married", 2)) == Decimal("37.00")

    def test_single_no_allowances(self):
        # 52,000: 109.25 + 4.5% x 38,450 = 1,839.50 / 26 = 70.75 -> $71
        assert calc(2000, "biweekly", ok("single")) == Decimal("71.00")

    def test_married_uses_the_married_table(self):
        # 52,000: 218.50 + 4.5% x 24,900 = 1,339.00 / 26 = 51.50 -> $52 (half rounds up)
        assert calc(2000, "biweekly", ok("married")) == Decimal("52.00")

    def test_married_two_allowances(self):
        # 50,000: 218.50 + 4.5% x 22,900 = 1,249.00 / 26 = 48.04 -> $48
        assert calc(2000, "biweekly", ok("married", 2)) == Decimal("48.00")

    def test_zero_band_covers_standard_deduction_and_zero_bracket(self):
        # 9,880 a year is under the $10,100 single zero band.
        assert calc(380, "biweekly", ok("single")) == Decimal("0.00")

    def test_lower_brackets(self):
        # 13,000: 28.75 + 3.5% x 1,750 = 90.00 / 52 = 1.73 -> $2
        assert calc(250, "weekly", ok("single")) == Decimal("2.00")

    def test_allowances_can_reduce_to_zero(self):
        assert calc(500, "biweekly", ok("single", 20)) == Decimal("0.00")

    def test_extra_withholding_added_after_rounding(self):
        assert calc(2000, "biweekly", ok("single", extra=25)) == Decimal("96.00")

    def test_exempt_withholds_nothing(self):
        o = OKWithholdingInput(filing_status="single", extra_withholding=Decimal("25"), exempt=True)
        assert calc(2000, "biweekly", o) == Decimal("0")


class TestOK2025:
    def test_single_no_allowances(self):
        # 52,000: 153.50 + 4.75% x 38,450 = 1,979.88 / 26 = 76.15 -> $76
        assert calc(2000, "biweekly", ok("single"), T2025) == Decimal("76.00")

    def test_single_one_allowance(self):
        # 51,000: 153.50 + 4.75% x 37,450 = 1,932.38 / 26 = 74.32 -> $74
        assert calc(2000, "biweekly", ok("single", 1), T2025) == Decimal("74.00")

    def test_zero_band_is_the_standard_deduction(self):
        # 7,800: 2.50 + 0.75% x 450 = 5.88 / 26 = 0.23 -> $0
        assert calc(300, "biweekly", ok("single"), T2025) == Decimal("0.00")


@pytest.mark.parametrize("year", sorted(DEFAULT_OKLAHOMA_TABLES))
def test_shipped_tables_pass_the_entry_checks(year):
    assert check_ok_data(DEFAULT_OKLAHOMA_TABLES[year]) == {}
