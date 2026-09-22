from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class WorkersCompCode(Base):
    __tablename__ = "workers_comp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    ncci_code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(200))
    rate_per_100_wages: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4))
