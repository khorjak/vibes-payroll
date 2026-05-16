import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
from models.base import Base
from models.company import Company
from models.employee import Employee
from models.benefit import BenefitPlan
from main import app


# StaticPool forces all connections through a single underlying SQLite connection,
# which is required for in-memory databases to be visible across the session.
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def company(db):
    co = Company(name="Test Co", pay_frequency="biweekly", state="OK")
    db.add(co)
    db.commit()
    db.refresh(co)
    return co


@pytest.fixture()
def salaried_employee(db, company):
    emp = Employee(
        company_id=company.id,
        first_name="Jane",
        last_name="Smith",
        employment_type="salaried",
        pay_rate=65000.00,
        status="active",
        state="OK",
        flsa_exempt=True,
        hire_date=date(2024, 3, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture()
def hourly_employee(db, company):
    emp = Employee(
        company_id=company.id,
        first_name="Bob",
        last_name="Jones",
        employment_type="hourly",
        pay_rate=18.50,
        status="active",
        state="OK",
        flsa_exempt=False,
        hire_date=date(2025, 1, 15),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture()
def benefit_plan(db, company):
    plan = BenefitPlan(
        company_id=company.id,
        name="Health Plan",
        benefit_type="health",
        employee_contribution_type="fixed",
        employee_contribution_amount=150.00,
        pre_tax=True,
        active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan
