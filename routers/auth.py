import time
from collections import defaultdict
from typing import Annotated
import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
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
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


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
    return RedirectResponse(next, status_code=303)


@router.post("/logout")
def logout(request: Request, _csrf: CsrfProtect):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)
