"""
Full paycheck calculator — orchestrates all tax engine modules.

Calculation order per IRS/OTC rules:
  1. Taxable wages = gross - pre-tax (Section 125) deductions
  2. Federal income tax
  3. Oklahoma state income tax
  4. Employee FICA (SS + Medicare)
  5. Employer FICA (SS + Medicare match)
  6. FUTA (employer)
  7. SUTA (employer)
  8. Workers comp (employer)
  9. Post-tax deductions (Roth 401k, voluntary after-tax)
 10. Net pay = gross - pre_tax_deductions - employee taxes - post_tax_deductions
"""
from decimal import Decimal
from .models import PaycheckInput, PaycheckResult, TaxResult, GarnishmentResultItem
from .fica import calc_ss_employee, calc_ss_employer, calc_medicare_employee, calc_medicare_employer
from .federal import calc_federal_withholding, calc_supplemental_federal
from .oklahoma import calc_ok_withholding, calc_supplemental_ok
from .unemployment import calc_futa, calc_suta
from .workers_comp import calc_workers_comp
from .garnishments import calc_garnishments, GarnishmentInput


def calculate_paycheck(inp: PaycheckInput) -> PaycheckResult:
    gross = inp.gross_wages
    taxable = gross - inp.pre_tax_deductions  # income-tax wages
    # Traditional 401k deferrals cut income-tax wages but remain FICA/FUTA/SUTA wages.
    fica_wages = taxable + inp.pre_tax_retirement

    taxes = TaxResult()

    # Federal income tax
    if inp.w4 is not None and inp.w4.exempt:
        pass  # exempt covers supplemental wages too (no $1M+ mandatory rate modeled)
    elif inp.is_supplemental and inp.federal_flat_allowed:
        taxes.federal_income_tax = calc_supplemental_federal(taxable)
    elif inp.is_supplemental and inp.w4 is not None:
        # Aggregate method (IRS Pub. 15): tax the bonus plus the most recent regular
        # paycheck's wages as one payment, less the tax already withheld from them.
        total = calc_federal_withholding(taxable + inp.regular_taxable, inp.pay_frequency, inp.w4,
                                         table=inp.federal_table)
        taxes.federal_income_tax = max(Decimal("0"), total - inp.regular_federal_tax)
    elif inp.w4 is not None:
        taxes.federal_income_tax = calc_federal_withholding(taxable, inp.pay_frequency, inp.w4, table=inp.federal_table)

    # Oklahoma state income tax
    ok = inp.ok_withholding
    if ok is None or ok.exempt:
        pass
    elif inp.is_supplemental and inp.ok_flat_allowed:
        taxes.ok_income_tax = calc_supplemental_ok(taxable, inp.ok_table)
    elif inp.is_supplemental:
        total = calc_ok_withholding(taxable + inp.regular_taxable, inp.pay_frequency, ok, table=inp.ok_table)
        taxes.ok_income_tax = max(Decimal("0"), total - inp.regular_ok_tax)
    else:
        taxes.ok_income_tax = calc_ok_withholding(taxable, inp.pay_frequency, ok, table=inp.ok_table)

    # Employee FICA
    taxes.ss_employee = calc_ss_employee(fica_wages, inp.ytd_ss_wages_prior, wage_base=inp.ss_wage_base)
    taxes.medicare_employee = calc_medicare_employee(fica_wages, inp.ytd_gross_prior)

    # Employer FICA
    taxes.ss_employer = calc_ss_employer(fica_wages, inp.ytd_ss_wages_prior, wage_base=inp.ss_wage_base)
    taxes.medicare_employer = calc_medicare_employer(fica_wages)

    # Employer unemployment
    taxes.futa = calc_futa(fica_wages, inp.ytd_futa_wages_prior)
    taxes.suta = calc_suta(fica_wages, inp.ytd_suta_wages_prior, inp.suta_rate, wage_base=inp.suta_wage_base)

    # Employer workers comp (on gross wages, not taxable wages)
    taxes.workers_comp = calc_workers_comp(gross, inp.workers_comp_rate)

    # Garnishments (after all taxes, on disposable earnings)
    garnishment_total = Decimal("0")
    garnishment_results = []
    if inp.garnishments:
        employee_taxes = (taxes.federal_income_tax + taxes.ok_income_tax +
                          taxes.ss_employee + taxes.medicare_employee)
        # CCPA: only amounts required by law (income tax, FICA) come off. Voluntary
        # pre-tax benefits and 401k deferrals do not reduce disposable earnings.
        disposable = gross - employee_taxes
        garn_inputs = [
            GarnishmentInput(
                garnishment_type=g.garnishment_type,
                amount=g.amount,
                percent=g.percent,
                amount_type=g.amount_type,
                max_total=g.max_total,
                ytd_withheld=g.ytd_withheld,
                order_id=g.order_id,
            )
            for g in inp.garnishments
        ]
        raw_results = calc_garnishments(disposable, garn_inputs, inp.pay_frequency)
        for r in raw_results:
            garnishment_total += r.amount
            garnishment_results.append(GarnishmentResultItem(
                order_id=r.order_id,
                garnishment_type=r.garnishment_type,
                amount=r.amount,
            ))

    return PaycheckResult(
        gross_wages=gross,
        pre_tax_deductions=inp.pre_tax_deductions,
        post_tax_deductions=inp.post_tax_deductions,
        garnishment_total=garnishment_total,
        garnishment_results=garnishment_results,
        taxable_wages=taxable,
        fica_wages=fica_wages,
        taxes=taxes,
    )
