"""Per-user company (tenant) scoping.

Orthogonal to the 4-role RBAC in ``routers/auth.py``: roles control *what* a user
may do, this module controls *which companies* they may do it to.

Admins bypass company scope entirely, mirroring how ``require_role`` lets admin
pass every role check -- one mental model: admin passes everything.

Out-of-scope records raise **404, not 403**. A 403 would confirm that a record
exists and belongs to another payroll client; across unrelated tenants that is
itself a disclosure. Out-of-scope must be indistinguishable from nonexistent.
"""

from typing import Optional, Union

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.company import Company
from models.employee import Employee
from models.payroll import PayPeriod, Paycheck
from models.user import User
from models.user_company import UserCompany
from models.workers_comp import WorkersCompCode


class _All:
    """Sentinel for 'unrestricted' (admin). Truthy, and never equal to a list."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ALL"


ALL = _All()

CompanyIds = Union[_All, list[int]]


def accessible_company_ids(user: User, db: Session) -> CompanyIds:
    """ALL for admins, otherwise the list of company ids assigned to the user.

    Memoised on the ``User`` instance. ``get_current_user`` re-queries the user
    from the DB on every request, so the cached value lives exactly one request
    and CANNOT outlive it -- that matters, because a cache that survived across
    requests would re-open the revocation hole this module exists to close
    (access removed by an admin must take effect on the very next request, not
    at next login). Guarded by
    tests/test_multi_company.py::test_revoked_access_takes_effect_without_relogin.
    """
    if user.role == "admin":
        return ALL
    cached = getattr(user, "_company_ids_cache", None)
    if cached is not None:
        return cached
    result = [
        row.company_id
        for row in db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
    ]
    user._company_ids_cache = result
    return result


def accessible_companies(user: User, db: Session) -> list[Company]:
    """Company rows the user may see, ordered by name. Empty list means no access."""
    query = db.query(Company)
    allowed = accessible_company_ids(user, db)
    if allowed is not ALL:
        if not allowed:
            return []
        query = query.filter(Company.id.in_(allowed))
    return query.order_by(Company.name).all()


def has_company_access(user: User, company_id: int, db: Session) -> bool:
    allowed = accessible_company_ids(user, db)
    return allowed is ALL or company_id in allowed


def assert_company_access(user: User, company_id: int, db: Session) -> None:
    """Raise 404 if the user may not touch this company. Use before any write."""
    if not has_company_access(user, company_id, db):
        raise HTTPException(status_code=404, detail="Not found")


def scope_query(query, column, user: User, db: Session):
    """Filter a query to the user's companies. ``column`` is the model's company_id."""
    allowed = accessible_company_ids(user, db)
    if allowed is ALL:
        return query
    return query.filter(column.in_(allowed))


def resolve_company_ids(user: User, db: Session, requested: Optional[int] = None) -> list[int]:
    """Concrete company id list for reporting.

    ``requested`` of 0/None means "all companies the user may see". Always returns
    real ids (never the ALL sentinel) so callers can build ``IN`` filters directly.
    """
    if requested:
        assert_company_access(user, requested, db)
        return [requested]
    allowed = accessible_company_ids(user, db)
    if allowed is ALL:
        return [c.id for c in db.query(Company.id).order_by(Company.id).all()]
    return list(allowed)


# --- Scoped loaders -------------------------------------------------------
# Each collapses the old "look up by bare id, 404 if missing" block into one call
# that also 404s when the record belongs to another tenant.


def _scoped_first(query, column, user: User, db: Session):
    row = scope_query(query, column, user, db).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def get_scoped_employee(db: Session, user: User, employee_id: int, *options) -> Employee:
    query = db.query(Employee)
    if options:
        query = query.options(*options)
    return _scoped_first(
        query.filter(Employee.id == employee_id), Employee.company_id, user, db
    )


def get_scoped_pay_period(db: Session, user: User, period_id: int, *options) -> PayPeriod:
    query = db.query(PayPeriod)
    if options:
        query = query.options(*options)
    return _scoped_first(
        query.filter(PayPeriod.id == period_id), PayPeriod.company_id, user, db
    )


def get_scoped_paycheck(db: Session, user: User, paycheck_id: int, *options) -> Paycheck:
    """Paychecks have no company_id of their own -- scope via their pay period."""
    query = db.query(Paycheck).join(PayPeriod, Paycheck.pay_period_id == PayPeriod.id)
    if options:
        query = query.options(*options)
    return _scoped_first(
        query.filter(Paycheck.id == paycheck_id), PayPeriod.company_id, user, db
    )


def get_scoped_company(db: Session, user: User, company_id: int) -> Company:
    return _scoped_first(
        db.query(Company).filter(Company.id == company_id), Company.id, user, db
    )


def get_scoped_wc_code(db: Session, user: User, code_id: int) -> WorkersCompCode:
    return _scoped_first(
        db.query(WorkersCompCode).filter(WorkersCompCode.id == code_id),
        WorkersCompCode.company_id,
        user,
        db,
    )
