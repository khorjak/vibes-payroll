from datetime import date
from decimal import Decimal
from models.employee import Employee, W4Election, OKWithholdingElection
from models.company import Company


def test_employee_full_name():
    emp = Employee(first_name="Jane", last_name="Smith", employment_type="salaried", pay_rate=Decimal("60000"))
    assert emp.full_name == "Jane Smith"


def test_employee_active_w4_is_none_with_no_elections():
    emp = Employee(first_name="Jane", last_name="Smith", employment_type="salaried", pay_rate=Decimal("60000"))
    emp.w4_elections = []
    assert emp.active_w4 is None


def test_employee_active_w4_returns_first_in_list():
    # Relationship is ordered desc by effective_date, so index 0 is the most recent.
    emp = Employee(first_name="Jane", last_name="Smith", employment_type="salaried", pay_rate=Decimal("60000"))
    recent = W4Election(effective_date=date(2026, 1, 1), filing_status="married_filing_jointly")
    older = W4Election(effective_date=date(2025, 1, 1), filing_status="single")
    emp.w4_elections = [recent, older]
    assert emp.active_w4 is recent
    assert emp.active_w4.filing_status == "married_filing_jointly"


def test_employee_active_ok_withholding_is_none_with_no_elections():
    emp = Employee(first_name="Jane", last_name="Smith", employment_type="salaried", pay_rate=Decimal("60000"))
    emp.ok_withholding_elections = []
    assert emp.active_ok_withholding is None


def test_employee_active_ok_withholding_returns_first_in_list():
    emp = Employee(first_name="Jane", last_name="Smith", employment_type="salaried", pay_rate=Decimal("60000"))
    recent = OKWithholdingElection(effective_date=date(2026, 1, 1), filing_status="married", allowances=2)
    older = OKWithholdingElection(effective_date=date(2025, 1, 1), filing_status="single", allowances=0)
    emp.ok_withholding_elections = [recent, older]
    assert emp.active_ok_withholding is recent
    assert emp.active_ok_withholding.allowances == 2


def test_company_defaults(db):
    # SQLAlchemy applies mapped_column(default=...) at INSERT time, not construction time.
    # Verify after persisting.
    co = Company(name="ACME")
    db.add(co)
    db.commit()
    db.refresh(co)
    assert co.state == "OK"
    assert co.pay_frequency == "biweekly"


def test_employee_defaults(db, company):
    emp = Employee(
        company_id=company.id,
        first_name="Bob", last_name="Brown",
        employment_type="hourly", pay_rate=Decimal("15.00"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    assert emp.status == "active"
    assert emp.state == "OK"
    assert emp.flsa_exempt is False
