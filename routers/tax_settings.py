from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app_templates import templates
from database import get_db
from models.federal_withholding import SCHEDULES, STATUSES, FederalWithholdingTable
from models.tax_year import TaxYear
from routers.auth import AdminUser, get_current_user
from services.audit import log_change
from services.tax_years import ROWS_PER_TABLE, federal_table_for, form_values, parse_federal_form
from utils.csrf import CsrfProtect

router = APIRouter(prefix="/tax-settings", tags=["tax-settings"],
                   dependencies=[Depends(get_current_user)])

# Sanity bounds: a typo (an extra digit, a rate typed as a base) must not reach payroll.
_MIN_BASE, _MAX_BASE = Decimal("1000"), Decimal("1000000")


def _missing(have: set[int]) -> list[int]:
    """This year if absent; next year too from October (SSA and the IRS publish in Oct-Dec)."""
    today = date.today()
    wanted = [today.year] + ([today.year + 1] if today.month >= 10 else [])
    return [y for y in wanted if y not in have]


def _page(request: Request, db: Session, form: dict, errors: dict, flash: str = "", status_code: int = 200):
    wage_bases = {y.year: y for y in db.query(TaxYear)}
    federal_years = {y for (y,) in db.query(FederalWithholdingTable.year)}
    return templates.TemplateResponse(request, "tax_settings/index.html", {
        "years": sorted(wage_bases.keys() | federal_years, reverse=True),
        "wage_bases": wage_bases,
        "federal_years": federal_years,
        "missing_wage_bases": _missing(set(wage_bases)),
        "missing_federal": _missing(federal_years),
        "form": form,
        "errors": errors,
        "flash": flash,
        "active_nav": "tax_settings",
    }, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
def tax_settings(request: Request, _: AdminUser, db: Session = Depends(get_db), flash: str = "", year: int = 0):
    row = db.get(TaxYear, year) if year else None
    form = ({"year": row.year, "ss_wage_base": row.ss_wage_base, "ok_suta_wage_base": row.ok_suta_wage_base}
            if row else {"year": year or "", "ss_wage_base": "", "ok_suta_wage_base": ""})
    return _page(request, db, form, {}, flash)


def _base(value: str, errors: dict, field: str) -> Decimal | None:
    try:
        amount = Decimal(value.replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        errors[field] = "Enter a dollar amount."
        return None
    if not _MIN_BASE <= amount <= _MAX_BASE:
        errors[field] = f"Must be between ${_MIN_BASE:,.0f} and ${_MAX_BASE:,.0f}."
        return None
    return amount.quantize(Decimal("0.01"))


@router.post("/")
def save_tax_year(
    request: Request,
    current_user: AdminUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    year: str = Form(""),
    ss_wage_base: str = Form(""),
    ok_suta_wage_base: str = Form(""),
):
    errors: dict = {}
    try:
        tax_year = int(year)
        if not 2000 <= tax_year <= 2100:
            raise ValueError
    except ValueError:
        tax_year = None
        errors["year"] = "Enter a year between 2000 and 2100."
    ss = _base(ss_wage_base, errors, "ss_wage_base")
    suta = _base(ok_suta_wage_base, errors, "ok_suta_wage_base")
    if errors:
        form = {"year": year, "ss_wage_base": ss_wage_base, "ok_suta_wage_base": ok_suta_wage_base}
        return _page(request, db, form, errors, status_code=422)

    row = db.get(TaxYear, tax_year)
    new_values = {"ss_wage_base": str(ss), "ok_suta_wage_base": str(suta)}
    if row is None:
        db.add(TaxYear(year=tax_year, ss_wage_base=ss, ok_suta_wage_base=suta))
        log_change(db, "tax_years", tax_year, "insert", changed_by=current_user.username, new_values=new_values)
        flash = "created"
    else:
        old_values = {"ss_wage_base": str(row.ss_wage_base), "ok_suta_wage_base": str(row.ok_suta_wage_base)}
        row.ss_wage_base, row.ok_suta_wage_base = ss, suta
        log_change(db, "tax_years", tax_year, "update", changed_by=current_user.username,
                   old_values=old_values, new_values=new_values)
        flash = "updated"
    db.commit()
    return RedirectResponse(f"/tax-settings/?flash={flash}", status_code=303)


# ── Federal withholding tables ──────────────────────────────────────────────

def _federal_page(request, year, values, errors, prefilled_from=None, status_code=200):
    return templates.TemplateResponse(request, "tax_settings/federal.html", {
        "year": year, "values": values, "errors": errors, "prefilled_from": prefilled_from,
        "schedules": SCHEDULES, "statuses": STATUSES, "rows": range(ROWS_PER_TABLE),
        "active_nav": "tax_settings",
    }, status_code=status_code)


def _valid_year(year: int) -> None:
    if not 2000 <= year <= 2100:
        raise HTTPException(status_code=404)


@router.get("/{year}/federal", response_class=HTMLResponse)
def federal_tables(request: Request, year: int, _: AdminUser, db: Session = Depends(get_db)):
    _valid_year(year)
    row = db.get(FederalWithholdingTable, year)
    prefilled_from = None
    if row is None:
        # Start from the latest earlier year: the layout and rates rarely change, so the
        # admin replaces amounts instead of typing 150 fields from scratch.
        row = federal_table_for(db, year)
        prefilled_from = row.year
    return _federal_page(request, year, form_values(row.data), {}, prefilled_from)


@router.post("/{year}/federal")
async def save_federal_tables(
    request: Request, year: int, current_user: AdminUser, _csrf: CsrfProtect, db: Session = Depends(get_db),
):
    _valid_year(year)
    data, values, errors = parse_federal_form(await request.form())
    if errors:
        return _federal_page(request, year, values, errors, status_code=422)
    row = db.get(FederalWithholdingTable, year)
    if row is None:
        db.add(FederalWithholdingTable(year=year, data=data))
        log_change(db, "federal_withholding_tables", year, "insert",
                   changed_by=current_user.username, new_values=data)
        flash = "created"
    else:
        log_change(db, "federal_withholding_tables", year, "update",
                   changed_by=current_user.username, old_values=row.data, new_values=data)
        row.data = data
        flash = "updated"
    db.commit()
    return RedirectResponse(f"/tax-settings/?flash={flash}", status_code=303)
