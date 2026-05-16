from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
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

router = APIRouter(prefix="/payroll", tags=["payroll"])
templates = Jinja2Templates(directory="templates")

_FREQUENCIES = ["weekly", "biweekly", "semi_monthly", "monthly"]


@router.get("/", response_class=HTMLResponse)
def list_pay_periods(
    request: Request,
    db: Session = Depends(get_db),
    company_id: str = "",
):
    query = db.query(PayPeriod).options(joinedload(PayPeriod.company))
    if company_id:
        query = query.filter(PayPeriod.company_id == int(company_id))
    periods = query.order_by(PayPeriod.pay_date.desc()).all()
    companies = db.query(Company).order_by(Company.name).all()
    return templates.TemplateResponse(request, "payroll/list.html", {
        "periods": periods,
        "companies": companies,
        "company_filter": company_id,
        "active_nav": "payroll",
    })


@router.get("/new", response_class=HTMLResponse)
def new_pay_period(request: Request, db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.name).all()
    return templates.TemplateResponse(request, "payroll/new.html", {
        "companies": companies,
        "frequencies": _FREQUENCIES,
        "today": date.today().isoformat(),
        "errors": {},
        "active_nav": "payroll",
    })


@router.post("/new")
def create_pay_period(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    pay_date: str = Form(...),
    frequency: str = Form(...),
):
    errors = {}
    if not start_date:
        errors["start_date"] = "Required."
    if not end_date:
        errors["end_date"] = "Required."
    if not pay_date:
        errors["pay_date"] = "Required."

    if errors:
        companies = db.query(Company).order_by(Company.name).all()
        return templates.TemplateResponse(request, "payroll/new.html", {
            "companies": companies,
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
    return RedirectResponse(f"/payroll/{pp.id}", status_code=303)


# ── Paycheck routes (defined BEFORE /{period_id} to avoid route shadowing) ──

@router.get("/paychecks/{paycheck_id}", response_class=HTMLResponse)
def paycheck_detail(
    request: Request,
    paycheck_id: int,
    db: Session = Depends(get_db),
):
    paycheck = (
        db.query(Paycheck)
        .options(
            joinedload(Paycheck.employee),
            joinedload(Paycheck.pay_period).joinedload(PayPeriod.company),
            joinedload(Paycheck.lines),
        )
        .filter(Paycheck.id == paycheck_id)
        .first()
    )
    if not paycheck:
        raise HTTPException(status_code=404, detail="Paycheck not found")

    lines = sorted(paycheck.lines, key=lambda l: l.id)
    return templates.TemplateResponse(request, "payroll/paycheck_detail.html", {
        "paycheck": paycheck,
        "earnings": [l for l in lines if l.line_type == "earning"],
        "deductions": [l for l in lines if l.line_type == "deduction"],
        "employee_taxes": [l for l in lines if l.line_type == "tax"],
        "employer_taxes": [l for l in lines if l.line_type == "employer_tax"],
        "active_nav": "payroll",
    })


@router.post("/paychecks/{paycheck_id}/void")
def void_check(
    paycheck_id: int,
    db: Session = Depends(get_db),
    reason: str = Form(...),
):
    paycheck = db.query(Paycheck).filter(Paycheck.id == paycheck_id).first()
    if not paycheck:
        raise HTTPException(status_code=404, detail="Paycheck not found")
    try:
        void_paycheck(paycheck, reason, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(
        f"/payroll/{paycheck.pay_period_id}?flash=voided", status_code=303
    )


@router.get("/paychecks/{paycheck_id}/pdf")
def paycheck_pdf(
    paycheck_id: int,
    db: Session = Depends(get_db),
):
    paycheck = (
        db.query(Paycheck)
        .options(
            joinedload(Paycheck.employee),
            joinedload(Paycheck.pay_period).joinedload(PayPeriod.company),
            joinedload(Paycheck.lines),
        )
        .filter(Paycheck.id == paycheck_id)
        .first()
    )
    if not paycheck:
        raise HTTPException(status_code=404, detail="Paycheck not found")

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
    period_id: int,
    db: Session = Depends(get_db),
    flash: str = "",
):
    pp = (
        db.query(PayPeriod)
        .options(
            joinedload(PayPeriod.company),
            joinedload(PayPeriod.paychecks).joinedload(Paycheck.employee),
        )
        .filter(PayPeriod.id == period_id)
        .first()
    )
    if not pp:
        raise HTTPException(status_code=404, detail="Pay period not found")

    variance_flags: dict[int, bool] = {}
    if pp.status == "draft":
        for paycheck in pp.paychecks:
            if paycheck.status != "draft":
                continue
            prior = (
                db.query(Paycheck)
                .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
                .filter(
                    Paycheck.employee_id == paycheck.employee_id,
                    Paycheck.status.in_(["approved", "paid"]),
                    PayPeriod.pay_date < pp.pay_date,
                )
                .order_by(PayPeriod.pay_date.desc())
                .first()
            )
            if prior and prior.gross_wages > 0:
                pct = abs(paycheck.gross_wages - prior.gross_wages) / prior.gross_wages
                variance_flags[paycheck.id] = pct > Decimal("0.20")

    return templates.TemplateResponse(request, "payroll/detail.html", {
        "pp": pp,
        "flash": flash,
        "variance_flags": variance_flags,
        "active_nav": "payroll",
    })


@router.get("/{period_id}/timesheets", response_class=HTMLResponse)
def timesheet_grid(
    request: Request,
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = (
        db.query(PayPeriod)
        .options(joinedload(PayPeriod.company))
        .filter(PayPeriod.id == period_id)
        .first()
    )
    if not pp:
        raise HTTPException(status_code=404, detail="Pay period not found")

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
    pp = db.query(PayPeriod).filter(PayPeriod.id == period_id).first()
    if not pp or pp.status not in ("open", "draft"):
        raise HTTPException(status_code=400, detail="Pay period not editable")

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

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
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = (
        db.query(PayPeriod)
        .options(joinedload(PayPeriod.company))
        .filter(PayPeriod.id == period_id)
        .first()
    )
    if not pp:
        raise HTTPException(status_code=404, detail="Pay period not found")
    if pp.status not in ("open", "draft"):
        raise HTTPException(
            status_code=400, detail=f"Cannot calculate: pay period is '{pp.status}'"
        )

    calculate_payroll_run(pp, db)
    return RedirectResponse(f"/payroll/{period_id}?flash=calculated", status_code=303)


@router.post("/{period_id}/approve")
def approve_period(
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = (
        db.query(PayPeriod)
        .options(joinedload(PayPeriod.paychecks))
        .filter(PayPeriod.id == period_id)
        .first()
    )
    if not pp:
        raise HTTPException(status_code=404, detail="Pay period not found")
    try:
        approve_payroll_run(pp, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/payroll/{period_id}?flash=approved", status_code=303)


@router.post("/{period_id}/mark-paid")
def mark_paid_period(
    period_id: int,
    db: Session = Depends(get_db),
):
    pp = (
        db.query(PayPeriod)
        .options(joinedload(PayPeriod.paychecks))
        .filter(PayPeriod.id == period_id)
        .first()
    )
    if not pp:
        raise HTTPException(status_code=404, detail="Pay period not found")
    try:
        mark_period_paid(pp, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/payroll/{period_id}?flash=paid", status_code=303)
