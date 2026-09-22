from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database import get_db
from models.company import Company
from models.user import User, USER_ROLES
from models.user_company import UserCompany
from routers.auth import AdminUser, get_current_user, hash_password
from utils.csrf import CsrfProtect
from services.audit import log_change

from app_templates import templates

router = APIRouter(prefix="/users", tags=["users"],
                   dependencies=[Depends(get_current_user)])

_MIN_PASSWORD_LENGTH = 8


def _all_companies(db: Session) -> list[Company]:
    return db.query(Company).order_by(Company.name).all()


def _assigned_company_ids(db: Session, user_id: int) -> set[int]:
    return {
        row.company_id
        for row in db.query(UserCompany).filter(UserCompany.user_id == user_id).all()
    }


def _sync_company_assignments(
    db: Session, target_user: User, submitted_ids: list[int], changed_by: str,
) -> None:
    """Diff submitted company ids against stored rows; insert/delete the difference.

    Admins are not assigned -- they bypass company scope entirely -- so any
    submitted ids are ignored for them. Grants and revokes are audit-logged
    because company access is a security boundary, like a role change.
    """
    if target_user.role == "admin":
        return

    valid_ids = {c.id for c in _all_companies(db)}
    wanted = {cid for cid in submitted_ids if cid in valid_ids}
    existing = _assigned_company_ids(db, target_user.id)

    for company_id in sorted(wanted - existing):
        row = UserCompany(user_id=target_user.id, company_id=company_id)
        db.add(row)
        db.flush()
        log_change(db, "user_companies", row.id, "insert",
                   changed_by=changed_by,
                   new_values={"user_id": target_user.id, "company_id": company_id})

    removed = existing - wanted
    if removed:
        rows_to_delete = db.query(UserCompany).filter(
            UserCompany.user_id == target_user.id,
            UserCompany.company_id.in_(removed),
        ).order_by(UserCompany.company_id).all()
        for row in rows_to_delete:
            log_change(db, "user_companies", row.id, "delete",
                       changed_by=changed_by,
                       old_values={"user_id": target_user.id, "company_id": row.company_id})
            db.delete(row)


@router.get("/", response_class=HTMLResponse)
def list_users(request: Request, _: AdminUser, db: Session = Depends(get_db), flash: str = ""):
    users = db.query(User).order_by(User.username).all()
    companies = {c.id: c for c in _all_companies(db)}
    assignments: dict[int, list[str]] = {}
    for row in db.query(UserCompany).all():
        company = companies.get(row.company_id)
        if company:
            assignments.setdefault(row.user_id, []).append(company.name)
    for names in assignments.values():
        names.sort()
    return templates.TemplateResponse(request, "users/list.html", {
        "users": users,
        "assignments": assignments,
        "flash": flash,
        "current_user_id": request.session.get("user_id"),
        "active_nav": "users",
    })


@router.get("/new", response_class=HTMLResponse)
def new_user(request: Request, _: AdminUser, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "users/form.html", {
        "target_user": None,
        "roles": USER_ROLES,
        "companies": _all_companies(db),
        "assigned_company_ids": set(),
        "errors": {},
        "active_nav": "users",
    })


@router.post("/new")
def create_user(
    request: Request,
    current_user: AdminUser,
    _csrf: CsrfProtect,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    company_ids: list[int] = Form(default=[]),
):
    errors = {}
    username = username.strip()
    if not username:
        errors["username"] = "Username is required."
    elif db.query(User).filter(User.username == username).first():
        errors["username"] = "That username is already taken."
    if role not in USER_ROLES:
        errors["role"] = "Invalid role."
    if len(password) < _MIN_PASSWORD_LENGTH:
        errors["password"] = f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."

    if errors:
        return templates.TemplateResponse(request, "users/form.html", {
            "target_user": None,
            "roles": USER_ROLES,
            "companies": _all_companies(db),
            "assigned_company_ids": set(company_ids),
            "errors": errors,
            "active_nav": "users",
        }, status_code=422)

    user = User(
        username=username,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Two concurrent requests can both pass the .first() uniqueness check
        # above before either commits — the DB's unique constraint is the real
        # guard; this just turns that race into a normal form error instead of
        # a 500.
        db.rollback()
        return templates.TemplateResponse(request, "users/form.html", {
            "target_user": None,
            "roles": USER_ROLES,
            "companies": _all_companies(db),
            "assigned_company_ids": set(company_ids),
            "errors": {"username": "That username is already taken."},
            "active_nav": "users",
        }, status_code=422)
    log_change(db, "users", user.id, "insert",
               changed_by=current_user.username,
               new_values={"username": user.username, "role": user.role})
    _sync_company_assignments(db, user, company_ids, current_user.username)
    db.commit()
    return RedirectResponse("/users/?flash=created", status_code=303)


@router.get("/{user_id}/edit", response_class=HTMLResponse)
def edit_user(request: Request, user_id: int, _: AdminUser, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse(request, "users/form.html", {
        "target_user": target_user,
        "roles": USER_ROLES,
        "companies": _all_companies(db),
        "assigned_company_ids": _assigned_company_ids(db, user_id),
        "errors": {},
        "active_nav": "users",
    })


@router.post("/{user_id}/edit")
def update_user(
    request: Request,
    current_user: AdminUser,
    _csrf: CsrfProtect,
    user_id: int,
    db: Session = Depends(get_db),
    role: str = Form(...),
    is_active: str = Form(""),
    company_ids: list[int] = Form(default=[]),
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    errors = {}
    if role not in USER_ROLES:
        errors["role"] = "Invalid role."

    if errors:
        return templates.TemplateResponse(request, "users/form.html", {
            "target_user": target_user,
            "roles": USER_ROLES,
            "companies": _all_companies(db),
            "assigned_company_ids": set(company_ids),
            "errors": errors,
            "active_nav": "users",
        }, status_code=422)

    new_active = is_active == "on"
    old_values = {"role": target_user.role, "is_active": target_user.is_active}

    # Guard and write in one atomic UPDATE so two concurrent edits can't both
    # read "another active admin exists" before either commits and leave zero
    # active admins. The WHERE clause re-checks the invariant against the row
    # as SQLite sees it at UPDATE time, not against the (possibly stale)
    # target_user loaded above.
    result = db.execute(
        text("""
            UPDATE users
            SET role = :new_role, is_active = :new_active
            WHERE id = :user_id
            AND (
                NOT (role = 'admin' AND is_active = 1)
                OR (:new_role = 'admin' AND :new_active = 1)
                OR (SELECT COUNT(*) FROM users
                    WHERE role = 'admin' AND is_active = 1 AND id != :user_id) > 0
            )
        """),
        {"new_role": role, "new_active": 1 if new_active else 0, "user_id": user_id},
    )

    if result.rowcount == 0:
        db.rollback()
        return templates.TemplateResponse(request, "users/form.html", {
            "target_user": target_user,
            "roles": USER_ROLES,
            "companies": _all_companies(db),
            "assigned_company_ids": set(company_ids),
            "errors": {"role": "Cannot demote or deactivate the last active admin."},
            "active_nav": "users",
        }, status_code=422)

    log_change(db, "users", user_id, "update",
               changed_by=current_user.username,
               old_values=old_values,
               new_values={"role": role, "is_active": new_active})
    # Re-read: the raw UPDATE above bypassed the ORM, so target_user.role is stale
    # and _sync_company_assignments keys off the *new* role.
    db.refresh(target_user)
    _sync_company_assignments(db, target_user, company_ids, current_user.username)
    db.commit()
    return RedirectResponse("/users/?flash=updated", status_code=303)


@router.get("/{user_id}/reset-password", response_class=HTMLResponse)
def reset_password_form(request: Request, user_id: int, _: AdminUser, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse(request, "users/reset_password.html", {
        "target_user": target_user,
        "errors": {},
        "active_nav": "users",
    })


@router.post("/{user_id}/reset-password")
def reset_password(
    request: Request,
    current_user: AdminUser,
    _csrf: CsrfProtect,
    user_id: int,
    db: Session = Depends(get_db),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    errors = {}
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        errors["new_password"] = f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
    elif new_password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."

    if errors:
        return templates.TemplateResponse(request, "users/reset_password.html", {
            "target_user": target_user,
            "errors": errors,
            "active_nav": "users",
        }, status_code=422)

    target_user.hashed_password = hash_password(new_password)
    log_change(db, "users", user_id, "update",
               changed_by=current_user.username,
               new_values={"action": "password_reset"})
    db.commit()
    return RedirectResponse("/users/?flash=password_reset", status_code=303)
