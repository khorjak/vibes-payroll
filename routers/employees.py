from datetime import date
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models.company import Company
from models.employee import (
    Employee, W4Election, OKWithholdingElection,
    EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, FILING_STATUSES,
)
from models.workers_comp import WorkersCompCode
from models.benefit import BenefitPlan, EmployeeBenefitEnrollment
from utils.crypto import encrypt, decrypt
from routers.auth import AdminUser, get_current_user
from utils.csrf import CsrfProtect
from services.audit import log_change

from app_templates import templates

router = APIRouter(prefix="/employees", tags=["employees"],
                   dependencies=[Depends(get_current_user)])


@router.get("/", response_class=HTMLResponse)
def list_employees(
    request: Request,
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
    if company_id:
        query = query.filter(Employee.company_id == int(company_id))
    employees = query.order_by(Employee.last_name, Employee.first_name).all()
    companies = db.query(Company).order_by(Company.name).all()

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
def new_employee(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    wc_codes = db.query(WorkersCompCode).order_by(WorkersCompCode.ncci_code).all()
    return templates.TemplateResponse(request, "employees/form.html", {
        "employee": None,
        "companies": companies,
        "wc_codes": wc_codes,
        "employment_types": EMPLOYMENT_TYPES,
        "statuses": EMPLOYEE_STATUSES,
        "errors": {},
        "active_nav": "employees",
    })


@router.post("/new")
def create_employee(
    request: Request,
    current_user: AdminUser,
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
):
    errors = {}
    if not first_name.strip():
        errors["first_name"] = "First name is required."
    if not last_name.strip():
        errors["last_name"] = "Last name is required."
    if not pay_rate:
        errors["pay_rate"] = "Pay rate is required."

    if errors:
        companies = db.query(Company).order_by(Company.name).all()
        wc_codes = db.query(WorkersCompCode).order_by(WorkersCompCode.ncci_code).all()
        return templates.TemplateResponse(request, "employees/form.html", {
            "employee": None,
            "companies": companies,
            "wc_codes": wc_codes,
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
        employment_type=employment_type,
        pay_rate=float(pay_rate),
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
        workers_comp_code_id=int(workers_comp_code_id) if workers_comp_code_id else None,
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
    employee_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    employee = db.query(Employee).options(
        joinedload(Employee.company),
        joinedload(Employee.w4_elections),
        joinedload(Employee.ok_withholding_elections),
        joinedload(Employee.benefit_enrollments).joinedload(EmployeeBenefitEnrollment.plan),
        joinedload(Employee.workers_comp_code),
    ).filter(Employee.id == employee_id).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    ssn_display = None
    if employee.ssn_encrypted:
        raw = decrypt(employee.ssn_encrypted)
        if raw and len(raw) >= 4:
            ssn_display = f"***-**-{raw[-4:]}"

    active_enrollments = [e for e in employee.benefit_enrollments if not e.end_date]

    return templates.TemplateResponse(request, "employees/profile.html", {
        "employee": employee,
        "ssn_display": ssn_display,
        "flash": flash,
        "active_enrollments": active_enrollments,
        "active_nav": "employees",
    })


@router.get("/{employee_id}/edit", response_class=HTMLResponse)
def edit_employee(request: Request, employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    companies = db.query(Company).order_by(Company.name).all()
    wc_codes = db.query(WorkersCompCode).order_by(WorkersCompCode.ncci_code).all()
    return templates.TemplateResponse(request, "employees/form.html", {
        "employee": employee,
        "companies": companies,
        "wc_codes": wc_codes,
        "employment_types": EMPLOYMENT_TYPES,
        "statuses": EMPLOYEE_STATUSES,
        "errors": {},
        "active_nav": "employees",
    })


@router.post("/{employee_id}/edit")
def update_employee(
    request: Request,
    current_user: AdminUser,
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
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    employee.company_id = company_id
    employee.first_name = first_name.strip()
    employee.last_name = last_name.strip()
    employee.employment_type = employment_type
    employee.pay_rate = float(pay_rate)
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
    employee.workers_comp_code_id = int(workers_comp_code_id) if workers_comp_code_id else None
    log_change(db, "employees", employee_id, "update",
               changed_by=current_user.username,
               new_values={"first_name": employee.first_name, "last_name": employee.last_name,
                           "status": employee.status, "pay_rate": str(employee.pay_rate)})
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=updated", status_code=303)


# --- W-4 Elections ---

@router.get("/{employee_id}/w4/new", response_class=HTMLResponse)
def new_w4(request: Request, employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return templates.TemplateResponse(request, "employees/w4_form.html", {
        "employee": employee,
        "filing_statuses": FILING_STATUSES,
        "today": date.today().isoformat(),
        "active_nav": "employees",
    })


@router.post("/{employee_id}/w4/new")
def create_w4(
    _: AdminUser,
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
    election = W4Election(
        employee_id=employee_id,
        effective_date=date.fromisoformat(effective_date),
        filing_status=filing_status,
        multiple_jobs=(multiple_jobs == "on"),
        dependents_amount=float(dependents_amount or 0),
        other_income=float(other_income or 0),
        deductions_amount=float(deductions_amount or 0),
        extra_withholding=float(extra_withholding or 0),
    )
    db.add(election)
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=w4_updated", status_code=303)


# --- Oklahoma Withholding Elections ---

@router.get("/{employee_id}/ok-withholding/new", response_class=HTMLResponse)
def new_ok_withholding(request: Request, employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return templates.TemplateResponse(request, "employees/ok_form.html", {
        "employee": employee,
        "filing_statuses": ["single", "married"],
        "today": date.today().isoformat(),
        "active_nav": "employees",
    })


@router.post("/{employee_id}/ok-withholding/new")
def create_ok_withholding(
    _: AdminUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    effective_date: str = Form(...),
    filing_status: str = Form("single"),
    allowances: str = Form("0"),
    extra_withholding: str = Form("0"),
):
    election = OKWithholdingElection(
        employee_id=employee_id,
        effective_date=date.fromisoformat(effective_date),
        filing_status=filing_status,
        allowances=int(allowances or 0),
        extra_withholding=float(extra_withholding or 0),
    )
    db.add(election)
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=ok_updated", status_code=303)


# --- Benefit Enrollments ---

@router.post("/{employee_id}/benefits/enroll")
def enroll_benefit(
    _: AdminUser,
    _csrf: CsrfProtect,
    employee_id: int,
    db: Session = Depends(get_db),
    benefit_plan_id: int = Form(...),
    effective_date: str = Form(...),
    employee_override_amount: str = Form(""),
):
    enrollment = EmployeeBenefitEnrollment(
        employee_id=employee_id,
        benefit_plan_id=benefit_plan_id,
        effective_date=date.fromisoformat(effective_date),
        employee_override_amount=float(employee_override_amount) if employee_override_amount else None,
    )
    db.add(enrollment)
    db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=enrolled", status_code=303)


@router.post("/{employee_id}/benefits/{enrollment_id}/terminate")
def terminate_enrollment(
    _: AdminUser,
    _csrf: CsrfProtect,
    employee_id: int,
    enrollment_id: int,
    db: Session = Depends(get_db),
    end_date: str = Form(...),
):
    enrollment = db.query(EmployeeBenefitEnrollment).filter(
        EmployeeBenefitEnrollment.id == enrollment_id,
        EmployeeBenefitEnrollment.employee_id == employee_id,
    ).first()
    if enrollment:
        enrollment.end_date = date.fromisoformat(end_date)
        db.commit()
    return RedirectResponse(f"/employees/{employee_id}?flash=enrollment_ended", status_code=303)
