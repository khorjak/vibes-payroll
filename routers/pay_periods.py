from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import false
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models.company import Company
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck, Timesheet
from services.payroll_service import (
    calculate_payroll_run,
    approve_payroll_run,
    mark_period_paid,
    void_paycheck,
)
from routers.auth import (
    ActiveCompany, ApproverUser, CurrentUser, PreparerUser, get_current_user,
)
from utils.company_scope import (
    accessible_companies,
    assert_company_access,
    get_scoped_employee,
    get_scoped_paycheck,
    get_scoped_pay_period,
    scope_query,
)
from utils.csrf import CsrfProtect
from utils.forms import safe_float
from services.audit import log_change

from app_templates import templates

router = APIRouter(prefix="/payroll", tags=["payroll"],
                   dependencies=[Depends(get_current_user)])

_FREQUENCIES = ["weekly", "biweekly", "semi_monthly", "monthly"]


@router.get("/", response_class=HTMLResponse)
def list_pay_periods(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: str = "",
):
    query = db.query(PayPeriod).options(joinedload(PayPeriod.company))
    # No explicit filter means the active company, not every company.
    if company_id == "all":
        query = scope_query(query, PayPeriod.company_id, current_user, db)
    elif company_id.isdigit():
        assert_company_access(current_user, int(company_id), db)
        query = query.filter(PayPeriod.company_id == int(company_id))
    elif active_company:
        company_id = str(active_company.id)
        query = query.filter(PayPeriod.company_id == active_company.id)
    else:
        query = query.filter(false())
    periods = query.order_by(PayPeriod.pay_date.desc()).all()
    return templates.TemplateResponse(request, "payroll/list.html", {
        "periods": periods,
        "companies": accessible_companies(current_user, db),
        "company_filter": company_id,
        "active_nav": "payroll",
    })


@router.get("/new", response_class=HTMLResponse)
def new_pay_period(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(request, "payroll/new.html", {
        "companies": accessible_companies(current_user, db),
        "selected_company_id": active_company.id if active_company else None,
        "frequencies": _FREQUENCIES,
        "today": date.today().isoformat(),
        "errors": {},
        "active_nav": "payroll",
    })


@router.post("/new")
def create_pay_period(
    request: Request,
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    pay_date: str = Form(...),
    frequency: str = Form(...),
):
    assert_company_access(current_user, company_id, db)

    errors = {}
    if not start_date:
        errors["start_date"] = "Required."
    if not end_date:
        errors["end_date"] = "Required."
    if not pay_date:
        errors["pay_date"] = "Required."

    if errors:
        return templates.TemplateResponse(request, "payroll/new.html", {
            "companies": accessible_companies(current_user, db),
            "selected_company_id": company_id,
            "frequencies": _FREQUENCIES,
            "today": date.today().isoformat(),
            "errors": errors,
            "active_nav": "payroll",
        }, status_code=422)

    pp = PayPeriod(
        company_id=company_id,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        pay_date=date.fromisoformat(pay_date),
        frequency=frequency,
        status="open",
    )
    db.add(pp)
    db.commit()
    db.refresh(pp)
    log_change(db, "pay_periods", pp.id, "insert",
               changed_by=current_user.username,
               new_values={"start_date": start_date, "end_date": end_date,
                           "pay_date": pay_date, "frequency": frequency})
    db.commit()
    return RedirectResponse(f"/payroll/{pp.id}", status_code=303)


# ── Off-Cycle Payroll (BEFORE /{period_id} to avoid route shadowing) ──────────

def _off_cycle_employees(db: Session, company_id) -> list[Employee]:
    """Active employees of one company -- an off-cycle run must not cross companies."""
    if not company_id:
        return []
    return (
        db.query(Employee)
        .filter(Employee.status == "active", Employee.company_id == company_id)
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )

@router.get("/off-cycle/new", response_class=HTMLResponse)
def new_off_cycle(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
):
    employees = _off_cycle_employees(db, active_company.id if active_company else None)
    return templates.TemplateResponse(request, "payroll/off_cycle.html", {
        "companies": accessible_companies(current_user, db),
        "selected_company_id": active_company.id if active_company else None,
        "employees": employees,
        "frequencies": _FREQUENCIES,
        "today": date.today().isoformat(),
        "errors": {},
        "active_nav": "payroll",
    })


@router.get("/off-cycle/employee-options", response_class=HTMLResponse)
def off_cycle_employee_options(
    request: Request,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    company_id: int = 0,
    selected: int = 0,
):
    """HTMX partial: re-render the employee <select> options for one company.

    Scoped like any other read -- an out-of-scope company_id 404s, so this
    cannot be used to enumerate another tenant's employees.
    """
    if company_id:
        assert_company_access(current_user, company_id, db)
    return templates.TemplateResponse(request, "payroll/_employee_options.html", {
        "employees": _off_cycle_employees(db, company_id),
        "selected_employee_id": selected or None,
    })


@router.post("/off-cycle/new")
def create_off_cycle(
    request: Request,
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    employee_id: int = Form(...),
    pay_date: str = Form(...),
    frequency: str = Form("biweekly"),
    gross_amount: str = Form(...),
    description: str = Form("Off-Cycle Payment"),
):
    assert_company_access(current_user, company_id, db)

    errors = {}
    if not pay_date:
        errors["pay_date"] = "Required."
    if not gross_amount or safe_float(gross_amount, "gross_amount") <= 0:
        errors["gross_amount"] = "Must be greater than zero."

    if errors:
        return templates.TemplateResponse(request, "payroll/off_cycle.html", {
            "companies": accessible_companies(current_user, db),
            "selected_company_id": company_id,
            "employees": _off_cycle_employees(db, company_id),
            "frequencies": _FREQUENCIES,
            "today": date.today().isoformat(),
            "errors": errors,
            "active_nav": "payroll",
        }, status_code=422)

    pay_dt = date.fromisoformat(pay_date)
    pp = PayPeriod(
        company_id=company_id,
        start_date=pay_dt,
        end_date=pay_dt,
        pay_date=pay_dt,
        frequency=frequency,
        status="open",
    )
    db.add(pp)
    db.flush()

    from models.benefit import EmployeeBenefitEnrollment
    from models.garnishment import GarnishmentOrder
    from services.payroll_service import draft_paycheck

    employee = get_scoped_employee(
        db, current_user, employee_id,
        joinedload(Employee.w4_elections),
        joinedload(Employee.ok_withholding_elections),
        joinedload(Employee.benefit_enrollments).joinedload(EmployeeBenefitEnrollment.plan),
        joinedload(Employee.workers_comp_code),
        joinedload(Employee.garnishment_orders),
    )
    # Out of scope already 404'd inside get_scoped_employee. Reaching here with a
    # mismatch means both records are ones this user may legitimately see and the
    # pairing is simply wrong -- an ordinary form mistake, so say so rather than
    # dead-ending on a bare 404.
    if employee.company_id != company_id:
        db.rollback()
        return templates.TemplateResponse(request, "payroll/off_cycle.html", {
            "companies": accessible_companies(current_user, db),
            "selected_company_id": company_id,
            "employees": _off_cycle_employees(db, company_id),
            "frequencies": _FREQUENCIES,
            "today": date.today().isoformat(),
            "errors": {"employee_id": "That employee belongs to a different company."},
            "active_nav": "payroll",
        }, status_code=422)

    gross_val = safe_float(gross_amount, "gross_amount")
    if employee.employment_type != "salaried" and employee.pay_rate:
        regular_hours = gross_val / safe_float(str(employee.pay_rate), "pay_rate")
    else:
        regular_hours = 0

    ts = Timesheet(
        employee_id=employee_id,
        pay_period_id=pp.id,
        regular_hours=regular_hours,
    )
    db.add(ts)
    db.flush()

    # Salaried pay comes from the salary, so the entered amount must override it.
    paycheck = draft_paycheck(
        employee, pp, ts, db,
        gross_override=Decimal(str(gross_val)) if employee.employment_type == "salaried" else None,
        earning_label=description.strip() or None,
    )

    pp.status = "draft"
    log_change(db, "pay_periods", pp.id, "insert",
               changed_by=current_user.username,
               new_values={"type": "off-cycle", "employee_id": employee_id,
                           "pay_date": pay_date})
    db.commit()
    return RedirectResponse(f"/payroll/{pp.id}?flash=off_cycle_created", status_code=303)


# ── Paycheck routes (defined BEFORE /{period_id} to avoid route shadowing) ──

@router.get("/paychecks/{paycheck_id}", response_class=HTMLResponse)
def paycheck_detail(
    request: Request,
    current_user: CurrentUser,
    paycheck_id: int,
    db: Session = Depends(get_db),
):
    paycheck = get_scoped_paycheck(
        db, current_user, paycheck_id,
        joinedload(Paycheck.employee),
        joinedload(Paycheck.pay_period).joinedload(PayPeriod.company),
        joinedload(Paycheck.lines),
    )

    lines = sorted(paycheck.lines, key=lambda l: l.id)
    return templates.TemplateResponse(request, "payroll/paycheck_detail.html", {
        "paycheck": paycheck,
        "earnings": [l for l in lines if l.line_type == "earning"],
        "deductions": [l for l in lines if l.line_type == "deduction"],
        "employee_taxes": [l for l in lines if l.line_type == "tax"],
        "employer_taxes": [l for l in lines if l.line_type == "employer_tax"],
        "employer_contributions": [l for l in lines if l.line_type == "employer_contribution"],
        "active_nav": "payroll",
    })


@router.post("/paychecks/{paycheck_id}/void")
def void_check(
    current_user: ApproverUser,
    _csrf: CsrfProtect,
    paycheck_id: int,
    db: Session = Depends(get_db),
    reason: str = Form(...),
):
    paycheck = get_scoped_paycheck(db, current_user, paycheck_id)
    period_id = paycheck.pay_period_id
    try:
        void_paycheck(paycheck, reason, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_change(db, "paychecks", paycheck_id, "update",
               changed_by=current_user.username,
               old_values={"status": "approved"},
               new_values={"status": "voided", "void_reason": reason})
    db.commit()
    return RedirectResponse(f"/payroll/{period_id}?flash=voided", status_code=303)


@router.get("/paychecks/{paycheck_id}/pdf")
def paycheck_pdf(
    current_user: CurrentUser,
    paycheck_id: int,
    db: Session = Depends(get_db),
):
    paycheck = get_scoped_paycheck(
        db, current_user, paycheck_id,
        joinedload(Paycheck.employee),
        joinedload(Paycheck.pay_period).joinedload(PayPeriod.company),
        joinedload(Paycheck.lines),
    )

    try:
        from weasyprint import HTML as WeasyHTML
    except OSError:
        raise HTTPException(
            status_code=503,
            detail="PDF generation unavailable: GTK runtime not installed. "
                   "See https://doc.courtbouillon.org/weasyprint/stable/first_steps.html",
        )

    lines = sorted(paycheck.lines, key=lambda l: l.id)
    html_str = templates.env.get_template("payroll/paystub.html").render(
        paycheck=paycheck,
        earnings=[l for l in lines if l.line_type == "earning"],
        deductions=[l for l in lines if l.line_type == "deduction"],
        employee_taxes=[l for l in lines if l.line_type == "tax"],
        employer_taxes=[l for l in lines if l.line_type == "employer_tax"],
        employer_contributions=[l for l in lines if l.line_type == "employer_contribution"],
    )
    pdf_bytes = WeasyHTML(string=html_str).write_pdf()

    emp = paycheck.employee
    pay_date = paycheck.pay_period.pay_date.strftime("%Y-%m-%d")
    filename = f"paystub_{emp.last_name}_{emp.first_name}_{pay_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ── Pay period routes ──

@router.get("/{period_id}", response_class=HTMLResponse)
def pay_period_detail(
    request: Request,
    current_user: CurrentUser,
    period_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    pp = get_scoped_pay_period(
        db, current_user, period_id,
        joinedload(PayPeriod.company),
        joinedload(PayPeriod.paychecks).joinedload(Paycheck.employee),
    )

    variance_flags: dict[int, bool] = {}
    if pp.status == "draft":
        draft_checks = [pc for pc in pp.paychecks if pc.status == "draft"]
        draft_emp_ids = [pc.employee_id for pc in draft_checks]
        if draft_emp_ids:
            from sqlalchemy import func as sa_func, and_
            latest_date_sq = (
                db.query(
                    Paycheck.employee_id,
                    sa_func.max(PayPeriod.pay_date).label("max_date"),
                )
                .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
                .filter(
                    Paycheck.employee_id.in_(draft_emp_ids),
                    Paycheck.status.in_(["approved", "paid"]),
                    PayPeriod.pay_date < pp.pay_date,
                )
                .group_by(Paycheck.employee_id)
                .subquery()
            )
            priors = (
                db.query(Paycheck)
                .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
                .join(latest_date_sq, and_(
                    Paycheck.employee_id == latest_date_sq.c.employee_id,
                    PayPeriod.pay_date == latest_date_sq.c.max_date,
                ))
                .filter(Paycheck.status.in_(["approved", "paid"]))
                .all()
            )
            prior_map = {pc.employee_id: pc for pc in priors}
            for paycheck in draft_checks:
                prior = prior_map.get(paycheck.employee_id)
                if prior and prior.gross_wages > 0:
                    pct = abs(paycheck.gross_wages - prior.gross_wages) / prior.gross_wages
                    variance_flags[paycheck.id] = pct > Decimal("0.20")

    terminated_needing_final = []
    terminated_employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == pp.company_id,
            Employee.status == "terminated",
            Employee.termination_date.isnot(None),
            Employee.termination_date <= pp.pay_date,
        )
        .all()
    )
    paid_emp_ids = {pc.employee_id for pc in pp.paychecks}
    candidates = [emp for emp in terminated_employees if emp.id not in paid_emp_ids]
    if candidates:
        candidate_ids = [emp.id for emp in candidates]
        has_final_ids = set(
            row[0] for row in db.query(Paycheck.employee_id)
            .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
            .join(Employee, Paycheck.employee_id == Employee.id)
            .filter(
                Paycheck.employee_id.in_(candidate_ids),
                Paycheck.status.in_(["approved", "paid"]),
                PayPeriod.pay_date >= Employee.termination_date,
            )
            .distinct()
            .all()
        )
        terminated_needing_final = [emp for emp in candidates if emp.id not in has_final_ids]

    return templates.TemplateResponse(request, "payroll/detail.html", {
        "pp": pp,
        "flash": flash,
        "variance_flags": variance_flags,
        "terminated_needing_final": terminated_needing_final,
        "active_nav": "payroll",
    })


@router.get("/{period_id}/timesheets", response_class=HTMLResponse)
def timesheet_grid(
    request: Request,
    current_user: CurrentUser,
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = get_scoped_pay_period(db, current_user, period_id, joinedload(PayPeriod.company))

    employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == pp.company_id,
            Employee.status == "active",
            Employee.employment_type.in_(["hourly", "part_time"]),
        )
        .order_by(Employee.last_name, Employee.first_name)
        .all()
    )

    timesheets = {
        ts.employee_id: ts
        for ts in db.query(Timesheet).filter(
            Timesheet.pay_period_id == period_id
        ).all()
    }

    return templates.TemplateResponse(request, "payroll/timesheets.html", {
        "pp": pp,
        "employees": employees,
        "timesheets": timesheets,
        "active_nav": "payroll",
    })


@router.post("/{period_id}/timesheets/{employee_id}")
def save_timesheet_row(
    request: Request,
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    period_id: int,
    employee_id: int,
    db: Session = Depends(get_db),
    regular_hours: str = Form("0"),
    overtime_hours: str = Form("0"),
    double_time_hours: str = Form("0"),
    pto_hours: str = Form("0"),
    sick_hours: str = Form("0"),
    holiday_hours: str = Form("0"),
):
    pp = get_scoped_pay_period(db, current_user, period_id)
    if pp.status not in ("open", "draft"):
        raise HTTPException(status_code=400, detail="Pay period not editable")

    employee = get_scoped_employee(db, current_user, employee_id)
    # Out of scope already 404'd above. A mismatch here is an in-scope pairing
    # error -- 422 so the caller can tell it apart from a missing record.
    if employee.company_id != pp.company_id:
        raise HTTPException(
            status_code=422,
            detail="That employee belongs to a different company than this pay period.",
        )

    def _h(s: str) -> float:
        try:
            return max(0.0, float(s or 0))
        except ValueError:
            return 0.0

    ts = db.query(Timesheet).filter(
        Timesheet.employee_id == employee_id,
        Timesheet.pay_period_id == period_id,
    ).first()
    if ts is None:
        ts = Timesheet(employee_id=employee_id, pay_period_id=period_id)
        db.add(ts)

    ts.regular_hours = _h(regular_hours)
    ts.overtime_hours = _h(overtime_hours)
    ts.double_time_hours = _h(double_time_hours)
    ts.pto_hours = _h(pto_hours)
    ts.sick_hours = _h(sick_hours)
    ts.holiday_hours = _h(holiday_hours)
    db.commit()
    db.refresh(ts)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "payroll/_timesheet_row.html", {
            "pp": pp,
            "employee": employee,
            "ts": ts,
            "saved": True,
        })

    return RedirectResponse(f"/payroll/{period_id}/timesheets", status_code=303)


@router.post("/{period_id}/calculate")
def calculate_draft(
    current_user: PreparerUser,
    _csrf: CsrfProtect,
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = get_scoped_pay_period(db, current_user, period_id, joinedload(PayPeriod.company))
    if pp.status not in ("open", "draft"):
        raise HTTPException(
            status_code=400, detail=f"Cannot calculate: pay period is '{pp.status}'"
        )

    calculate_payroll_run(pp, db)
    return RedirectResponse(f"/payroll/{period_id}?flash=calculated", status_code=303)


@router.post("/{period_id}/approve")
def approve_period(
    current_user: ApproverUser,
    _csrf: CsrfProtect,
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = get_scoped_pay_period(db, current_user, period_id, joinedload(PayPeriod.paychecks))
    try:
        approve_payroll_run(pp, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_change(db, "pay_periods", period_id, "update",
               changed_by=current_user.username,
               old_values={"status": "draft"},
               new_values={"status": "approved"})
    for paycheck in pp.paychecks:
        if paycheck.status == "approved":
            log_change(db, "paychecks", paycheck.id, "update",
                       changed_by=current_user.username,
                       old_values={"status": "draft"},
                       new_values={"status": "approved"})
    db.commit()
    return RedirectResponse(f"/payroll/{period_id}?flash=approved", status_code=303)


@router.post("/{period_id}/mark-paid")
def mark_paid_period(
    current_user: ApproverUser,
    _csrf: CsrfProtect,
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = get_scoped_pay_period(db, current_user, period_id, joinedload(PayPeriod.paychecks))
    try:
        mark_period_paid(pp, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/payroll/{period_id}?flash=paid", status_code=303)


