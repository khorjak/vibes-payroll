import json
from sqlalchemy.orm import Session
from models.audit import AuditLog


def log_change(
    db: Session,
    table_name: str,
    record_id: int,
    action: str,
    changed_by: str | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        action=action,
        changed_by=changed_by,
        old_values=json.dumps(old_values) if old_values else None,
        new_values=json.dumps(new_values) if new_values else None,
    )
    db.add(entry)
