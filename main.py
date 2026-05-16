from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from database import engine
from models import Base
from routers import companies, employees, pay_periods

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Payroll", docs_url="/api/docs")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(pay_periods.router)

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    from database import SessionLocal
    from models.company import Company
    from models.employee import Employee

    db = SessionLocal()
    try:
        company_count = db.query(Company).count()
        employee_count = db.query(Employee).filter(Employee.status == "active").count()
    finally:
        db.close()

    return templates.TemplateResponse(request, "index.html", {
        "company_count": company_count,
        "employee_count": employee_count,
        "active_nav": "dashboard",
    })
