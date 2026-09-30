from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.company import Company, PAY_FREQUENCIES
from models.workers_comp import WorkersCompCode
from models.benefit import BenefitPlan, BENEFIT_TYPES, CONTRIBUTION_TYPES
from routers.auth import AdminUser, CurrentUser, get_current_user
from utils.company_scope import (
    accessible_companies,
    assert_company_access,
    get_scoped_company,
    get_scoped_wc_code,
)
from utils.csrf import CsrfProtect
from utils.forms import percent_value, safe_float

from app_templates import templates

router = APIRouter(prefix="/companies", tags=["companies"],
                   dependencies=[Depends(get_current_user)])


@router.get("/", response_class=HTMLResponse)
def list_companies(request: Request, current_user: CurrentUser, db: Session = Depends(get_db)):
    companies = accessible_companies(current_user, db)
    return templates.TemplateResponse(request, "companies/list.html", {
        "companies": companies,
        "active_nav": "companies",
    })


@router.post("/switch")
def switch_company(
    request: Request,
    current_user: CurrentUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    next: str = Form("/"),
):
    """Set the session's active company. Available to every role, not just admin."""
    assert_company_access(current_user, company_id, db)
    request.session["company_id"] = company_id
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    return RedirectResponse(next, status_code=303)


@router.get("/new", response_class=HTMLResponse)
def new_company(request: Request):
    return templates.TemplateResponse(request, "companies/form.html", {
        "company": None,
        "pay_frequencies": PAY_FREQUENCIES,
        "errors": {},
        "active_nav": "companies",
    })


@router.post("/new")
def create_company(
    request: Request,
    _: AdminUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    name: str = Form(...),
    ein: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form("OK"),
    zip_code: str = Form(""),
    pay_frequency: str = Form("biweekly"),
    suta_rate: str = Form(""),
    workers_comp_policy: str = Form(""),
):
    errors = {}
    if not name.strip():
        errors["name"] = "Company name is required."

    if errors:
        return templates.TemplateResponse(request, "companies/form.html", {
            "company": None,
            "pay_frequencies": PAY_FREQUENCIES,
            "errors": errors,
            "active_nav": "companies",
        }, status_code=422)

    company = Company(
        name=name.strip(),
        ein=ein.strip() or None,
        address=address.strip() or None,
        city=city.strip() or None,
        state=state.strip() or "OK",
        zip_code=zip_code.strip() or None,
        pay_frequency=pay_frequency,
        suta_rate=safe_float(suta_rate, "suta_rate") if suta_rate else None,
        workers_comp_policy=workers_comp_policy.strip() or None,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    # Switch to the company just created -- it's almost certainly what you want next.
    request.session["company_id"] = company.id
    return RedirectResponse(f"/companies/{company.id}?flash=created", status_code=303)


@router.get("/{company_id}", response_class=HTMLResponse)
def get_company(
    request: Request,
    current_user: CurrentUser,
    company_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    company = get_scoped_company(db, current_user, company_id)
    wc_codes = (
        db.query(WorkersCompCode)
        .filter(WorkersCompCode.company_id == company_id)
        .order_by(WorkersCompCode.ncci_code)
        .all()
    )
    benefit_plans = db.query(BenefitPlan).filter(BenefitPlan.company_id == company_id).all()
    return templates.TemplateResponse(request, "companies/detail.html", {
        "company": company,
        "wc_codes": wc_codes,
        "benefit_plans": benefit_plans,
        "benefit_types": BENEFIT_TYPES,
        "flash": flash,
        "active_nav": "companies",
    })


@router.get("/{company_id}/edit", response_class=HTMLResponse)
def edit_company(
    request: Request, current_user: CurrentUser, company_id: int, db: Session = Depends(get_db),
):
    company = get_scoped_company(db, current_user, company_id)
    return templates.TemplateResponse(request, "companies/form.html", {
        "company": company,
        "pay_frequencies": PAY_FREQUENCIES,
        "errors": {},
        "active_nav": "companies",
    })


@router.post("/{company_id}/edit")
def update_company(
    request: Request,
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    ein: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form("OK"),
    zip_code: str = Form(""),
    pay_frequency: str = Form("biweekly"),
    suta_rate: str = Form(""),
    workers_comp_policy: str = Form(""),
):
    company = get_scoped_company(db, current_user, company_id)

    company.name = name.strip()
    company.ein = ein.strip() or None
    company.address = address.strip() or None
    company.city = city.strip() or None
    company.state = state.strip() or "OK"
    company.zip_code = zip_code.strip() or None
    company.pay_frequency = pay_frequency
    company.suta_rate = safe_float(suta_rate, "suta_rate") if suta_rate else None
    company.workers_comp_policy = workers_comp_policy.strip() or None
    db.commit()
    return RedirectResponse(f"/companies/{company_id}?flash=updated", status_code=303)


# --- Workers Comp Codes ---

@router.post("/{company_id}/wc-codes/new")
def create_wc_code(
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    db: Session = Depends(get_db),
    ncci_code: str = Form(...),
    description: str = Form(...),
    rate_per_100_wages: str = Form(""),
):
    assert_company_access(current_user, company_id, db)
    code = WorkersCompCode(
        company_id=company_id,
        ncci_code=ncci_code.strip(),
        description=description.strip(),
        rate_per_100_wages=safe_float(rate_per_100_wages, "rate_per_100_wages") if rate_per_100_wages else None,
    )
    db.add(code)
    db.commit()
    return RedirectResponse(f"/companies/{company_id}?flash=wc_added", status_code=303)


# --- Benefit Plans ---

def _plan_numbers(contribution_type: str, amount: str, match: str, cap: str):
    """Parse a benefit plan's numbers; percent values must be 0-100."""
    amount_f = safe_float(amount or "0", "employee_contribution_amount")
    if contribution_type == "percent":
        percent_value(amount_f, "employee_contribution_amount")
    match_f = percent_value(safe_float(match, "employer_match_percent"), "employer_match_percent") if match else None
    cap_f = percent_value(safe_float(cap, "employer_match_cap_percent"), "employer_match_cap_percent") if cap else None
    return amount_f, match_f, cap_f


@router.post("/{company_id}/benefits/new")
def create_benefit_plan(
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    benefit_type: str = Form(...),
    employee_contribution_type: str = Form("fixed"),
    employee_contribution_amount: str = Form("0"),
    employer_match_percent: str = Form(""),
    employer_match_cap_percent: str = Form(""),
    pre_tax: str = Form(""),
):
    assert_company_access(current_user, company_id, db)
    amount, match, cap = _plan_numbers(
        employee_contribution_type, employee_contribution_amount,
        employer_match_percent, employer_match_cap_percent)
    plan = BenefitPlan(
        company_id=company_id,
        name=name.strip(),
        benefit_type=benefit_type,
        employee_contribution_type=employee_contribution_type,
        employee_contribution_amount=amount,
        employer_match_percent=match,
        employer_match_cap_percent=cap,
        pre_tax=pre_tax == "on",
    )
    db.add(plan)
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/benefits?flash=added", status_code=303)


@router.get("/{company_id}/benefits", response_class=HTMLResponse)
def list_benefit_plans(
    request: Request,
    current_user: CurrentUser,
    company_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    company = get_scoped_company(db, current_user, company_id)
    plans = db.query(BenefitPlan).filter(BenefitPlan.company_id == company_id).order_by(BenefitPlan.name).all()
    return templates.TemplateResponse(request, "companies/benefit_plans.html", {
        "company": company,
        "plans": plans,
        "benefit_types": BENEFIT_TYPES,
        "contribution_types": CONTRIBUTION_TYPES,
        "flash": flash,
        "active_nav": "companies",
    })


@router.get("/{company_id}/benefits/{plan_id}/edit", response_class=HTMLResponse)
def edit_benefit_plan(
    request: Request,
    current_user: CurrentUser,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
):
    company = get_scoped_company(db, current_user, company_id)
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == plan_id, BenefitPlan.company_id == company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    return templates.TemplateResponse(request, "companies/benefit_plan_edit.html", {
        "company": company,
        "plan": plan,
        "benefit_types": BENEFIT_TYPES,
        "contribution_types": CONTRIBUTION_TYPES,
        "active_nav": "companies",
    })


@router.post("/{company_id}/benefits/{plan_id}/edit")
def update_benefit_plan(
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    benefit_type: str = Form(...),
    employee_contribution_type: str = Form("fixed"),
    employee_contribution_amount: str = Form("0"),
    employer_match_percent: str = Form(""),
    employer_match_cap_percent: str = Form(""),
    pre_tax: str = Form(""),
):
    assert_company_access(current_user, company_id, db)
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == plan_id, BenefitPlan.company_id == company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    plan.name = name.strip()
    plan.benefit_type = benefit_type
    plan.employee_contribution_type = employee_contribution_type
    plan.employee_contribution_amount, plan.employer_match_percent, plan.employer_match_cap_percent = _plan_numbers(
        employee_contribution_type, employee_contribution_amount,
        employer_match_percent, employer_match_cap_percent)
    plan.pre_tax = pre_tax == "on"
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/benefits?flash=updated", status_code=303)


@router.post("/{company_id}/benefits/{plan_id}/toggle")
def toggle_benefit_plan(
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
):
    assert_company_access(current_user, company_id, db)
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == plan_id, BenefitPlan.company_id == company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    plan.active = not plan.active
    db.commit()
    status = "activated" if plan.active else "deactivated"
    return RedirectResponse(f"/companies/{company_id}/benefits?flash={status}", status_code=303)


# --- Workers Comp Code Management ---

@router.get("/{company_id}/wc-codes", response_class=HTMLResponse)
def list_wc_codes(
    request: Request,
    current_user: CurrentUser,
    company_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    company = get_scoped_company(db, current_user, company_id)
    wc_codes = (
        db.query(WorkersCompCode)
        .filter(WorkersCompCode.company_id == company_id)
        .order_by(WorkersCompCode.ncci_code)
        .all()
    )
    return templates.TemplateResponse(request, "companies/workers_comp_codes.html", {
        "company": company,
        "wc_codes": wc_codes,
        "flash": flash,
        "active_nav": "companies",
    })


@router.get("/{company_id}/wc-codes/{code_id}/edit", response_class=HTMLResponse)
def edit_wc_code(
    request: Request,
    current_user: CurrentUser,
    company_id: int,
    code_id: int,
    db: Session = Depends(get_db),
):
    company = get_scoped_company(db, current_user, company_id)
    code = get_scoped_wc_code(db, current_user, code_id)
    if code.company_id != company_id:
        raise HTTPException(status_code=404, detail="WC code not found")
    return templates.TemplateResponse(request, "companies/wc_code_edit.html", {
        "company": company,
        "code": code,
        "active_nav": "companies",
    })


@router.post("/{company_id}/wc-codes/{code_id}/edit")
def update_wc_code(
    current_user: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    code_id: int,
    db: Session = Depends(get_db),
    ncci_code: str = Form(...),
    description: str = Form(...),
    rate_per_100_wages: str = Form(""),
):
    code = get_scoped_wc_code(db, current_user, code_id)
    if code.company_id != company_id:
        raise HTTPException(status_code=404, detail="WC code not found")
    code.ncci_code = ncci_code.strip()
    code.description = description.strip()
    code.rate_per_100_wages = safe_float(rate_per_100_wages, "rate_per_100_wages") if rate_per_100_wages else None
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/wc-codes?flash=updated", status_code=303)
