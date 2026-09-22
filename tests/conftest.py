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
from models.user import User
from models.user_company import UserCompany
from models.workers_comp import WorkersCompCode
from routers.auth import (
    get_active_company, get_current_user, require_admin, require_preparer,
    require_approver, hash_password,
)
from utils.csrf import _csrf_dep
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


_fake_admin = User(id=1, username="test_admin", role="admin", is_active=True)


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    from app_templates import templates
    _original_is_admin = templates.env.globals.get("is_admin")
    _original_has_role = templates.env.globals.get("has_role")
    _original_company_context = templates.env.globals.get("company_context")
    templates.env.globals["is_admin"] = lambda request: True
    templates.env.globals["has_role"] = lambda request, *roles: True
    # company_context opens its own SessionLocal against the real DB; point the
    # switcher at the test session instead.
    templates.env.globals["company_context"] = lambda request: {
        "active": db.query(Company).order_by(Company.id).first(),
        "available": db.query(Company).order_by(Company.name).all(),
    }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _fake_admin
    app.dependency_overrides[require_admin] = lambda: _fake_admin
    app.dependency_overrides[require_preparer] = lambda: _fake_admin
    app.dependency_overrides[require_approver] = lambda: _fake_admin
    app.dependency_overrides[_csrf_dep] = lambda: None
    # The fake admin bypasses company scope, but routes still need an active
    # company for their "default to the active company" list filtering.
    app.dependency_overrides[get_active_company] = (
        lambda: db.query(Company).order_by(Company.id).first()
    )
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
    if _original_is_admin:
        templates.env.globals["is_admin"] = _original_is_admin
    if _original_has_role:
        templates.env.globals["has_role"] = _original_has_role
    if _original_company_context:
        templates.env.globals["company_context"] = _original_company_context


@pytest.fixture()
def auth_db():
    """Isolated DB for auth/role tests — no dependency overrides so auth runs real."""
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
def auth_client(auth_db):
    """TestClient with real auth (no overrides)."""
    def override_get_db():
        yield auth_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(auth_db):
    user = User(
        username="admin",
        hashed_password=hash_password("secret123"),
        role="admin",
        is_active=True,
    )
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


@pytest.fixture()
def readonly_user(auth_db):
    user = User(
        username="viewer",
        hashed_password=hash_password("viewpass"),
        role="read_only",
        is_active=True,
    )
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


@pytest.fixture()
def preparer_user(auth_db):
    user = User(
        username="preparer",
        hashed_password=hash_password("preppass"),
        role="preparer",
        is_active=True,
    )
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


@pytest.fixture()
def approver_user(auth_db):
    user = User(
        username="approver",
        hashed_password=hash_password("approvepass"),
        role="approver",
        is_active=True,
    )
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    return user


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
def pay_period(db, company):
    from models.payroll import PayPeriod
    pp = PayPeriod(
        company_id=company.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        pay_date=date(2026, 5, 20),
        frequency="biweekly",
        status="open",
    )
    db.add(pp)
    db.commit()
    db.refresh(pp)
    return pp


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


@pytest.fixture()
def second_company(db):
    """A second tenant -- scoping tests are only meaningful with two."""
    co = Company(name="Other Co", pay_frequency="biweekly", state="OK")
    db.add(co)
    db.commit()
    db.refresh(co)
    return co


@pytest.fixture()
def other_employee(db, second_company):
    emp = Employee(
        company_id=second_company.id,
        first_name="Rival",
        last_name="Person",
        employment_type="salaried",
        pay_rate=50000.00,
        status="active",
        state="OK",
        flsa_exempt=True,
        hire_date=date(2025, 6, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture()
def other_pay_period(db, second_company):
    from models.payroll import PayPeriod
    pp = PayPeriod(
        company_id=second_company.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        pay_date=date(2026, 5, 20),
        frequency="biweekly",
        status="open",
    )
    db.add(pp)
    db.commit()
    db.refresh(pp)
    return pp


@pytest.fixture()
def wc_code(db, company):
    code = WorkersCompCode(
        company_id=company.id,
        ncci_code="8810",
        description="Clerical",
        rate_per_100_wages=0.25,
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return code
