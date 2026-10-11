"""Per-year wage bases: stored in tax_years, edited by admins under Tax Settings."""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from models.audit import AuditLog
from models.payroll import Paycheck, PaycheckLine
from models.tax_year import TaxYear
from services.tax_years import seed_tax_years, tax_year_for
from tax_engine.calculator import calculate_paycheck
from models.federal_withholding import DEFAULT_FEDERAL_TABLES
from models.oklahoma_withholding import DEFAULT_OKLAHOMA_TABLES
from tax_engine.models import FederalTable, OKTable, PaycheckInput


# ── Lookup and seed ─────────────────────────────────────────────────────────

def test_seeded_with_published_figures(db):
    # SSA contribution and benefit base; OESC "Important Numbers" sheets.
    rows = {r.year: (r.ss_wage_base, r.ok_suta_wage_base) for r in db.query(TaxYear)}
    assert rows == {2024: (Decimal("168600"), Decimal("27000")),
                    2025: (Decimal("176100"), Decimal("28200")),
                    2026: (Decimal("184500"), Decimal("25000"))}


def test_seed_never_overwrites_admin_edits(db):
    db.get(TaxYear, 2026).ok_suta_wage_base = Decimal("99999")
    db.commit()
    seed_tax_years(db)
    assert db.get(TaxYear, 2026).ok_suta_wage_base == Decimal("99999")


def test_missing_year_falls_back_to_latest_earlier_then_earliest(db):
    assert tax_year_for(db, 2025).year == 2025
    assert tax_year_for(db, 2027).year == 2026
    assert tax_year_for(db, 2020).year == 2024


def test_empty_table_is_a_clear_error(db):
    db.query(TaxYear).delete()
    db.commit()
    with pytest.raises(ValueError, match="Tax Settings"):
        tax_year_for(db, 2026)


# ── Engine and payroll ──────────────────────────────────────────────────────

def test_engine_uses_the_bases_it_is_given():
    def taxes(ss, suta, **ytd):
        return calculate_paycheck(PaycheckInput(
            gross_wages=Decimal("2000"), pay_frequency="biweekly", suta_rate=Decimal("0.027"),
            ss_wage_base=Decimal(ss), suta_wage_base=Decimal(suta),
            federal_table=FederalTable.from_data(DEFAULT_FEDERAL_TABLES[2026]),
            ok_table=OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[2026]), **ytd)).taxes
    # 26,000 prior: room under 28,200 (2025), none under 25,000 (2026).
    assert taxes("176100", "28200", ytd_suta_wages_prior=Decimal("26000")).suta == Decimal("54.00")
    assert taxes("184500", "25000", ytd_suta_wages_prior=Decimal("26000")).suta == Decimal("0.00")
    # 180,000 prior: over 176,100 (2025), under 184,500 (2026).
    assert taxes("176100", "28200", ytd_ss_wages_prior=Decimal("180000")).ss_employee == Decimal("0.00")
    assert taxes("184500", "25000", ytd_ss_wages_prior=Decimal("180000")).ss_employee == Decimal("124.00")


def _suta_line(db):
    pc = db.query(Paycheck).first()
    return next(l.amount for l in db.query(PaycheckLine).filter_by(paycheck_id=pc.id) if l.description == "SUTA")


def test_payroll_reads_the_pay_years_row(client, db, company, salaried_employee, pay_period):
    # An admin edit to the 2026 row changes what a 2026 paycheck charges.
    db.get(TaxYear, pay_period.pay_date.year).ok_suta_wage_base = Decimal("1000")
    db.commit()
    client.post(f"/payroll/{pay_period.id}/calculate")
    rate = Decimal(str(company.suta_rate or "0.027"))
    assert Decimal(str(_suta_line(db))) == (Decimal("1000") * rate).quantize(Decimal("0.01"))


# ── Warnings ────────────────────────────────────────────────────────────────

def test_pay_period_warns_when_its_year_is_missing(client, db, pay_period):
    assert "wage bases on file" not in client.get(f"/payroll/{pay_period.id}").text
    db.delete(db.get(TaxYear, 2026))
    db.commit()
    page = client.get(f"/payroll/{pay_period.id}").text
    assert "No 2026 wage bases on file" in page and "uses the 2025" in page
    assert 'href="/tax-settings/?year=2026"' in page


def test_suta_report_flags_a_fallback_year(client, db, company, salaried_employee):
    from models.payroll import PayPeriod
    pp = PayPeriod(company_id=company.id, start_date=date(2027, 5, 1), end_date=date(2027, 5, 14),
                   pay_date=date(2027, 5, 20), frequency="biweekly", status="approved")
    db.add(pp)
    db.flush()
    db.add(Paycheck(employee_id=salaried_employee.id, pay_period_id=pp.id, status="approved",
                    gross_wages=Decimal("1000"), net_pay=Decimal("800")))
    db.commit()
    page = client.get(f"/reports/suta?company_id={company.id}&year=2027&quarter=2").text
    assert "$25,000.00" in page and "2026 figure: no 2027 wage base on file" in page
    page = client.get(f"/reports/suta?company_id={company.id}&year=2026&quarter=2").text
    assert "wage base on file" not in page


def test_tax_settings_page_flags_missing_current_year(client, db):
    db.delete(db.get(TaxYear, 2026))
    db.commit()
    assert "No wage bases on file for 2026" in client.get("/tax-settings/").text


# ── Admin page ──────────────────────────────────────────────────────────────

def test_lists_years_and_prefills_edit(client):
    page = client.get("/tax-settings/").text
    assert "$184,500.00" in page and "$25,000.00" in page
    edit = client.get("/tax-settings/?year=2025").text
    assert 'value="176100.00"' in edit and 'value="28200.00"' in edit


def test_add_a_year_is_audit_logged(client, db):
    r = client.post("/tax-settings/", data={"year": "2027", "ss_wage_base": "$190,200",
                                           "ok_suta_wage_base": "26000"})
    assert r.status_code == 303 and r.headers["location"].endswith("flash=created")
    row = db.get(TaxYear, 2027)
    assert (row.ss_wage_base, row.ok_suta_wage_base) == (Decimal("190200"), Decimal("26000"))
    log = db.query(AuditLog).filter_by(table_name="tax_years", record_id=2027).one()
    assert log.action == "insert" and json.loads(log.new_values)["ss_wage_base"] == "190200.00"


def test_update_a_year_logs_old_and_new(client, db):
    client.post("/tax-settings/", data={"year": "2026", "ss_wage_base": "184500", "ok_suta_wage_base": "25500"})
    assert db.get(TaxYear, 2026).ok_suta_wage_base == Decimal("25500")
    log = db.query(AuditLog).filter_by(table_name="tax_years", record_id=2026).one()
    assert log.action == "update"
    assert json.loads(log.old_values)["ok_suta_wage_base"] == "25000.00"
    assert json.loads(log.new_values)["ok_suta_wage_base"] == "25500.00"


@pytest.mark.parametrize("data, field", [
    ({"year": "1999", "ss_wage_base": "184500", "ok_suta_wage_base": "25000"}, "year"),
    ({"year": "abc", "ss_wage_base": "184500", "ok_suta_wage_base": "25000"}, "year"),
    ({"year": "2027", "ss_wage_base": "1845000", "ok_suta_wage_base": "25000"}, "ss_wage_base"),
    ({"year": "2027", "ss_wage_base": "184500", "ok_suta_wage_base": "0.027"}, "ok_suta_wage_base"),
    ({"year": "2027", "ss_wage_base": "lots", "ok_suta_wage_base": "25000"}, "ss_wage_base"),
])
def test_rejects_implausible_values(client, db, data, field):
    r = client.post("/tax-settings/", data=data)
    assert r.status_code == 422
    assert f'id="{field}"' in r.text and "border-red-400" in r.text
    assert db.get(TaxYear, 2027) is None


# ── Admin only (real auth) ──────────────────────────────────────────────────

def _login(client, username, password):
    assert client.post("/auth/login", data={"username": username, "password": password,
                                            "next": "/"}).status_code == 303


def _token(client):
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/reports/").text).group(1)


def test_preparer_cannot_view_or_change(auth_client, auth_db, preparer_user):
    _login(auth_client, "preparer", "preppass")
    assert auth_client.get("/tax-settings/").status_code == 403
    r = auth_client.post("/tax-settings/", data={"year": "2026", "ss_wage_base": "1000",
                                                 "ok_suta_wage_base": "1000", "csrf_token": _token(auth_client)})
    assert r.status_code == 403
    assert auth_db.get(TaxYear, 2026).ss_wage_base == Decimal("184500")
    assert 'href="/tax-settings/"' not in auth_client.get("/reports/").text


def test_admin_sees_nav_link_and_can_save(auth_client, auth_db, admin_user):
    _login(auth_client, "admin", "secret123")
    assert 'href="/tax-settings/"' in auth_client.get("/reports/").text
    r = auth_client.post("/tax-settings/", data={"year": "2027", "ss_wage_base": "190200",
                                                 "ok_suta_wage_base": "26000", "csrf_token": _token(auth_client)})
    assert r.status_code == 303 and auth_db.get(TaxYear, 2027) is not None


# ── Federal withholding table year ──────────────────────────────────────────

def test_payroll_uses_the_pay_years_federal_table(client, db, company, salaried_employee, pay_period):
    from tax_engine.federal import calc_federal_withholding
    from tax_engine.models import W4Input
    client.post(f"/payroll/{pay_period.id}/calculate")
    pc = db.query(Paycheck).first()
    fed = next(l.amount for l in db.query(PaycheckLine).filter_by(paycheck_id=pc.id)
               if l.description == "Federal Income Tax")
    taxable = Decimal(str(pc.gross_wages)) - Decimal(str(pc.total_deductions))
    w4 = W4Input(filing_status="single")  # no W-4 on file: single default
    t = {y: FederalTable.from_data(DEFAULT_FEDERAL_TABLES[y]) for y in (2025, 2026)}
    assert Decimal(str(fed)) == calc_federal_withholding(taxable, "biweekly", w4, table=t[2026])
    assert Decimal(str(fed)) != calc_federal_withholding(taxable, "biweekly", w4, table=t[2025])


def test_pay_period_warns_when_no_federal_table_for_its_year(client, db, company, pay_period):
    from models.payroll import PayPeriod
    assert "federal withholding tables" not in client.get(f"/payroll/{pay_period.id}").text
    pp = PayPeriod(company_id=company.id, start_date=date(2030, 1, 1), end_date=date(2030, 1, 14),
                   pay_date=date(2030, 1, 20), frequency="biweekly", status="open")
    db.add(pp)
    db.commit()
    page = client.get(f"/payroll/{pp.id}").text
    assert "No 2030 federal withholding tables on file" in page and "uses the 2026 federal withholding tables" in page
    assert 'href="/tax-settings/2030/federal"' in page


# ── Federal tables: lookup, seed and Tax Settings entry ─────────────────────

from models.federal_withholding import FederalWithholdingTable
from services.tax_years import federal_table_for, form_values


def test_federal_lookup_falls_back_and_errors_when_empty(db):
    assert federal_table_for(db, 2026).year == 2026
    assert federal_table_for(db, 2027).year == 2026
    assert federal_table_for(db, 2020).year == 2025
    db.query(FederalWithholdingTable).delete()
    db.commit()
    with pytest.raises(ValueError, match="Tax Settings"):
        federal_table_for(db, 2026)


def test_existing_install_gets_federal_tables_seeded(db):
    # Upgrading: tax_years already has rows, the new federal table is empty.
    db.query(FederalWithholdingTable).delete()
    db.commit()
    seed_tax_years(db)
    assert sorted(y for (y,) in db.query(FederalWithholdingTable.year)) == [2025, 2026]


def _form(data):
    return form_values(data)


def test_federal_page_shows_a_years_tables(client):
    page = client.get("/tax-settings/2026/federal").text
    assert 'name="standard.single.2.at_least" value="19900"' in page
    assert 'name="step2.head_of_household.7.tentative" value="95585.50"' in page
    assert 'name="standard.single.3.rate" value="22"' in page
    assert "starting point" not in page


def test_missing_year_starts_from_the_latest_tables(client):
    page = client.get("/tax-settings/2027/federal").text
    assert "No 2027 tables on file yet" in page and "the 2026 tables as a starting point" in page
    assert 'value="19900"' in page


def test_save_a_new_year_is_used_by_payroll_and_logged(client, db, company, salaried_employee):
    from datetime import date as d
    from models.payroll import PayPeriod
    data = DEFAULT_FEDERAL_TABLES[2026]
    form = _form(data)
    form["standard.single.0.at_least"] = "0"
    r = client.post("/tax-settings/2027/federal", data=form)
    assert r.status_code == 303 and r.headers["location"].endswith("flash=created")
    saved = db.get(FederalWithholdingTable, 2027).data
    assert saved["standard"]["single"][2] == ["19900", "1240.00", "0.12"]
    log = db.query(AuditLog).filter_by(table_name="federal_withholding_tables", record_id=2027).one()
    assert log.action == "insert"
    pp = PayPeriod(company_id=company.id, start_date=d(2027, 1, 1), end_date=d(2027, 1, 14),
                   pay_date=d(2027, 1, 20), frequency="biweekly", status="open")
    db.add(pp)
    db.commit()
    assert "federal withholding tables on file" not in client.get(f"/payroll/{pp.id}").text


def test_typo_is_caught_and_nothing_saved(client, db):
    form = _form(DEFAULT_FEDERAL_TABLES[2026])
    form["standard.single.3.tentative"] = "5880.00"  # published: 5,800.00
    r = client.post("/tax-settings/2026/federal", data=form)
    assert r.status_code == 422
    assert "Expected about $5,800.00 from the row above" in r.text
    assert 'value="5880.00"' in r.text  # the admin's entry is kept for correction
    assert db.get(FederalWithholdingTable, 2026).data["standard"]["single"][3][1] == "5800.00"


@pytest.mark.parametrize("name, value, message", [
    ("step2.single.4.at_least", "lots", "Enter a number."),
    ("standard.married_filing_jointly.5.rate", "320", "Must be between 0 and 100."),
    ("standard.head_of_household.2.at_least", "10000", "Must be more than the row above."),
    ("step2.single.0.at_least", "50", "The first row starts at $0"),
])
def test_rejects_malformed_rows(client, db, name, value, message):
    form = _form(DEFAULT_FEDERAL_TABLES[2026])
    form[name] = value
    r = client.post("/tax-settings/2026/federal", data=form)
    assert r.status_code == 422 and message in r.text


def test_update_logs_old_and_new(client, db):
    form = _form(DEFAULT_FEDERAL_TABLES[2026])
    form["line_1g.other"] = "8700"
    assert client.post("/tax-settings/2026/federal", data=form).status_code == 303
    log = db.query(AuditLog).filter_by(table_name="federal_withholding_tables", record_id=2026).one()
    assert log.action == "update"
    assert json.loads(log.old_values)["line_1g"]["other"] == "8600"
    assert json.loads(log.new_values)["line_1g"]["other"] == "8700"


def test_year_out_of_range_is_404(client):
    assert client.get("/tax-settings/1999/federal").status_code == 404


def test_index_flags_a_year_without_federal_tables(client, db):
    client.post("/tax-settings/", data={"year": "2027", "ss_wage_base": "190200", "ok_suta_wage_base": "26000"})
    page = client.get("/tax-settings/").text
    assert 'href="/tax-settings/2027/federal"' in page and "enter tables" in page


def test_preparer_cannot_view_or_save_federal_tables(auth_client, auth_db, preparer_user):
    _login(auth_client, "preparer", "preppass")
    assert auth_client.get("/tax-settings/2026/federal").status_code == 403
    form = _form(DEFAULT_FEDERAL_TABLES[2026]) | {"line_1g.other": "1", "csrf_token": _token(auth_client)}
    assert auth_client.post("/tax-settings/2026/federal", data=form).status_code == 403
    assert auth_db.get(FederalWithholdingTable, 2026).data["line_1g"]["other"] == "8600"


# ── Oklahoma tables: lookup, seed, payroll and Tax Settings entry ───────────

from models.oklahoma_withholding import OklahomaWithholdingTable
from services.tax_years import ok_form_values, ok_table_for


def test_ok_lookup_falls_back_and_errors_when_empty(db):
    assert ok_table_for(db, 2026).year == 2026
    assert ok_table_for(db, 2027).year == 2026
    assert ok_table_for(db, 2020).year == 2025
    db.query(OklahomaWithholdingTable).delete()
    db.commit()
    with pytest.raises(ValueError, match="Tax Settings"):
        ok_table_for(db, 2026)


def test_existing_install_gets_ok_tables_seeded(db):
    db.query(OklahomaWithholdingTable).delete()
    db.commit()
    seed_tax_years(db)
    assert sorted(y for (y,) in db.query(OklahomaWithholdingTable.year)) == [2025, 2026]


def test_payroll_uses_the_pay_years_ok_table(client, db, company, salaried_employee, pay_period):
    from tax_engine.models import OKWithholdingInput
    from tax_engine.oklahoma import calc_ok_withholding
    client.post(f"/payroll/{pay_period.id}/calculate")
    pc = db.query(Paycheck).first()
    ok_tax = next(l.amount for l in db.query(PaycheckLine).filter_by(paycheck_id=pc.id)
                  if l.description == "Oklahoma Income Tax")
    taxable = Decimal(str(pc.gross_wages)) - Decimal(str(pc.total_deductions))
    election = OKWithholdingInput(filing_status="single", allowances=0)  # none on file
    t = {y: OKTable.from_data(DEFAULT_OKLAHOMA_TABLES[y]) for y in (2025, 2026)}
    assert Decimal(str(ok_tax)) == calc_ok_withholding(taxable, "biweekly", election, table=t[2026])
    assert Decimal(str(ok_tax)) != calc_ok_withholding(taxable, "biweekly", election, table=t[2025])


def test_pay_period_warns_when_no_ok_table_for_its_year(client, db, company):
    from models.payroll import PayPeriod
    pp = PayPeriod(company_id=company.id, start_date=date(2030, 1, 1), end_date=date(2030, 1, 14),
                   pay_date=date(2030, 1, 20), frequency="biweekly", status="open")
    db.add(pp)
    db.commit()
    page = client.get(f"/payroll/{pp.id}").text
    assert "No 2030 Oklahoma withholding tables on file" in page
    assert "uses the 2026 Oklahoma withholding tables" in page
    assert 'href="/tax-settings/2030/oklahoma"' in page


def test_ok_page_shows_a_years_rows_and_blank_spares(client):
    page = client.get("/tax-settings/2026/oklahoma").text
    assert 'name="single.3.at_least" value="13550"' in page
    assert 'name="married.2.tentative" value="57.50"' in page
    assert 'name="single.1.rate" value="2.5"' in page
    assert 'name="single.4.at_least" value=""' in page
    assert "starting point" not in page


def test_ok_missing_year_starts_from_the_latest_tables(client):
    page = client.get("/tax-settings/2027/oklahoma").text
    assert "No 2027 tables on file yet" in page and 'value="13550"' in page


def test_ok_save_accepts_a_different_number_of_rows(client, db, company):
    # 2027 entered with the 2025 layout (7 rows) after 2026's 4: row count is per year.
    from models.payroll import PayPeriod
    r = client.post("/tax-settings/2027/oklahoma", data=ok_form_values(DEFAULT_OKLAHOMA_TABLES[2025]))
    assert r.status_code == 303 and r.headers["location"].endswith("flash=created")
    saved = db.get(OklahomaWithholdingTable, 2027).data
    assert len(saved["single"]) == 7 and saved["married"][6] == ["27100", "307.00", "0.0475"]
    log = db.query(AuditLog).filter_by(table_name="oklahoma_withholding_tables", record_id=2027).one()
    assert log.action == "insert"
    pp = PayPeriod(company_id=company.id, start_date=date(2027, 1, 1), end_date=date(2027, 1, 14),
                   pay_date=date(2027, 1, 20), frequency="biweekly", status="open")
    db.add(pp)
    db.commit()
    assert "Oklahoma withholding tables on file" not in client.get(f"/payroll/{pp.id}").text


def test_ok_typo_is_caught_and_nothing_saved(client, db):
    form = ok_form_values(DEFAULT_OKLAHOMA_TABLES[2026])
    form["married.3.tentative"] = "281.50"  # published: 218.50
    r = client.post("/tax-settings/2026/oklahoma", data=form)
    assert r.status_code == 422 and "Expected about $218.50 from the row above" in r.text
    assert db.get(OklahomaWithholdingTable, 2026).data["married"][3][1] == "218.50"


@pytest.mark.parametrize("change, message", [
    ({"single.2.at_least": "", "single.2.tentative": "", "single.2.rate": ""}, "Fill rows from the top with no gaps."),
    ({f"single.{i}.{c}": "" for i in (1, 2, 3) for c in ("at_least", "tentative", "rate")}, "at least two"),
    ({"married.1.rate": "250"}, "Must be between 0 and 100."),
    ({"allowance": "a thousand"}, "Enter a number."),
])
def test_ok_rejects_malformed_tables(client, db, change, message):
    form = ok_form_values(DEFAULT_OKLAHOMA_TABLES[2026]) | change
    r = client.post("/tax-settings/2026/oklahoma", data=form)
    assert r.status_code == 422 and message in r.text


def test_ok_update_logs_old_and_new(client, db):
    form = ok_form_values(DEFAULT_OKLAHOMA_TABLES[2026]) | {"allowance": "1100"}
    assert client.post("/tax-settings/2026/oklahoma", data=form).status_code == 303
    log = db.query(AuditLog).filter_by(table_name="oklahoma_withholding_tables", record_id=2026).one()
    assert log.action == "update"
    assert json.loads(log.old_values)["allowance"] == "1000"
    assert json.loads(log.new_values)["allowance"] == "1100"


def test_index_links_each_years_ok_tables(client, db):
    client.post("/tax-settings/", data={"year": "2027", "ss_wage_base": "190200", "ok_suta_wage_base": "26000"})
    page = client.get("/tax-settings/").text
    assert 'href="/tax-settings/2026/oklahoma"' in page and 'href="/tax-settings/2027/oklahoma"' in page
    assert "No Oklahoma withholding tables on file for 2026" not in page


def test_preparer_cannot_view_or_save_ok_tables(auth_client, auth_db, preparer_user):
    _login(auth_client, "preparer", "preppass")
    assert auth_client.get("/tax-settings/2026/oklahoma").status_code == 403
    form = ok_form_values(DEFAULT_OKLAHOMA_TABLES[2026]) | {"allowance": "1", "csrf_token": _token(auth_client)}
    assert auth_client.post("/tax-settings/2026/oklahoma", data=form).status_code == 403
    assert auth_db.get(OklahomaWithholdingTable, 2026).data["allowance"] == "1000"
