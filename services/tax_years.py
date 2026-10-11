from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from models.federal_withholding import (
    DEFAULT_FEDERAL_TABLES, SCHEDULES, STATUSES, FederalWithholdingTable,
)
from models.oklahoma_withholding import DEFAULT_OKLAHOMA_TABLES, OK_STATUSES, OklahomaWithholdingTable
from models.tax_year import DEFAULT_TAX_YEARS, TaxYear

ROWS_PER_TABLE = 8  # a zero row plus the seven tax brackets


def seed_tax_years(db: Session) -> None:
    """Fill empty tax_years / federal_withholding_tables with the figures shipped with the app."""
    if not db.query(TaxYear).first():
        for year, (ss, suta) in DEFAULT_TAX_YEARS.items():
            db.add(TaxYear(year=year, ss_wage_base=ss, ok_suta_wage_base=suta))
    if not db.query(FederalWithholdingTable).first():
        for year, data in DEFAULT_FEDERAL_TABLES.items():
            db.add(FederalWithholdingTable(year=year, data=data))
    if not db.query(OklahomaWithholdingTable).first():
        for year, data in DEFAULT_OKLAHOMA_TABLES.items():
            db.add(OklahomaWithholdingTable(year=year, data=data))
    db.commit()


def _latest_on_or_before(db: Session, model, year: int):
    """The row for `year`, else the latest earlier one, else the earliest.

    A missing year must not stop January payroll, so it falls back; callers
    compare `.year` with the year they asked for to warn about the fallback.
    """
    return (db.query(model).filter(model.year <= year).order_by(model.year.desc()).first()
            or db.query(model).order_by(model.year).first())


def tax_year_for(db: Session, year: int) -> TaxYear:
    row = _latest_on_or_before(db, TaxYear, year)
    if row is None:
        raise ValueError("No wage bases on file. An admin can add them under Tax Settings.")
    return row


def federal_table_for(db: Session, year: int) -> FederalWithholdingTable:
    row = _latest_on_or_before(db, FederalWithholdingTable, year)
    if row is None:
        raise ValueError("No federal withholding tables on file. An admin can add them under Tax Settings.")
    return row


def ok_table_for(db: Session, year: int) -> OklahomaWithholdingTable:
    row = _latest_on_or_before(db, OklahomaWithholdingTable, year)
    if row is None:
        raise ValueError("No Oklahoma withholding tables on file. An admin can add them under Tax Settings.")
    return row


# ── Federal table entry (Tax Settings form) ─────────────────────────────────

def field(schedule: str, status: str, i: int, col: str) -> str:
    return f"{schedule}.{status}.{i}.{col}"


def form_values(data: dict) -> dict:
    """Stored table -> form field values (rates shown as percentages)."""
    values = {f"line_1g.{k}": data["line_1g"][k] for k in ("married_filing_jointly", "other")}
    for schedule in SCHEDULES:
        for status in STATUSES:
            for i, (at_least, tentative, rate) in enumerate(data[schedule][status]):
                values[field(schedule, status, i, "at_least")] = at_least
                values[field(schedule, status, i, "tentative")] = tentative
                values[field(schedule, status, i, "rate")] = format((Decimal(rate) * 100).normalize(), "f")
    return values


def _amount(raw: str, errors: dict, name: str, maximum: Decimal) -> Decimal | None:
    try:
        value = Decimal((raw or "").replace(",", "").replace("$", "").replace("%", "").strip())
    except InvalidOperation:
        errors[name] = "Enter a number."
        return None
    if not Decimal("0") <= value <= maximum:
        errors[name] = f"Must be between 0 and {maximum:,}."
        return None
    return value


def parse_federal_form(form) -> tuple[dict | None, dict, dict]:
    """Validate a submitted federal table. Returns (data or None, values to redisplay, errors)."""
    values = {k: (form.get(k) or "").strip() for k in form_values(DEFAULT_FEDERAL_TABLES[max(DEFAULT_FEDERAL_TABLES)])}
    errors: dict = {}
    line_1g = {k: _amount(values[f"line_1g.{k}"], errors, f"line_1g.{k}", Decimal("100000"))
               for k in ("married_filing_jointly", "other")}
    data = {"line_1g": {k: format(v, "f") for k, v in line_1g.items() if v is not None}}
    for schedule in SCHEDULES:
        data[schedule] = {}
        for status in STATUSES:
            rows = []
            for i in range(ROWS_PER_TABLE):
                at_least = _amount(values[field(schedule, status, i, "at_least")], errors,
                                   field(schedule, status, i, "at_least"), Decimal("10000000"))
                tentative = _amount(values[field(schedule, status, i, "tentative")], errors,
                                    field(schedule, status, i, "tentative"), Decimal("10000000"))
                pct = _amount(values[field(schedule, status, i, "rate")], errors,
                              field(schedule, status, i, "rate"), Decimal("100"))
                rows.append((at_least, tentative, None if pct is None else pct / 100))
            if all(None not in row for row in rows):
                errors.update(check_rows(rows, lambda i, col: field(schedule, status, i, col)))
            data[schedule][status] = [[format(v, "f") for v in row] if None not in row else None for row in rows]
    if errors:
        return None, values, errors
    return data, values, errors


def check_rows(rows: list, name) -> dict:
    """Catch typos in a bracket table of (at_least, tentative, rate) rows: rows must start
    at 0, rise, and each tentative amount must equal the previous one plus the band times
    its rate (within $1: the IRS rounds its Step 2 tables to whole dollars, the OTC to
    cents). name(i, col) gives the form field to attach an error to."""
    errors = {}
    if rows[0][0] != 0 or rows[0][1] != 0:
        errors[name(0, "at_least")] = "The first row starts at $0 with $0 to withhold."
    for i in range(1, len(rows)):
        (a0, t0, r0), (a1, t1, _) = rows[i - 1], rows[i]
        if a1 <= a0:
            errors[name(i, "at_least")] = "Must be more than the row above."
            continue
        expected = t0 + (a1 - a0) * r0
        if abs(expected - t1) > 1:
            errors[name(i, "tentative")] = (
                f"Expected about ${expected:,.2f} from the row above. Check this row and the one above.")
    return errors


def check_federal_data(data: dict) -> dict:
    """check_rows over a stored table (used by tests on the shipped defaults)."""
    errors = {}
    for schedule in SCHEDULES:
        for status in STATUSES:
            rows = [tuple(Decimal(v) for v in row) for row in data[schedule][status]]
            errors.update(check_rows(rows, lambda i, col: field(schedule, status, i, col)))
    return errors


# ── Oklahoma table entry (Tax Settings form) ────────────────────────────────

OK_MAX_ROWS = 10  # OW-2 has had 4 to 7 rows; blank rows at the end are ignored


def ok_field(status: str, i: int, col: str) -> str:
    return f"{status}.{i}.{col}"


def ok_form_values(data: dict) -> dict:
    """Stored table -> form field values (rates as percentages), padded with blank rows."""
    values = {"allowance": data["allowance"]}
    for status in OK_STATUSES:
        for i in range(OK_MAX_ROWS):
            row = data[status][i] if i < len(data[status]) else ("", "", "")
            values[ok_field(status, i, "at_least")] = row[0]
            values[ok_field(status, i, "tentative")] = row[1]
            values[ok_field(status, i, "rate")] = (
                format((Decimal(row[2]) * 100).normalize(), "f") if row[2] != "" else "")
    return values


def parse_ok_form(form) -> tuple[dict | None, dict, dict]:
    """Validate a submitted Oklahoma table. Returns (data or None, values to redisplay, errors)."""
    values = {"allowance": (form.get("allowance") or "").strip()}
    errors: dict = {}
    allowance = _amount(values["allowance"], errors, "allowance", Decimal("100000"))
    data = {"allowance": format(allowance, "f") if allowance is not None else None}
    for status in OK_STATUSES:
        rows = []
        for i in range(OK_MAX_ROWS):
            names = [ok_field(status, i, col) for col in ("at_least", "tentative", "rate")]
            raw = [(form.get(n) or "").strip() for n in names]
            values.update(zip(names, raw))
            if not any(raw):
                continue
            at_least = _amount(raw[0], errors, names[0], Decimal("10000000"))
            tentative = _amount(raw[1], errors, names[1], Decimal("10000000"))
            pct = _amount(raw[2], errors, names[2], Decimal("100"))
            rows.append((i, (at_least, tentative, None if pct is None else pct / 100)))
        filled = [i for i, _ in rows]
        if filled != list(range(len(rows))):
            gap = next(pos for pos, i in enumerate(filled) if pos != i)  # first blank row
            errors[ok_field(status, gap, "at_least")] = "Fill rows from the top with no gaps."
        elif len(rows) < 2:
            errors[ok_field(status, 0, "at_least")] = "Enter the table's rows (at least two)."
        elif all(None not in row for _, row in rows):
            errors.update(check_rows([row for _, row in rows], lambda i, col: ok_field(status, i, col)))
        data[status] = [[format(v, "f") for v in row] for _, row in rows if None not in row]
    if errors:
        return None, values, errors
    return data, values, errors


def check_ok_data(data: dict) -> dict:
    """check_rows over a stored Oklahoma table (used by tests on the shipped defaults)."""
    errors = {}
    for status in OK_STATUSES:
        rows = [tuple(Decimal(v) for v in row) for row in data[status]]
        errors.update(check_rows(rows, lambda i, col: ok_field(status, i, col)))
    return errors
