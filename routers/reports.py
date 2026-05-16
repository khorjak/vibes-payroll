import io
import csv
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.company import Company
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck, PaycheckLine
from models.workers_comp import WorkersCompCode

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="templates")

_QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def _sum_line(paychecks: list, description: str) -> Decimal:
    total = Decimal("0")
    for pc in paychecks:
        for line in pc.lines:
            if line.description == description:
                total += Decimal(str(line.amount))
    return total


def _load_paychecks(
    db: Session,
    company_id: int,
    year: int,
    quarter: int = 0,
) -> list:
    q = (
        db.query(Paycheck)
        .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
        .options(
            joinedload(Paycheck.lines),
            joinedload(Paycheck.employee),
            joinedload(Paycheck.pay_period),
        )
        .filter(
            PayPeriod.company_id == company_id,
            Paycheck.status != "voided",
            func.strftime("%Y", PayPeriod.pay_date) == str(year),
        )
    )
    if quarter and quarter in _QUARTER_MONTHS:
        m_start, m_end = _QUARTER_MONTHS[quarter]
        q = q.filter(
            func.strftime("%m", PayPeriod.pay_date) >= f"{m_start:02d}",
            func.strftime("%m", PayPeriod.pay_date) <= f"{m_end:02d}",
        )
    return q.all()


@router.get("/", response_class=HTMLResponse)
def reports_index(request: Request):
    return templates.TemplateResponse(request, "reports/index.html", {
        "active_nav": "reports",
    })


@router.get("/payroll-register", response_class=HTMLResponse)
def payroll_register(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = 0,
    pay_period_id: int = 0,
):
    companies = db.query(Company).order_by(Company.name).all()

    periods = []
    if company_id > 0:
        periods = (
            db.query(PayPeriod)
            .filter(PayPeriod.company_id == company_id)
            .order_by(PayPeriod.pay_date.desc())
            .all()
        )

    paychecks = []
    pay_period = None
    totals = {}

    if pay_period_id:
        pay_period = db.query(PayPeriod).filter(PayPeriod.id == pay_period_id).first()
        paychecks = (
            db.query(Paycheck)
            .options(
                joinedload(Paycheck.employee),
                joinedload(Paycheck.lines),
            )
            .filter(Paycheck.pay_period_id == pay_period_id)
            .order_by(Paycheck.id)
            .all()
        )
        totals = {
            "gross": sum(Decimal(str(pc.gross_wages)) for pc in paychecks),
            "deductions": sum(Decimal(str(pc.total_deductions)) for pc in paychecks),
            "taxes": sum(Decimal(str(pc.total_taxes_withheld)) for pc in paychecks),
            "net": sum(Decimal(str(pc.net_pay)) for pc in paychecks),
        }

    return templates.TemplateResponse(request, "reports/payroll_register.html", {
        "active_nav": "reports",
        "companies": companies,
        "periods": periods,
        "company_id": company_id,
        "pay_period_id": pay_period_id,
        "pay_period": pay_period,
        "paychecks": paychecks,
        "totals": totals,
    })


@router.get("/tax-liability", response_class=HTMLResponse)
def tax_liability(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    companies = db.query(Company).order_by(Company.name).all()
    if not year:
        year = date.today().year

    rows = []
    yearly = {}

    if company_id and year:
        paychecks = _load_paychecks(db, company_id, year)

        by_period: dict[int, list] = {}
        for pc in paychecks:
            by_period.setdefault(pc.pay_period_id, []).append(pc)

        period_ids = sorted(by_period.keys())
        periods_map = {
            pp.id: pp
            for pp in db.query(PayPeriod).filter(PayPeriod.id.in_(period_ids)).all()
        }

        for pid in sorted(period_ids, key=lambda x: periods_map[x].pay_date):
            pcs = by_period[pid]
            pp = periods_map[pid]
            gross = sum(Decimal(str(pc.gross_wages)) for pc in pcs)
            fed = _sum_line(pcs, "Federal Income Tax")
            ok = _sum_line(pcs, "Oklahoma Income Tax")
            ss_emp = _sum_line(pcs, "Social Security (Employee)")
            ss_er = _sum_line(pcs, "Social Security (Employer)")
            med_emp = _sum_line(pcs, "Medicare (Employee)")
            med_er = _sum_line(pcs, "Medicare (Employer)")
            futa = _sum_line(pcs, "FUTA")
            suta = _sum_line(pcs, "SUTA")
            wc = _sum_line(pcs, "Workers Comp")
            total_cost = (
                gross + ss_er + med_er + futa + suta + wc
            )
            rows.append({
                "pay_date": pp.pay_date,
                "employee_count": len(set(pc.employee_id for pc in pcs)),
                "gross": gross,
                "fed": fed,
                "ok": ok,
                "ss_emp": ss_emp,
                "ss_er": ss_er,
                "med_emp": med_emp,
                "med_er": med_er,
                "futa": futa,
                "suta": suta,
                "wc": wc,
                "fica_emp": ss_emp + med_emp,
                "fica_er": ss_er + med_er,
                "total_cost": total_cost,
            })

        def _row_sum(key):
            return sum(r[key] for r in rows)

        yearly = {
            "gross": _row_sum("gross"),
            "fed": _row_sum("fed"),
            "ok": _row_sum("ok"),
            "ss_emp": _row_sum("ss_emp"),
            "ss_er": _row_sum("ss_er"),
            "med_emp": _row_sum("med_emp"),
            "med_er": _row_sum("med_er"),
            "futa": _row_sum("futa"),
            "suta": _row_sum("suta"),
            "wc": _row_sum("wc"),
            "fica_emp": _row_sum("fica_emp"),
            "fica_er": _row_sum("fica_er"),
            "total_cost": _row_sum("total_cost"),
            "employee_count": _row_sum("employee_count"),
        }

    return templates.TemplateResponse(request, "reports/tax_liability.html", {
        "active_nav": "reports",
        "companies": companies,
        "company_id": company_id,
        "year": year,
        "rows": rows,
        "yearly": yearly,
    })


@router.get("/quarterly-941", response_class=HTMLResponse)
def quarterly_941(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
    quarter: int = 0,
):
    companies = db.query(Company).order_by(Company.name).all()
    if not year:
        year = date.today().year

    summary = {}

    if company_id and year and quarter:
        paychecks = _load_paychecks(db, company_id, year, quarter)

        gross = sum(Decimal(str(pc.gross_wages)) for pc in paychecks)
        fed_tax = _sum_line(paychecks, "Federal Income Tax")
        ss_emp = _sum_line(paychecks, "Social Security (Employee)")
        ss_er = _sum_line(paychecks, "Social Security (Employer)")
        med_emp = _sum_line(paychecks, "Medicare (Employee)")
        med_er = _sum_line(paychecks, "Medicare (Employer)")

        ss_wages = (ss_emp / Decimal("0.062")).quantize(Decimal("0.01")) if ss_emp else Decimal("0")
        med_wages = (med_emp / Decimal("0.0145")).quantize(Decimal("0.01")) if med_emp else Decimal("0")

        total_fica = ss_emp + ss_er + med_emp + med_er
        total_liability = fed_tax + total_fica
        employee_count = len(set(pc.employee_id for pc in paychecks))

        summary = {
            "employee_count": employee_count,
            "gross": gross,
            "fed_tax": fed_tax,
            "ss_wages": ss_wages,
            "med_wages": med_wages,
            "ss_emp": ss_emp,
            "ss_er": ss_er,
            "med_emp": med_emp,
            "med_er": med_er,
            "total_fica": total_fica,
            "total_liability": total_liability,
        }

    return templates.TemplateResponse(request, "reports/quarterly_941.html", {
        "active_nav": "reports",
        "companies": companies,
        "company_id": company_id,
        "year": year,
        "quarter": quarter,
        "summary": summary,
    })


@router.get("/workers-comp", response_class=HTMLResponse)
def workers_comp(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    companies = db.query(Company).order_by(Company.name).all()
    if not year:
        year = date.today().year

    rows = []
    totals = {}

    if company_id and year:
        paychecks = _load_paychecks(db, company_id, year)

        employees = (
            db.query(Employee)
            .options(joinedload(Employee.workers_comp_code))
            .filter(Employee.company_id == company_id)
            .all()
        )
        emp_map = {e.id: e for e in employees}

        by_code: dict[Optional[int], dict] = {}
        for pc in paychecks:
            emp = emp_map.get(pc.employee_id)
            code_id = emp.workers_comp_code_id if emp else None
            wcc = emp.workers_comp_code if emp else None

            if code_id not in by_code:
                by_code[code_id] = {
                    "code": wcc,
                    "gross": Decimal("0"),
                }
            by_code[code_id]["gross"] += Decimal(str(pc.gross_wages))

        for code_id, data in by_code.items():
            wcc = data["code"]
            gross = data["gross"]
            rate = Decimal(str(wcc.rate_per_100_wages)) if wcc and wcc.rate_per_100_wages else Decimal("0")
            premium = (gross / Decimal("100") * rate).quantize(Decimal("0.01"))
            rows.append({
                "ncci_code": wcc.ncci_code if wcc else "N/A",
                "description": wcc.description if wcc else "Unclassified",
                "rate": rate,
                "gross": gross,
                "premium": premium,
            })

        rows.sort(key=lambda r: r["ncci_code"])
        totals = {
            "gross": sum(r["gross"] for r in rows),
            "premium": sum(r["premium"] for r in rows),
        }

    return templates.TemplateResponse(request, "reports/workers_comp.html", {
        "active_nav": "reports",
        "companies": companies,
        "company_id": company_id,
        "year": year,
        "rows": rows,
        "totals": totals,
    })


@router.get("/ok-withholding", response_class=HTMLResponse)
def ok_withholding(
    request: Request,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
    quarter: int = 0,
):
    companies = db.query(Company).order_by(Company.name).all()
    if not year:
        year = date.today().year

    rows = []
    grand = {}

    if company_id and year:
        paychecks = _load_paychecks(db, company_id, year, quarter)

        by_month: dict[int, list] = {}
        for pc in paychecks:
            m = pc.pay_period.pay_date.month
            by_month.setdefault(m, []).append(pc)

        for m in sorted(by_month.keys()):
            pcs = by_month[m]
            pre_tax_total = sum(
                sum(
                    Decimal(str(line.amount))
                    for line in pc.lines
                    if line.is_pre_tax and line.line_type == "deduction"
                )
                for pc in pcs
            )
            gross = sum(Decimal(str(pc.gross_wages)) for pc in pcs)
            ok_wages = gross - pre_tax_total
            ok_tax = _sum_line(pcs, "Oklahoma Income Tax")
            rows.append({
                "month": m,
                "month_name": _MONTH_NAMES[m],
                "quarter": (m - 1) // 3 + 1,
                "employee_count": len(set(pc.employee_id for pc in pcs)),
                "ok_wages": ok_wages,
                "ok_tax": ok_tax,
            })

        grand = {
            "employee_count": sum(r["employee_count"] for r in rows),
            "ok_wages": sum(r["ok_wages"] for r in rows),
            "ok_tax": sum(r["ok_tax"] for r in rows),
        }

    return templates.TemplateResponse(request, "reports/ok_withholding.html", {
        "active_nav": "reports",
        "companies": companies,
        "company_id": company_id,
        "year": year,
        "quarter": quarter,
        "rows": rows,
        "grand": grand,
        "month_names": _MONTH_NAMES,
    })


@router.get("/w2-export")
def w2_export(
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    if not year:
        year = date.today().year

    company = db.query(Company).filter(Company.id == company_id).first()
    company_name = company.name if company else "unknown"

    paychecks = _load_paychecks(db, company_id, year)

    by_employee: dict[int, list] = {}
    for pc in paychecks:
        by_employee.setdefault(pc.employee_id, []).append(pc)

    emp_ids = list(by_employee.keys())
    employees = {
        e.id: e
        for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()
    }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee ID", "Last Name", "First Name", "SSN",
        "Box1_FedWages", "Box2_FedTax",
        "Box3_SSWages", "Box4_SSTax",
        "Box5_MedWages", "Box6_MedTax",
        "Box16_StateWages", "Box17_StateTax",
    ])

    for emp_id in sorted(emp_ids):
        emp = employees.get(emp_id)
        if not emp:
            continue
        pcs = by_employee[emp_id]

        gross = sum(Decimal(str(pc.gross_wages)) for pc in pcs)
        deductions = sum(Decimal(str(pc.total_deductions)) for pc in pcs)
        fed_tax = _sum_line(pcs, "Federal Income Tax")
        ss_emp = _sum_line(pcs, "Social Security (Employee)")
        med_emp = _sum_line(pcs, "Medicare (Employee)")
        ok_tax = _sum_line(pcs, "Oklahoma Income Tax")

        box1 = (gross - deductions).quantize(Decimal("0.01"))
        box3 = (ss_emp / Decimal("0.062")).quantize(Decimal("0.01")) if ss_emp else Decimal("0")
        box5 = (med_emp / Decimal("0.0145")).quantize(Decimal("0.01")) if med_emp else Decimal("0")

        ssn_display = "ENCRYPTED" if emp.ssn_encrypted else ""

        writer.writerow([
            emp.id,
            emp.last_name,
            emp.first_name,
            ssn_display,
            box1,
            fed_tax.quantize(Decimal("0.01")),
            box3,
            ss_emp.quantize(Decimal("0.01")),
            box5,
            med_emp.quantize(Decimal("0.01")),
            box1,
            ok_tax.quantize(Decimal("0.01")),
        ])

    safe_name = re.sub(r"[^\w\-]", "_", company_name)
    filename = f"w2_data_{year}_{safe_name}.csv"
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
