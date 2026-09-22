import time
from collections import defaultdict
from typing import Annotated, Optional
import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.company import Company
from models.user import User
from utils.company_scope import accessible_companies, has_company_access
from utils.csrf import CsrfProtect
from app_templates import templates

_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300

router = APIRouter(prefix="/auth", tags=["auth"])


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Drop any memoised company scope from a previous request. Re-querying the
    # User is NOT enough on its own: SQLAlchemy's identity map hands back the
    # same instance when a Session is reused, so the cache would survive and
    # revoked access would keep working until the object was evicted. Clearing
    # it here -- the one dependency every scoped route passes through -- makes
    # the cache provably request-scoped.
    user.__dict__.pop("_company_ids_cache", None)
    return user


def require_role(*allowed_roles: str):
    """Dependency factory: admin always passes; otherwise role must be in allowed_roles."""
    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == "admin" or current_user.role in allowed_roles:
            return current_user
        raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(allowed_roles)}")
    return _dependency


require_admin = require_role("admin")
require_preparer = require_role("preparer")
require_approver = require_role("approver")

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
PreparerUser = Annotated[User, Depends(require_preparer)]
ApproverUser = Annotated[User, Depends(require_approver)]


def _stash_switcher(request: Request, active, available) -> None:
    """Hand the nav switcher its data so company_context need not re-query.

    Without this, main.py's company_context global opens its own SessionLocal on
    every page render just to populate the switcher.
    """
    request.state.company_context = {"active": active, "available": available}


def get_active_company(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Company]:
    """Resolve the session's active company, falling back to the user's first.

    Returns None in two legitimate states: a fresh install with no companies, and
    a non-admin with no assignments. The session value is re-validated against
    current access on every request, so access revoked by an admin takes effect
    immediately rather than at next login.
    """
    company_id = request.session.get("company_id")
    if company_id is not None and has_company_access(current_user, company_id, db):
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            _stash_switcher(request, company, accessible_companies(current_user, db))
            return company

    available = accessible_companies(current_user, db)
    company = available[0] if available else None
    request.session["company_id"] = company.id if company else None
    _stash_switcher(request, company, available)
    return company


ActiveCompany = Annotated[Optional[Company], Depends(get_active_company)]


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "auth/login.html", {
        "next": next,
        "error": None,
    })


def _is_rate_limited(key: str) -> bool:
    now = time.monotonic()
    attempts = _login_attempts[key]
    _login_attempts[key] = [t for t in attempts if now - t < _WINDOW_SECONDS]
    return len(_login_attempts[key]) >= _MAX_ATTEMPTS


def _record_attempt(key: str) -> None:
    _login_attempts[key].append(time.monotonic())


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{username}"
    if _is_rate_limited(rate_key):
        return templates.TemplateResponse(request, "auth/login.html", {
            "next": next,
            "error": "Too many login attempts. Please wait a few minutes.",
        }, status_code=429)
    user = db.query(User).filter(
        User.username == username,
        User.is_active.is_(True),
    ).first()
    if not user or not _bcrypt.checkpw(password.encode(), user.hashed_password.encode()):
        _record_attempt(rate_key)
        return templates.TemplateResponse(request, "auth/login.html", {
            "next": next,
            "error": "Invalid username or password.",
        }, status_code=401)
    _login_attempts.pop(rate_key, None)
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role
    # Drop any previous account's active company; get_active_company re-resolves it.
    request.session.pop("company_id", None)
    return RedirectResponse(next, status_code=303)


@router.post("/logout")
def logout(request: Request, _csrf: CsrfProtect):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)
