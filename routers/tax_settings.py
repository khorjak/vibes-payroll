from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app_templates import templates
from database import get_db
from models.tax_year import TaxYear
from routers.auth import AdminUser, get_current_user
from services.audit import log_change
from utils.csrf import CsrfProtect

router = APIRouter(prefix="/tax-settings", tags=["tax-settings"],
                   dependencies=[Depends(get_current_user)])

# Sanity bounds: a typo (an extra digit, a rate typed as a base) must not reach payroll.
_MIN_BASE, _MAX_BASE = Decimal("1000"), Decimal("1000000")


def _missing_years(years: list[TaxYear]) -> list[int]:
    """This year if absent; next year too once SSA has announced it (October)."""
    have = {y.year for y in years}
    today = date.today()
    wanted = [today.year] + ([today.year + 1] if today.month >= 10 else [])
    return [y for y in wanted if y not in have]


def _page(request: Request, db: Session, form: dict, errors: dict, flash: str = "", status_code: int = 200):
    years = db.query(TaxYear).order_by(TaxYear.year.desc()).all()
    return templates.TemplateResponse(request, "tax_settings/index.html", {
        "years": years,
        "missing_years": _missing_years(years),
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
