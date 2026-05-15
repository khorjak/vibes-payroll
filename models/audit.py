from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column(String(10))  # insert, update, delete
    changed_by: Mapped[Optional[str]] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    old_values: Mapped[Optional[str]] = mapped_column(Text)
    new_values: Mapped[Optional[str]] = mapped_column(Text)
