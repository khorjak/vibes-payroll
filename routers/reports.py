import io
import csv
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.company import Company
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck, PaycheckLine, ClientLiability
from models.user import User
from models.workers_comp import WorkersCompCode
from routers.auth import ActiveCompany, CurrentUser, get_current_user
from utils.company_scope import (
    accessible_companies,
    assert_company_access,
    get_scoped_pay_period,
    resolve_company_ids,
)
from app_templates import templates

router = APIRouter(prefix="/reports", tags=["reports"],
                   dependencies=[Depends(get_current_user)])

# company_id sentinel values on report routes:
#   0  -> unset, prompt the user
#  -1  -> every company the user may see (consolidated)
CONSOLIDATED = -1

_QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def _sum_lines(paychecks: list) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for pc in paychecks:
        for line in pc.lines:
            totals[line.description] = totals.get(line.description, Decimal("0")) + Decimal(str(line.amount))
    return totals


def _sum_line(paychecks: list, description: str) -> Decimal:
    total = Decimal("0")
    for pc in paychecks:
        for line in pc.lines:
            if line.description == description:
                total += Decimal(str(line.amount))
    return total


def _load_paychecks(
    db: Session,
    company_ids: list[int],
    year: int,
    quarter: int = 0,
) -> list:
    if not company_ids:
        return []
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)
    q = (
        db.query(Paycheck)
        .join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
        .options(
            joinedload(Paycheck.lines),
            joinedload(Paycheck.employee),
            joinedload(Paycheck.pay_period),
        )
        .filter(
            PayPeriod.company_id.in_(company_ids),
            Paycheck.status != "voided",
            PayPeriod.pay_date >= year_start,
            PayPeriod.pay_date < year_end,
        )
    )
    if quarter and quarter in _QUARTER_MONTHS:
        m_start, m_end = _QUARTER_MONTHS[quarter]
        q_start = date(year, m_start, 1)
        q_end = date(year, m_end + 1, 1) if m_end < 12 else date(year + 1, 1, 1)
        q = q.filter(
            PayPeriod.pay_date >= q_start,
            PayPeriod.pay_date < q_end,
        )
    return q.all()


def _report_scope(
    user: User, db: Session, company_id: int, *, allow_consolidated: bool,
) -> tuple[list[int], Optional[str]]:
    """Resolve a report's company_id param into concrete ids.

    Returns (company_ids, error). An empty id list means "nothing selected yet" --
    the caller renders the prompt state rather than data.
    """
    if company_id == CONSOLIDATED:
        if not allow_consolidated:
            return [], (
                "This report is filed per EIN and must be run for one company at a time."
            )
        return resolve_company_ids(user, db), None
    if company_id > 0:
        assert_company_access(user, company_id, db)
        return [company_id], None
    return [], None


def _company_map(db: Session, company_ids: list[int]) -> dict[int, Company]:
    if not company_ids:
        return {}
    return {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    }


def _group_by_company(paychecks: list) -> dict[int, list]:
    grouped: dict[int, list] = {}
    for pc in paychecks:
        grouped.setdefault(pc.pay_period.company_id, []).append(pc)
    return grouped


@router.get("/", response_class=HTMLResponse)
def reports_index(request: Request):
    return templates.TemplateResponse(request, "reports/index.html", {
        "active_nav": "reports",
    })


@router.get("/payroll-register", response_class=HTMLResponse)
def payroll_register(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    pay_period_id: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )

    periods = []
    if company_ids:
        periods = (
            db.query(PayPeriod)
            .options(joinedload(PayPeriod.company))
            .filter(PayPeriod.company_id.in_(company_ids))
            .order_by(PayPeriod.pay_date.desc())
            .all()
        )

    paychecks = []
    pay_period = None
    totals = {}

    if pay_period_id:
        # Scoped lookup: a period id from another tenant must 404, not render.
        pay_period = get_scoped_pay_period(
            db, current_user, pay_period_id, joinedload(PayPeriod.company),
        )
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
        "companies": accessible_companies(current_user, db),
        "periods": periods,
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "pay_period_id": pay_period_id,
        "pay_period": pay_period,
        "paychecks": paychecks,
        "totals": totals,
    })


_TAX_LIABILITY_KEYS = [
    "gross", "fed", "ok", "ss_emp", "ss_er", "med_emp", "med_er",
    "futa", "suta", "wc", "fica_emp", "fica_er", "total_cost", "employee_count",
]


def _tax_liability_rows(db: Session, paychecks: list) -> list[dict]:
    by_period: dict[int, list] = {}
    for pc in paychecks:
        by_period.setdefault(pc.pay_period_id, []).append(pc)

    period_ids = sorted(by_period.keys())
    if not period_ids:
        return []
    periods_map = {
        pp.id: pp
        for pp in db.query(PayPeriod).filter(PayPeriod.id.in_(period_ids)).all()
    }

    rows = []
    for pid in sorted(period_ids, key=lambda x: periods_map[x].pay_date):
        pcs = by_period[pid]
        pp = periods_map[pid]
        gross = sum(Decimal(str(pc.gross_wages)) for pc in pcs)
        s = _sum_lines(pcs)
        zero = Decimal("0")
        fed = s.get("Federal Income Tax", zero)
        ok = s.get("Oklahoma Income Tax", zero)
        ss_emp = s.get("Social Security (Employee)", zero)
        ss_er = s.get("Social Security (Employer)", zero)
        med_emp = s.get("Medicare (Employee)", zero)
        med_er = s.get("Medicare (Employer)", zero)
        futa = s.get("FUTA", zero)
        suta = s.get("SUTA", zero)
        wc = s.get("Workers Comp", zero)
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
            "total_cost": gross + ss_er + med_er + futa + suta + wc,
        })
    return rows


def _totals(rows: list[dict], keys: list[str]) -> dict:
    return {k: sum(r[k] for r in rows) for k in keys}


@router.get("/tax-liability", response_class=HTMLResponse)
def tax_liability(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )
    if not year:
        year = date.today().year

    rows = []
    groups = []
    yearly = {}

    if company_ids and year:
        paychecks = _load_paychecks(db, company_ids, year)

        if company_id == CONSOLIDATED:
            # Build per-company groups FIRST, then derive the flat view by
            # summing them -- aggregating the whole set a second time would
            # repeat every PayPeriod lookup. Per-company subtotals matter:
            # one undifferentiated total across unrelated EINs is
            # indistinguishable from a single company's figures.
            company_map = _company_map(db, company_ids)
            for cid, pcs in _group_by_company(paychecks).items():
                group_rows = _tax_liability_rows(db, pcs)
                groups.append({
                    "company": company_map.get(cid),
                    "rows": group_rows,
                    "totals": _totals(group_rows, _TAX_LIABILITY_KEYS),
                })
            groups.sort(key=lambda g: g["company"].name if g["company"] else "")
            rows = [r for g in groups for r in g["rows"]]
            rows.sort(key=lambda r: r["pay_date"])
            yearly = _totals([g["totals"] for g in groups], _TAX_LIABILITY_KEYS) if groups else {}
        else:
            rows = _tax_liability_rows(db, paychecks)
            yearly = _totals(rows, _TAX_LIABILITY_KEYS) if rows else {}

    return templates.TemplateResponse(request, "reports/tax_liability.html", {
        "active_nav": "reports",
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "groups": groups,
        "year": year,
        "rows": rows,
        "yearly": yearly,
    })


@router.get("/quarterly-941", response_class=HTMLResponse)
def quarterly_941(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
    quarter: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    # Form 941 is filed per EIN -- consolidating would reconcile to no real return.
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=False,
    )
    if not year:
        year = date.today().year

    summary = {}

    if company_ids and year and quarter:
        paychecks = _load_paychecks(db, company_ids, year, quarter)

        gross = sum(Decimal(str(pc.gross_wages)) for pc in paychecks)
        s = _sum_lines(paychecks)
        zero = Decimal("0")
        fed_tax = s.get("Federal Income Tax", zero)
        ss_emp = s.get("Social Security (Employee)", zero)
        ss_er = s.get("Social Security (Employer)", zero)
        med_emp = s.get("Medicare (Employee)", zero)
        med_er = s.get("Medicare (Employer)", zero)

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
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": False,
        "allow_consolidated": False,
        "error": error,
        "year": year,
        "quarter": quarter,
        "summary": summary,
    })


def _workers_comp_rows(db: Session, paychecks: list, company_ids: list[int]) -> list[dict]:
    if not paychecks:
        return []
    employees = (
        db.query(Employee)
        .options(joinedload(Employee.workers_comp_code))
        .filter(Employee.company_id.in_(company_ids))
        .all()
    )
    emp_map = {e.id: e for e in employees}

    by_code: dict[Optional[int], dict] = {}
    for pc in paychecks:
        emp = emp_map.get(pc.employee_id)
        code_id = emp.workers_comp_code_id if emp else None
        wcc = emp.workers_comp_code if emp else None

        if code_id not in by_code:
            by_code[code_id] = {"code": wcc, "gross": Decimal("0")}
        by_code[code_id]["gross"] += Decimal(str(pc.gross_wages))

    rows = []
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
    return rows


@router.get("/workers-comp", response_class=HTMLResponse)
def workers_comp(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )
    if not year:
        year = date.today().year

    rows = []
    groups = []
    totals = {}

    if company_ids and year:
        paychecks = _load_paychecks(db, company_ids, year)
        if company_id == CONSOLIDATED:
            # WC rates differ per company policy -- never merge into one rate
            # table. Groups first; the flat view is derived from them.
            company_map = _company_map(db, company_ids)
            for cid, pcs in _group_by_company(paychecks).items():
                group_rows = _workers_comp_rows(db, pcs, [cid])
                groups.append({
                    "company": company_map.get(cid),
                    "rows": group_rows,
                    "totals": {
                        "gross": sum(r["gross"] for r in group_rows),
                        "premium": sum(r["premium"] for r in group_rows),
                    },
                })
            groups.sort(key=lambda g: g["company"].name if g["company"] else "")
            rows = [r for g in groups for r in g["rows"]]
            totals = {
                "gross": sum(g["totals"]["gross"] for g in groups),
                "premium": sum(g["totals"]["premium"] for g in groups),
            }
        else:
            rows = _workers_comp_rows(db, paychecks, company_ids)
            totals = {
                "gross": sum(r["gross"] for r in rows),
                "premium": sum(r["premium"] for r in rows),
            }

    return templates.TemplateResponse(request, "reports/workers_comp.html", {
        "active_nav": "reports",
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "groups": groups,
        "year": year,
        "rows": rows,
        "totals": totals,
    })


@router.get("/ok-withholding", response_class=HTMLResponse)
def ok_withholding(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
    quarter: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    # OK withholding is remitted per EIN -- one company at a time.
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=False,
    )
    if not year:
        year = date.today().year

    rows = []
    grand = {}

    if company_ids and year:
        paychecks = _load_paychecks(db, company_ids, year, quarter)

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
            ok_tax = _sum_lines(pcs).get("Oklahoma Income Tax", Decimal("0"))
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
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": False,
        "allow_consolidated": False,
        "error": error,
        "year": year,
        "quarter": quarter,
        "rows": rows,
        "grand": grand,
        "month_names": _MONTH_NAMES,
    })


@router.get("/w2-export")
def w2_export(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    if not year:
        year = date.today().year

    # W-2s are issued per EIN. A consolidated export would produce forms that
    # belong to no single employer, so refuse rather than silently merge.
    if company_id == CONSOLIDATED:
        raise HTTPException(
            status_code=400,
            detail="W-2 data is filed per EIN and must be exported one company at a time.",
        )
    if company_id <= 0:
        raise HTTPException(status_code=400, detail="Select a company to export.")
    assert_company_access(current_user, company_id, db)

    company = db.query(Company).filter(Company.id == company_id).first()
    company_name = company.name if company else "unknown"

    paychecks = _load_paychecks(db, [company_id], year)

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
        s = _sum_lines(pcs)
        zero = Decimal("0")
        fed_tax = s.get("Federal Income Tax", zero)
        ss_emp = s.get("Social Security (Employee)", zero)
        med_emp = s.get("Medicare (Employee)", zero)
        ok_tax = s.get("Oklahoma Income Tax", zero)

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


def _deduction_rows(paychecks: list) -> list[dict]:
    by_type: dict[str, dict] = {}
    for pc in paychecks:
        for line in pc.lines:
            if line.line_type != "deduction":
                continue
            key = line.description
            if key not in by_type:
                by_type[key] = {
                    "description": key,
                    "pre_tax": line.is_pre_tax,
                    "total": Decimal("0"),
                    "count": 0,
                }
            by_type[key]["total"] += Decimal(str(line.amount))
            by_type[key]["count"] += 1
    return sorted(by_type.values(), key=lambda r: r["description"])


@router.get("/deductions", response_class=HTMLResponse)
def deductions_report(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
    quarter: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )
    if not year:
        year = date.today().year

    rows = []
    groups = []
    totals = {}

    if company_ids and year:
        paychecks = _load_paychecks(db, company_ids, year, quarter)
        if company_id == CONSOLIDATED:
            company_map = _company_map(db, company_ids)
            for cid, pcs in _group_by_company(paychecks).items():
                group_rows = _deduction_rows(pcs)
                groups.append({
                    "company": company_map.get(cid),
                    "rows": group_rows,
                    "totals": {
                        "total": sum(r["total"] for r in group_rows),
                        "count": sum(r["count"] for r in group_rows),
                    },
                })
            groups.sort(key=lambda g: g["company"].name if g["company"] else "")
            rows = [r for g in groups for r in g["rows"]]
            totals = {
                "total": sum(g["totals"]["total"] for g in groups),
                "count": sum(g["totals"]["count"] for g in groups),
            }
        else:
            rows = _deduction_rows(paychecks)
            totals = {
                "total": sum(r["total"] for r in rows),
                "count": sum(r["count"] for r in rows),
            }

    return templates.TemplateResponse(request, "reports/deductions.html", {
        "active_nav": "reports",
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "groups": groups,
        "year": year,
        "quarter": quarter,
        "rows": rows,
        "totals": totals,
    })


def _liability_rows(liabilities: list) -> list[dict]:
    by_payee: dict[str, dict] = {}
    for li in liabilities:
        key = li.payee_name
        if key not in by_payee:
            by_payee[key] = {
                "payee_name": key,
                "liability_type": li.liability_type,
                "total": Decimal("0"),
                "remitted": Decimal("0"),
                "count": 0,
            }
        by_payee[key]["total"] += Decimal(str(li.amount))
        if li.remitted_at:
            by_payee[key]["remitted"] += Decimal(str(li.amount))
        by_payee[key]["count"] += 1
    return sorted(by_payee.values(), key=lambda r: r["payee_name"])


@router.get("/client-liabilities", response_class=HTMLResponse)
def client_liabilities_report(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
    year: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )
    if not year:
        year = date.today().year

    rows = []
    groups = []
    totals = {}

    if company_ids and year:
        liabilities = (
            db.query(ClientLiability)
            .join(PayPeriod, ClientLiability.pay_period_id == PayPeriod.id)
            .filter(
                PayPeriod.company_id.in_(company_ids),
                PayPeriod.pay_date >= date(year, 1, 1),
                PayPeriod.pay_date < date(year + 1, 1, 1),
            )
            .all()
        )

        if company_id == CONSOLIDATED:
            company_map = _company_map(db, company_ids)
            by_company: dict[int, list] = {}
            for li in liabilities:
                by_company.setdefault(li.company_id, []).append(li)
            for cid, lis in by_company.items():
                group_rows = _liability_rows(lis)
                groups.append({
                    "company": company_map.get(cid),
                    "rows": group_rows,
                    "totals": {
                        "total": sum(r["total"] for r in group_rows),
                        "remitted": sum(r["remitted"] for r in group_rows),
                    },
                })
            groups.sort(key=lambda g: g["company"].name if g["company"] else "")
            rows = [r for g in groups for r in g["rows"]]
            totals = {
                "total": sum(g["totals"]["total"] for g in groups),
                "remitted": sum(g["totals"]["remitted"] for g in groups),
            }
        else:
            rows = _liability_rows(liabilities)
            totals = {
                "total": sum(r["total"] for r in rows),
                "remitted": sum(r["remitted"] for r in rows),
            }

    return templates.TemplateResponse(request, "reports/client_liabilities.html", {
        "active_nav": "reports",
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "groups": groups,
        "year": year,
        "rows": rows,
        "totals": totals,
    })


@router.get("/new-hires", response_class=HTMLResponse)
def new_hires_report(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
    company_id: int = 0,
):
    if not company_id and active_company:
        company_id = active_company.id
    company_ids, error = _report_scope(
        current_user, db, company_id, allow_consolidated=True,
    )
    employees = []
    groups = []
    cutoff = date.today() - timedelta(days=20)

    if company_ids:
        employees = (
            db.query(Employee)
            .options(joinedload(Employee.company))
            .filter(
                Employee.company_id.in_(company_ids),
                Employee.hire_date >= cutoff,
                Employee.new_hire_reported_at.is_(None),
            )
            .order_by(Employee.hire_date.desc())
            .all()
        )

        if company_id == CONSOLIDATED:
            company_map = _company_map(db, company_ids)
            by_company: dict[int, list] = {}
            for emp in employees:
                by_company.setdefault(emp.company_id, []).append(emp)
            groups = [
                {"company": company_map.get(cid), "employees": emps}
                for cid, emps in by_company.items()
            ]
            groups.sort(key=lambda g: g["company"].name if g["company"] else "")

    return templates.TemplateResponse(request, "reports/new_hires.html", {
        "active_nav": "reports",
        "companies": accessible_companies(current_user, db),
        "company_id": company_id,
        "consolidated": company_id == CONSOLIDATED,
        "allow_consolidated": True,
        "error": error,
        "groups": groups,
        "employees": employees,
        "cutoff": cutoff,
    })
