from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from database import engine, SessionLocal
from models import Base
from config import settings
from app_templates import templates
from routers import companies, employees, pay_periods, reports
from routers.auth import router as auth_router, hash_password
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

app = FastAPI(title="Payroll", docs_url="/api/docs")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(pay_periods.router)
app.include_router(reports.router)

templates.env.globals["csrf_token"] = csrf_token_global


@app.exception_handler(401)
async def auth_exception_handler(request: Request, exc):
    if request.headers.get("HX-Request"):
        return RedirectResponse("/auth/login", status_code=302,
                                headers={"HX-Redirect": "/auth/login"})
    next_path = request.url.path
    return RedirectResponse(f"/auth/login?next={next_path}", status_code=302)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/auth/login?next=/", status_code=302)

    db = SessionLocal()
    try:
        from models.company import Company
        from models.employee import Employee
        from models.payroll import PayPeriod
        company_count = db.query(Company).count()
        employee_count = db.query(Employee).filter(Employee.status == "active").count()
        open_pay_runs = db.query(PayPeriod).filter(PayPeriod.status.in_(["open", "draft"])).count()
    finally:
        db.close()

    return templates.TemplateResponse(request, "index.html", {
        "company_count": company_count,
        "employee_count": employee_count,
        "open_pay_runs": open_pay_runs,
        "active_nav": "dashboard",
    })
