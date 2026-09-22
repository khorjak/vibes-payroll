from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from database import engine, get_db, SessionLocal
from models import Base
from config import settings
from app_templates import templates
from routers import companies, employees, pay_periods, reports, users
from routers.auth import (
    ActiveCompany, CurrentUser, router as auth_router, hash_password,
)
from utils.csrf import csrf_token_global

Base.metadata.create_all(bind=engine)

# Seed default admin user on first run
with SessionLocal() as _db:
    from models.user import User
    if not _db.query(User).first():
        _db.add(User(
            username=settings.admin_username,
            hashed_password=hash_password(settings.admin_password),
            role="admin",
            is_active=True,
        ))
        _db.commit()

app = FastAPI(title="Payroll", docs_url="/api/docs" if settings.debug else None)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.session_https_only,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(pay_periods.router)
app.include_router(reports.router)
app.include_router(users.router)

@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com https://unpkg.com 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


templates.env.globals["csrf_token"] = csrf_token_global


def has_role(request, *roles):
    return request.session.get("role") in roles or request.session.get("role") == "admin"


def is_admin(request):
    return has_role(request, "admin")


def company_context(request):
    """Jinja2 global backing the nav company switcher.

    Returns {"active": Company|None, "available": [Company, ...]}. Opens its own
    short-lived session so no route has to thread switcher data into its context.
    """
    from models.company import Company
    from models.user import User
    from utils.company_scope import accessible_companies

    empty = {"active": None, "available": []}
    user_id = request.session.get("user_id")
    if not user_id:
        return empty

    # Routes with an ActiveCompany dependency already resolved this; reuse it
    # rather than opening a second session per page render.
    stashed = getattr(request.state, "company_context", None)
    if stashed is not None:
        return stashed

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return empty
        available = accessible_companies(user, db)
        active_id = request.session.get("company_id")
        active = next((c for c in available if c.id == active_id), None)
        if active is None and available:
            active = available[0]
        return {"active": active, "available": available}
    finally:
        db.close()


templates.env.globals["has_role"] = has_role
templates.env.globals["is_admin"] = is_admin
templates.env.globals["company_context"] = company_context


@app.exception_handler(401)
async def auth_exception_handler(request: Request, exc):
    if request.headers.get("HX-Request"):
        return RedirectResponse("/auth/login", status_code=302,
                                headers={"HX-Redirect": "/auth/login"})
    next_path = request.url.path
    return RedirectResponse(f"/auth/login?next={next_path}", status_code=302)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    current_user: CurrentUser,
    active_company: ActiveCompany,
    db: Session = Depends(get_db),
):
    """Dashboard.

    Uses the normal dependencies rather than hand-rolling a session: that gets
    the request-scoped company cache and the nav switcher stash for free (this
    route previously opened two extra sessions per render), and an
    unauthenticated hit raises 401, which the handler above turns into the same
    login redirect as before.
    """
    from models.employee import Employee
    from models.payroll import PayPeriod
    from utils.company_scope import accessible_companies

    # Counts are scoped to the active company -- global counts would leak the
    # size of payroll clients this user has no access to.
    company_count = len(accessible_companies(current_user, db))
    if active_company:
        employee_count = db.query(Employee).filter(
            Employee.company_id == active_company.id, Employee.status == "active",
        ).count()
        open_pay_runs = db.query(PayPeriod).filter(
            PayPeriod.company_id == active_company.id,
            PayPeriod.status.in_(["open", "draft"]),
        ).count()
    else:
        employee_count = 0
        open_pay_runs = 0

    return templates.TemplateResponse(request, "index.html", {
        "company_count": company_count,
        "employee_count": employee_count,
        "open_pay_runs": open_pay_runs,
        "active_company_name": active_company.name if active_company else None,
        "active_nav": "dashboard",
    })
