from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.company import Company, PAY_FREQUENCIES
from models.workers_comp import WorkersCompCode
from models.benefit import BenefitPlan, BENEFIT_TYPES, CONTRIBUTION_TYPES
from routers.auth import AdminUser, get_current_user
from utils.csrf import CsrfProtect
from utils.forms import safe_float

from app_templates import templates

router = APIRouter(prefix="/companies", tags=["companies"],
                   dependencies=[Depends(get_current_user)])


@router.get("/", response_class=HTMLResponse)
def list_companies(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return templates.TemplateResponse(request, "companies/list.html", {
        "companies": companies,
        "active_nav": "companies",
    })


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
    return RedirectResponse(f"/companies/{company.id}?flash=created", status_code=303)


@router.get("/{company_id}", response_class=HTMLResponse)
def get_company(request: Request, company_id: int, db: Session = Depends(get_db), flash: str = ""):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    wc_codes = db.query(WorkersCompCode).order_by(WorkersCompCode.ncci_code).all()
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
def edit_company(request: Request, company_id: int, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return templates.TemplateResponse(request, "companies/form.html", {
        "company": company,
        "pay_frequencies": PAY_FREQUENCIES,
        "errors": {},
        "active_nav": "companies",
    })


@router.post("/{company_id}/edit")
def update_company(
    request: Request,
    _: AdminUser,
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
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

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
    _: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    db: Session = Depends(get_db),
    ncci_code: str = Form(...),
    description: str = Form(...),
    rate_per_100_wages: str = Form(""),
):
    code = WorkersCompCode(
        ncci_code=ncci_code.strip(),
        description=description.strip(),
        rate_per_100_wages=safe_float(rate_per_100_wages, "rate_per_100_wages") if rate_per_100_wages else None,
    )
    db.add(code)
    db.commit()
    return RedirectResponse(f"/companies/{company_id}?flash=wc_added", status_code=303)


# --- Benefit Plans ---

@router.post("/{company_id}/benefits/new")
def create_benefit_plan(
    _: AdminUser,
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
    plan = BenefitPlan(
        company_id=company_id,
        name=name.strip(),
        benefit_type=benefit_type,
        employee_contribution_type=employee_contribution_type,
        employee_contribution_amount=safe_float(employee_contribution_amount or "0", "employee_contribution_amount"),
        employer_match_percent=safe_float(employer_match_percent, "employer_match_percent") if employer_match_percent else None,
        employer_match_cap_percent=safe_float(employer_match_cap_percent, "employer_match_cap_percent") if employer_match_cap_percent else None,
        pre_tax=pre_tax == "on",
    )
    db.add(plan)
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/benefits?flash=added", status_code=303)


@router.get("/{company_id}/benefits", response_class=HTMLResponse)
def list_benefit_plans(
    request: Request, company_id: int, db: Session = Depends(get_db), flash: str = "",
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
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
    request: Request, company_id: int, plan_id: int, db: Session = Depends(get_db),
):
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == plan_id, BenefitPlan.company_id == company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    company = db.query(Company).filter(Company.id == company_id).first()
    return templates.TemplateResponse(request, "companies/benefit_plan_edit.html", {
        "company": company,
        "plan": plan,
        "benefit_types": BENEFIT_TYPES,
        "contribution_types": CONTRIBUTION_TYPES,
        "active_nav": "companies",
    })


@router.post("/{company_id}/benefits/{plan_id}/edit")
def update_benefit_plan(
    _: AdminUser,
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
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == plan_id, BenefitPlan.company_id == company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    plan.name = name.strip()
    plan.benefit_type = benefit_type
    plan.employee_contribution_type = employee_contribution_type
    plan.employee_contribution_amount = safe_float(employee_contribution_amount or "0", "employee_contribution_amount")
    plan.employer_match_percent = safe_float(employer_match_percent, "employer_match_percent") if employer_match_percent else None
    plan.employer_match_cap_percent = safe_float(employer_match_cap_percent, "employer_match_cap_percent") if employer_match_cap_percent else None
    plan.pre_tax = pre_tax == "on"
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/benefits?flash=updated", status_code=303)


@router.post("/{company_id}/benefits/{plan_id}/toggle")
def toggle_benefit_plan(
    _: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
):
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
    request: Request, company_id: int, db: Session = Depends(get_db), flash: str = "",
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    wc_codes = db.query(WorkersCompCode).order_by(WorkersCompCode.ncci_code).all()
    return templates.TemplateResponse(request, "companies/workers_comp_codes.html", {
        "company": company,
        "wc_codes": wc_codes,
        "flash": flash,
        "active_nav": "companies",
    })


@router.get("/{company_id}/wc-codes/{code_id}/edit", response_class=HTMLResponse)
def edit_wc_code(
    request: Request, company_id: int, code_id: int, db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    code = db.query(WorkersCompCode).filter(WorkersCompCode.id == code_id).first()
    if not code:
        raise HTTPException(status_code=404, detail="WC code not found")
    return templates.TemplateResponse(request, "companies/wc_code_edit.html", {
        "company": company,
        "code": code,
        "active_nav": "companies",
    })


@router.post("/{company_id}/wc-codes/{code_id}/edit")
def update_wc_code(
    _: AdminUser,
    _csrf: CsrfProtect,
    company_id: int,
    code_id: int,
    db: Session = Depends(get_db),
    ncci_code: str = Form(...),
    description: str = Form(...),
    rate_per_100_wages: str = Form(""),
):
    code = db.query(WorkersCompCode).filter(WorkersCompCode.id == code_id).first()
    if not code:
        raise HTTPException(status_code=404, detail="WC code not found")
    code.ncci_code = ncci_code.strip()
    code.description = description.strip()
    code.rate_per_100_wages = safe_float(rate_per_100_wages, "rate_per_100_wages") if rate_per_100_wages else None
    db.commit()
    return RedirectResponse(f"/companies/{company_id}/wc-codes?flash=updated", status_code=303)
