from sqlalchemy.orm import Session

from models.tax_year import DEFAULT_TAX_YEARS, TaxYear


def seed_tax_years(db: Session) -> None:
    """Fill an empty tax_years table with the figures shipped with the app."""
    if db.query(TaxYear).first():
        return
    for year, (ss, suta) in DEFAULT_TAX_YEARS.items():
        db.add(TaxYear(year=year, ss_wage_base=ss, ok_suta_wage_base=suta))
    db.commit()


def tax_year_for(db: Session, year: int) -> TaxYear:
    """The row for `year`; if missing, the latest earlier year (else the earliest).

    A missing year must not stop January payroll, so it falls back; callers
    compare `.year` with the year they asked for to warn about the fallback.
    """
    row = (db.query(TaxYear).filter(TaxYear.year <= year).order_by(TaxYear.year.desc()).first()
           or db.query(TaxYear).order_by(TaxYear.year).first())
    if row is None:
        raise ValueError("No wage bases on file. An admin can add them under Tax Settings.")
    return row
