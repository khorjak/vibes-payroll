from datetime import date
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import false
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models.company import Company
from models.employee import (
    Employee, W4Election, OKWithholdingElection,
    EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, FILING_STATUSES,
)
from models.workers_comp import WorkersCompCode
from models.benefit import BenefitPlan, EmployeeBenefitEnrollment
from models.garnishment import GarnishmentOrder, GARNISHMENT_TYPES
from utils.crypto import encrypt, decrypt
from utils.forms import safe_float
from routers.auth import ActiveCompany, CurrentUser, PreparerUser, get_current_user
from utils.company_scope import (
    accessible_companies,
    assert_company_access,
    get_scoped_employee,
    scope_query,
)
from utils.csrf import CsrfProtect
from services.audit import log_change

from app_templates import templates

router = APIRouter(prefix="/employees", tags=["employees"],
                   dependencies=[Depends(get_current_user)])


def _company_wc_codes(db: Session, company_id) -> list[WorkersCompCode]:
    """WC codes belong to one company -- never list them across companies."""
    if not company_id:
        return []
    return (
        db.query(WorkersCompCode)
        .filter(WorkersCompCode.company_id == company_id)
        .order_by(WorkersCompCode.ncci_code)
        .all()
    )


def _validate_wc_code(db: Session, company_id: int, wc_code_id: str) -> tuple[int | None, str | None]:
    """Resolve a submitted WC code id, rejecting one from a different company."""
    if not wc_code_id:
        return None, None
    code = db.query(WorkersCompCode).filter(WorkersCompCode.id == int(wc_code_id)).first()
    if not code or code.company_id != company_id:
        return None, "Select a workers comp code belonging to this company."
    return code.id, None


@router.get("/", response_class=HTMLResponse)
def list_employees(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    q: str = "",
    status: str = "",
    company_id: str = "",
):
    query = db.query(Employee).options(joinedload(Employee.company))
    if q:
        query = query.filter(
            (Employee.first_name.ilike(f"%{q}%")) |
            (Employee.last_name.ilike(f"%{q}%")) |
            (Employee.department.ilike(f"%{q}%"))
        )
    if status:
        query = query.filter(Employee.status == status)
    # No explicit filter means the active company, not every company.
    if company_id == "all":
        query = scope_query(query, Employee.company_id, current_user, db)
    elif company_id:
        assert_company_access(current_user, int(company_id), db)
        query = query.filter(Employee.company_id == int(company_id))
    elif active_company:
        company_id = str(active_company.id)
        query = query.filter(Employee.company_id == active_company.id)
    else:
        # No accessible company at all -- show nothing rather than everything.
        query = query.filter(false())
    employees = query.order_by(Employee.last_name, Employee.first_name).all()
    companies = accessible_companies(current_user, db)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "employees/_table.html", {
            "employees": employees,
        })

    return templates.TemplateResponse(request, "employees/list.html", {
        "employees": employees,
        "companies": companies,
        "q": q,
        "status_filter": status,
        "company_filter": company_id,
        "statuses": EMPLOYEE_STATUSES,
        "active_nav": "employees",
    })


@router.get("/new", response_class=HTMLResponse)
def new_employee(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(request, "employees/form.html", {
        "employee": None,
        "companies": accessible_companies(current_user, db),
        "selected_company_id": active_company.id if active_company else None,
        "wc_codes": _company_wc_codes(db, active_company.id if active_company else None),
        "employment_types": EMPLOYMENT_TYPES,
        "statuses": EMPLOYEE_STATUSES,
        "errors": {},
        "active_nav": "employees",
    })


@router.get("/wc-code-options", response_class=HTMLResponse)
def wc_code_options(
    request: Request,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    company_id: int = 0,
    selected: int = 0,
):
    """HTMX partial: re-render the WC code <select> options for one company.

    Declared before /{employee_id} so the literal path is not swallowed by the
    int path param. Scoped like any other read -- an out-of-scope company_id
    404s, so this cannot be used to enumerate another tenant's codes.
    """
    if company_id:
        assert_company_access(current_user, company_id, db)
    return templates.TemplateResponse(request, "employees/_wc_options.html", {
        "wc_codes": _company_wc_codes(db, company_id),
        "selected_wc_code_id": selected or None,
    })


@router.post("/new")
def create_employee(
    request: Request,
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    ssn: str = Form(""),
    employment_type: str = Form(...),
    pay_rate: str = Form(...),
    pay_frequency: str = Form(""),
    hire_date: str = Form(""),
    status: str = Form("active"),
    flsa_exempt: str = Form(""),
    department: str = Form(""),
    job_title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form("OK"),
    zip_code: str = Form(""),
    workers_comp_code_id: str = Form(""),
    routing_number: str = Form(""),
    account_number: str = Form(""),
):
    assert_company_access(current_user, company_id, db)

    errors = {}
    if not first_name.strip():
        errors["first_name"] = "First name is required."
    if not last_name.strip():
        errors["last_name"] = "Last name is required."
    if not pay_rate:
        errors["pay_rate"] = "Pay rate is required."
    elif employment_type in ("hourly", "part_time") and safe_float(pay_rate, "pay_rate") < 7.25:
        errors["pay_rate"] = "Pay rate must be at least $7.25/hr (federal minimum wage)."

    wc_code_id, wc_error = _validate_wc_code(db, company_id, workers_comp_code_id)
    if wc_error:
        errors["workers_comp_code_id"] = wc_error

    if errors:
        return templates.TemplateResponse(request, "employees/form.html", {
            "employee": None,
            "companies": accessible_companies(current_user, db),
            "selected_company_id": company_id,
            "wc_codes": _company_wc_codes(db, company_id),
            "employment_types": EMPLOYMENT_TYPES,
            "statuses": EMPLOYEE_STATUSES,
            "errors": errors,
            "active_nav": "employees",
        }, status_code=422)

    employee = Employee(
        company_id=company_id,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        ssn_encrypted=encrypt(ssn.replace("-", "").strip()) if ssn.strip() else None,
        routing_number_encrypted=encrypt(routing_number.strip()) if routing_number.strip() else None,
        account_number_encrypted=encrypt(account_number.strip()) if account_number.strip() else None,
        employment_type=employment_type,
        pay_rate=safe_float(pay_rate, "pay_rate"),
        pay_frequency=pay_frequency or None,
        hire_date=date.fromisoformat(hire_date) if hire_date else None,
        status=status,
        flsa_exempt=(flsa_exempt == "on"),
        department=department.strip() or None,
        job_title=job_title.strip() or None,
        email=email.strip() or None,
        phone=phone.strip() or None,
        address=address.strip() or None,
        city=city.strip() or None,
        state=state.strip() or "OK",
        zip_code=zip_code.strip() or None,
        workers_comp_code_id=wc_code_id,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    log_change(db, "employees", employee.id, "insert",
               changed_by=current_user.username,
               new_values={"first_name": employee.first_name, "last_name": employee.last_name,
                           "employment_type": employee.employment_type, "status": employee.status})
    db.commit()
    return RedirectResponse(f"/employees/{employee.id}?flash=created", status_code=303)


@router.get("/{employee_id}", response_class=HTMLResponse)
def get_employee(
    request: Request,
    current_user: CurrentUser,
    employee_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    employee = get_scoped_employee(
        db, current_user, employee_id,
        joinedload(Employee.company),
        joinedload(Employee.w4_elections),
        joinedload(Employee.ok_withholding_elections),
        joinedload(Employee.benefit_enrollments).joinedload(EmployeeBenefitEnrollment.plan),
        joinedload(Employee.workers_comp_code),
        joinedload(Employee.garnishment_orders),
    )

    ssn_display = None
    if employee.ssn_encrypted:
        raw = decrypt(employee.ssn_encrypted)
        if raw and len(raw) >= 4:
            ssn_display = f"***-**-{raw[-4:]}"

    active_enrollments = [e for e in employee.benefit_enrollments if not e.end_date]
    active_garnishments = [g for g in employee.garnishment_orders if g.active and not g.end_date]

    return templates.TemplateResponse(request, "employees/profile.html", {
        "employee": employee,
        "ssn_display": ssn_display,
        "flash": flash,
        "active_enrollments": active_enrollments,
        "active_garnishments": active_garnishments,
        "active_nav": "employees",
    })


@router.get("/{employee_id}/edit", response_class=HTMLResponse)
def edit_employee(
    request: Request, current_user: CurrentUser, employee_id: int, db: Session = Depends(get_db),
):
    employee = get_scoped_employee(db, current_user, employee_id)
    return templates.TemplateResponse(request, "employees/form.html", {
        "employee": employee,
        "companies": accessible_companies(current_user, db),
        "selected_company_id": employee.company_id,
        "wc_codes": _company_wc_codes(db, employee.company_id),
        "employment_types": EMPLOYMENT_TYPES,
        "statuses": EMPLOYEE_STATUSES,
        "errors": {},
        "active_nav": "employees",
    })


@router.post("/{employee_id}/edit")
def update_employee(
    request: Request,
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    employment_type: str = Form(...),
    pay_rate: str = Form(...),
    pay_frequency: str = Form(""),
    hire_date: str = Form(""),
    termination_date: str = Form(""),
    status: str = Form("active"),
    flsa_exempt: str = Form(""),
    department: str = Form(""),
    job_title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form("OK"),
    zip_code: str = Form(""),
    workers_comp_code_id: str = Form(""),
    routing_number: str = Form(""),
    account_number: str = Form(""),
):
    employee = get_scoped_employee(db, current_user, employee_id)
    # Reassignment must not move an employee into a company the user cannot see.
    assert_company_access(current_user, company_id, db)

    errors = {}
    if employment_type in ("hourly", "part_time") and pay_rate and safe_float(pay_rate, "pay_rate") < 7.25:
        errors["pay_rate"] = "Pay rate must be at least $7.25/hr (federal minimum wage)."

    wc_code_id, wc_error = _validate_wc_code(db, company_id, workers_comp_code_id)
    if wc_error:
        errors["workers_comp_code_id"] = wc_error

    if errors:
        return templates.TemplateResponse(request, "employees/form.html", {
            "employee": employee,
            "companies": accessible_companies(current_user, db),
            "selected_company_id": company_id,
            "wc_codes": _company_wc_codes(db, company_id),
            "employment_types": EMPLOYMENT_TYPES,
            "statuses": EMPLOYEE_STATUSES,
            "errors": errors,
            "active_nav": "employees",
        }, status_code=422)

    employee.company_id = company_id
    employee.first_name = first_name.strip()
    employee.last_name = last_name.strip()
    employee.employment_type = employment_type
    employee.pay_rate = safe_float(pay_rate, "pay_rate")
    employee.pay_frequency = pay_frequency or None
    employee.hire_date = date.fromisoformat(hire_date) if hire_date else None
    employee.termination_date = date.fromisoformat(termination_date) if termination_date else None
    employee.status = status
    employee.flsa_exempt = (flsa_exempt == "on")
    employee.department = department.strip() or None
    employee.job_title = job_title.strip() or None
    employee.email = email.strip() or None
    employee.phone = phone.strip() or None
    employee.address = address.strip() or None
    employee.city = city.strip() or None
    employee.state = state.strip() or "OK"
    employee.zip_code = zip_code.strip() or None
    employee.workers_comp_code_id = wc_code_id
    if routing_number.strip():
        employee.routing_number_encrypted = encrypt(routing_number.strip())
    if account_number.strip():
        employee.account_number_encrypted = encrypt(account_number.strip())
    log_change(db, "employees", employee_id, "update",
               changed_by=current_user.username,
               new_values={"first_name": employee.first_name, "last_name": employee.last_name,
                           "status": employee.status, "pay_rate": str(employee.pay_rate)})
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=updated", status_code=303)


# --- W-4 Elections ---

@router.get("/{employee_id}/w4/new", response_class=HTMLResponse)
def new_w4(
    request: Request, current_user: CurrentUser, employee_id: int, db: Session = Depends(get_db),
):
    employee = get_scoped_employee(db, current_user, employee_id)
    return templates.TemplateResponse(request, "employees/w4_form.html", {
        "employee": employee,
        "filing_statuses": FILING_STATUSES,
        "today": date.today().isoformat(),
        "active_nav": "employees",
    })


@router.post("/{employee_id}/w4/new")
def create_w4(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    effective_date: str = Form(...),
    filing_status: str = Form("single"),
    multiple_jobs: str = Form(""),
    dependents_amount: str = Form("0"),
    other_income: str = Form("0"),
    deductions_amount: str = Form("0"),
    extra_withholding: str = Form("0"),
):
    get_scoped_employee(db, current_user, employee_id)
    election = W4Election(
        employee_id=employee_id,
        effective_date=date.fromisoformat(effective_date),
        filing_status=filing_status,
        multiple_jobs=(multiple_jobs == "on"),
        dependents_amount=safe_float(dependents_amount or "0", "dependents_amount"),
        other_income=safe_float(other_income or "0", "other_income"),
        deductions_amount=safe_float(deductions_amount or "0", "deductions_amount"),
        extra_withholding=safe_float(extra_withholding or "0", "extra_withholding"),
    )
    db.add(election)
    db.flush()
    log_change(db, "w4_elections", election.id, "insert",
               changed_by=current_user.username,
               new_values={"employee_id": employee_id, "filing_status": filing_status,
                           "effective_date": effective_date})
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=w4_updated", status_code=303)


# --- Oklahoma Withholding Elections ---

@router.get("/{employee_id}/ok-withholding/new", response_class=HTMLResponse)
def new_ok_withholding(
    request: Request, current_user: CurrentUser, employee_id: int, db: Session = Depends(get_db),
):
    employee = get_scoped_employee(db, current_user, employee_id)
    return templates.TemplateResponse(request, "employees/ok_form.html", {
        "employee": employee,
        "filing_statuses": ["single", "married"],
        "today": date.today().isoformat(),
        "active_nav": "employees",
    })


@router.post("/{employee_id}/ok-withholding/new")
def create_ok_withholding(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    effective_date: str = Form(...),
    filing_status: str = Form("single"),
    allowances: str = Form("0"),
    extra_withholding: str = Form("0"),
):
    get_scoped_employee(db, current_user, employee_id)
    election = OKWithholdingElection(
        employee_id=employee_id,
        effective_date=date.fromisoformat(effective_date),
        filing_status=filing_status,
        allowances=int(allowances or 0),
        extra_withholding=safe_float(extra_withholding or "0", "extra_withholding"),
    )
    db.add(election)
    db.flush()
    log_change(db, "ok_withholding_elections", election.id, "insert",
               changed_by=current_user.username,
               new_values={"employee_id": employee_id, "filing_status": filing_status,
                           "allowances": allowances, "effective_date": effective_date})
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=ok_updated", status_code=303)


# --- Benefit Enrollments ---

@router.post("/{employee_id}/benefits/enroll")
def enroll_benefit(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    benefit_plan_id: int = Form(...),
    effective_date: str = Form(...),
    employee_override_amount: str = Form(""),
):
    employee = get_scoped_employee(db, current_user, employee_id)
    # A benefit plan belongs to one company -- never enroll across companies.
    plan = db.query(BenefitPlan).filter(
        BenefitPlan.id == benefit_plan_id,
        BenefitPlan.company_id == employee.company_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Benefit plan not found")
    enrollment = EmployeeBenefitEnrollment(
        employee_id=employee_id,
        benefit_plan_id=benefit_plan_id,
        effective_date=date.fromisoformat(effective_date),
        employee_override_amount=safe_float(employee_override_amount, "override_amount") if employee_override_amount else None,
    )
    db.add(enrollment)
    db.flush()
    log_change(db, "employee_benefit_enrollments", enrollment.id, "insert",
               changed_by=current_user.username,
               new_values={"employee_id": employee_id, "benefit_plan_id": benefit_plan_id,
                           "effective_date": effective_date})
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=enrolled", status_code=303)


@router.post("/{employee_id}/benefits/{enrollment_id}/terminate")
def terminate_enrollment(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    enrollment_id: int,
    db: Session = Depends(get_db),
    end_date: str = Form(...),
):
    get_scoped_employee(db, current_user, employee_id)
    enrollment = db.query(EmployeeBenefitEnrollment).filter(
        EmployeeBenefitEnrollment.id == enrollment_id,
        EmployeeBenefitEnrollment.employee_id == employee_id,
    ).first()
    if enrollment:
        enrollment.end_date = date.fromisoformat(end_date)
        log_change(db, "employee_benefit_enrollments", enrollment_id, "update",
                   changed_by=current_user.username,
                   old_values={"end_date": None},
                   new_values={"end_date": end_date})
        db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=enrollment_ended", status_code=303)


# --- Garnishment Orders ---

@router.get("/{employee_id}/garnishments", response_class=HTMLResponse)
def list_garnishments(
    request: Request, current_user: CurrentUser, employee_id: int, db: Session = Depends(get_db),
):
    employee = get_scoped_employee(
        db, current_user, employee_id, joinedload(Employee.garnishment_orders),
    )
    return templates.TemplateResponse(request, "employees/garnishments.html", {
        "employee": employee,
        "garnishment_types": GARNISHMENT_TYPES,
        "today": date.today().isoformat(),
        "active_nav": "employees",
    })


@router.post("/{employee_id}/garnishments/new")
def create_garnishment(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    garnishment_type: str = Form(...),
    payee_name: str = Form(...),
    amount: str = Form("0"),
    percent: str = Form("0"),
    amount_type: str = Form("fixed"),
    max_total: str = Form(""),
    effective_date: str = Form(...),
    case_number: str = Form(""),
    notes: str = Form(""),
):
    get_scoped_employee(db, current_user, employee_id)

    order = GarnishmentOrder(
        employee_id=employee_id,
        garnishment_type=garnishment_type,
        payee_name=payee_name.strip(),
        amount=safe_float(amount or "0", "amount"),
        percent=safe_float(percent or "0", "percent"),
        amount_type=amount_type,
        max_total=safe_float(max_total, "max_total") if max_total else None,
        effective_date=date.fromisoformat(effective_date),
        case_number=case_number.strip() or None,
        notes=notes.strip() or None,
        active=True,
    )
    db.add(order)
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}/garnishments?flash=created", status_code=303)


@router.post("/{employee_id}/garnishments/{order_id}/deactivate")
def deactivate_garnishment(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    employee_id: int,
    order_id: int,
    db: Session = Depends(get_db),
    end_date: str = Form(...),
):
    get_scoped_employee(db, current_user, employee_id)
    order = db.query(GarnishmentOrder).filter(
        GarnishmentOrder.id == order_id,
        GarnishmentOrder.employee_id == employee_id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Garnishment order not found")
    order.active = False
    order.end_date = date.fromisoformat(end_date)
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}/garnishments?flash=deactivated", status_code=303)
