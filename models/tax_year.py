from decimal import Decimal
from sqlalchemy import Numeric
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class TaxYear(Base):
    """Year-specific tax figures, maintained by admins under Tax Settings."""
    __tablename__ = "tax_years"

    year: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ss_wage_base: Mapped[Decimal] = mapped_column(Numeric(12, 2))       # SSA contribution and benefit base
    ok_suta_wage_base: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # OESC taxable wage base


# Published figures shipped with the app, seeded into an empty table on startup
# (ssa.gov/oact/cola/cbb.html; OESC "Important Numbers" sheet for each year).
DEFAULT_TAX_YEARS = {
    2024: (Decimal("168600"), Decimal("27000")),
    2025: (Decimal("176100"), Decimal("28200")),
    2026: (Decimal("184500"), Decimal("25000")),
}
