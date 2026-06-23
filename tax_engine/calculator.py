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
from .oklahoma import calc_ok_withholding
from .unemployment import calc_futa, calc_suta
from .workers_comp import calc_workers_comp
from .garnishments import calc_garnishments, GarnishmentInput


def calculate_paycheck(inp: PaycheckInput) -> PaycheckResult:
    gross = inp.gross_wages
    taxable = gross - inp.pre_tax_deductions  # used for income tax and FICA

    taxes = TaxResult()

    # Federal income tax
    if inp.is_supplemental:
        taxes.federal_income_tax = calc_supplemental_federal(taxable)
    elif inp.w4 is not None:
        taxes.federal_income_tax = calc_federal_withholding(taxable, inp.pay_frequency, inp.w4)

    # Oklahoma state income tax
    if inp.ok_withholding is not None:
        taxes.ok_income_tax = calc_ok_withholding(taxable, inp.pay_frequency, inp.ok_withholding)

    # Employee FICA
    taxes.ss_employee = calc_ss_employee(taxable, inp.ytd_ss_wages_prior)
    taxes.medicare_employee = calc_medicare_employee(taxable, inp.ytd_gross_prior)

    # Employer FICA
    taxes.ss_employer = calc_ss_employer(taxable, inp.ytd_ss_wages_prior)
    taxes.medicare_employer = calc_medicare_employer(taxable)

    # Employer unemployment
    taxes.futa = calc_futa(taxable, inp.ytd_futa_wages_prior)
    taxes.suta = calc_suta(taxable, inp.ytd_suta_wages_prior, inp.suta_rate)

    # Employer workers comp (on gross wages, not taxable wages)
    taxes.workers_comp = calc_workers_comp(gross, inp.workers_comp_rate)

    # Garnishments (after all taxes, on disposable earnings)
    garnishment_total = Decimal("0")
    garnishment_results = []
    if inp.garnishments:
        employee_taxes = (taxes.federal_income_tax + taxes.ok_income_tax +
                          taxes.ss_employee + taxes.medicare_employee)
        disposable = gross - inp.pre_tax_deductions - employee_taxes
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
        taxes=taxes,
    )
