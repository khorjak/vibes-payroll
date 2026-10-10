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
from tax_engine.models import PaycheckInput


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
            ss_wage_base=Decimal(ss), suta_wage_base=Decimal(suta), **ytd)).taxes
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
