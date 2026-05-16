import pytest
from datetime import date
from models.employee import Employee, W4Election, OKWithholdingElection
from models.benefit import EmployeeBenefitEnrollment


class TestEmployeeList:
    def test_empty_list_renders(self, client):
        r = client.get("/employees/")
        assert r.status_code == 200
        assert "No employees found" in r.text

    def test_shows_existing_employees(self, client, salaried_employee):
        r = client.get("/employees/")
        assert r.status_code == 200
        assert "Smith" in r.text
        assert "Jane" in r.text

    def test_shows_employee_type_badge(self, client, salaried_employee, hourly_employee):
        r = client.get("/employees/")
        assert "Salaried" in r.text
        assert "Hourly" in r.text

    def test_htmx_request_returns_partial_without_layout(self, client, salaried_employee):
        r = client.get("/employees/", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "Smith" in r.text
        assert "<aside" not in r.text  # sidebar not in partial

    def test_search_filter_by_last_name(self, client, salaried_employee, hourly_employee):
        r = client.get("/employees/?q=Smith")
        assert "Smith" in r.text
        assert "Jones" not in r.text

    def test_search_filter_no_match(self, client, salaried_employee):
        r = client.get("/employees/?q=Nobody")
        assert "No employees found" in r.text

    def test_status_filter_active(self, client, db, company):
        active = Employee(company_id=company.id, first_name="Active", last_name="Person",
                          employment_type="hourly", pay_rate=15, status="active", state="OK")
        terminated = Employee(company_id=company.id, first_name="Former", last_name="Employee",
                              employment_type="hourly", pay_rate=15, status="terminated", state="OK")
        db.add_all([active, terminated])
        db.commit()
        r = client.get("/employees/?status=active")
        assert "Active" in r.text
        assert "Former" not in r.text

    def test_company_filter(self, client, db, salaried_employee):
        other_co = __import__("models.company", fromlist=["Company"]).Company(
            name="Other Co", pay_frequency="weekly", state="OK"
        )
        db.add(other_co)
        db.commit()
        other_emp = Employee(company_id=other_co.id, first_name="Other", last_name="Person",
                             employment_type="hourly", pay_rate=12, status="active", state="OK")
        db.add(other_emp)
        db.commit()

        r = client.get(f"/employees/?company_id={salaried_employee.company_id}")
        assert "Smith" in r.text
        assert "Person" not in r.text


class TestEmployeeCreate:
    def test_new_form_renders(self, client, company):
        r = client.get("/employees/new")
        assert r.status_code == 200
        assert "New Employee" in r.text

    def test_new_form_shows_companies(self, client, company):
        r = client.get("/employees/new")
        assert "Test Co" in r.text

    def test_create_success_redirects(self, client, company):
        r = client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "Alice",
            "last_name": "Walker",
            "employment_type": "hourly",
            "pay_rate": "20.00",
            "status": "active",
            "state": "OK",
        })
        assert r.status_code == 303
        assert "/employees/" in r.headers["location"]

    def test_create_persists_to_db(self, client, db, company):
        client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "Alice",
            "last_name": "Walker",
            "employment_type": "salaried",
            "pay_rate": "75000",
            "hire_date": "2026-01-01",
            "department": "Engineering",
            "job_title": "Developer",
            "state": "OK",
            "flsa_exempt": "on",
        })
        emp = db.query(Employee).filter(Employee.last_name == "Walker").first()
        assert emp is not None
        assert emp.employment_type == "salaried"
        assert float(emp.pay_rate) == pytest.approx(75000.0)
        assert emp.hire_date == date(2026, 1, 1)
        assert emp.department == "Engineering"
        assert emp.flsa_exempt is True

    def test_create_missing_first_name_returns_422(self, client, company):
        r = client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "",
            "last_name": "Doe",
            "employment_type": "hourly",
            "pay_rate": "15",
            "state": "OK",
        })
        assert r.status_code == 422

    def test_create_missing_last_name_returns_422(self, client, company):
        r = client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "John",
            "last_name": "",
            "employment_type": "hourly",
            "pay_rate": "15",
            "state": "OK",
        })
        assert r.status_code == 422

    def test_create_missing_pay_rate_returns_422(self, client, company):
        r = client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "John",
            "last_name": "Doe",
            "employment_type": "hourly",
            "pay_rate": "",
            "state": "OK",
        })
        assert r.status_code == 422

    def test_create_validation_error_does_not_persist(self, client, db, company):
        client.post("/employees/new", data={
            "company_id": company.id,
            "first_name": "",
            "last_name": "",
            "employment_type": "hourly",
            "pay_rate": "",
            "state": "OK",
        })
        assert db.query(Employee).count() == 0


class TestEmployeeDetail:
    def test_get_employee_profile(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}")
        assert r.status_code == 200
        assert "Jane" in r.text
        assert "Smith" in r.text

    def test_profile_shows_pay_rate(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "65,000" in r.text

    def test_profile_shows_employment_type(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "Salaried" in r.text or "salaried" in r.text

    def test_profile_shows_company_link(self, client, salaried_employee, company):
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "Test Co" in r.text

    def test_profile_shows_no_w4_message(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "No W-4 on file" in r.text

    def test_get_missing_employee_returns_404(self, client):
        r = client.get("/employees/9999")
        assert r.status_code == 404

    def test_flash_created(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}?flash=created")
        assert "created successfully" in r.text.lower()

    def test_flash_updated(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}?flash=updated")
        assert "Changes saved" in r.text


class TestEmployeeEdit:
    def test_edit_form_renders(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}/edit")
        assert r.status_code == 200
        assert "Jane" in r.text

    def test_edit_missing_employee_returns_404(self, client):
        r = client.get("/employees/9999/edit")
        assert r.status_code == 404

    def test_update_redirects_on_success(self, client, salaried_employee, company):
        r = client.post(f"/employees/{salaried_employee.id}/edit", data={
            "company_id": company.id,
            "first_name": "Janet",
            "last_name": "Smith",
            "employment_type": "salaried",
            "pay_rate": "70000",
            "status": "active",
            "state": "OK",
        })
        assert r.status_code == 303

    def test_update_persists_changes(self, client, db, salaried_employee, company):
        client.post(f"/employees/{salaried_employee.id}/edit", data={
            "company_id": company.id,
            "first_name": "Janet",
            "last_name": "Smith-Jones",
            "employment_type": "salaried",
            "pay_rate": "72000",
            "status": "active",
            "department": "Finance",
            "state": "OK",
            "flsa_exempt": "on",
        })
        db.refresh(salaried_employee)
        assert salaried_employee.first_name == "Janet"
        assert salaried_employee.last_name == "Smith-Jones"
        assert float(salaried_employee.pay_rate) == pytest.approx(72000.0)
        assert salaried_employee.department == "Finance"

    def test_update_termination(self, client, db, salaried_employee, company):
        client.post(f"/employees/{salaried_employee.id}/edit", data={
            "company_id": company.id,
            "first_name": "Jane",
            "last_name": "Smith",
            "employment_type": "salaried",
            "pay_rate": "65000",
            "status": "terminated",
            "termination_date": "2026-06-30",
            "state": "OK",
        })
        db.refresh(salaried_employee)
        assert salaried_employee.status == "terminated"
        assert salaried_employee.termination_date == date(2026, 6, 30)

    def test_update_missing_employee_returns_404(self, client):
        r = client.post("/employees/9999/edit", data={
            "company_id": 1, "first_name": "Ghost", "last_name": "X",
            "employment_type": "hourly", "pay_rate": "10", "status": "active", "state": "OK",
        })
        assert r.status_code == 404


class TestW4Elections:
    def test_w4_form_renders(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}/w4/new")
        assert r.status_code == 200
        assert "W-4" in r.text
        assert "Smith" in r.text

    def test_w4_form_missing_employee_returns_404(self, client):
        r = client.get("/employees/9999/w4/new")
        assert r.status_code == 404

    def test_create_w4_redirects(self, client, salaried_employee):
        r = client.post(f"/employees/{salaried_employee.id}/w4/new", data={
            "effective_date": "2026-01-01",
            "filing_status": "single",
            "dependents_amount": "0",
            "other_income": "0",
            "deductions_amount": "0",
            "extra_withholding": "0",
        })
        assert r.status_code == 303
        assert f"/employees/{salaried_employee.id}" in r.headers["location"]

    def test_create_w4_persists(self, client, db, salaried_employee):
        client.post(f"/employees/{salaried_employee.id}/w4/new", data={
            "effective_date": "2026-01-01",
            "filing_status": "married_filing_jointly",
            "multiple_jobs": "on",
            "dependents_amount": "4000",
            "other_income": "500",
            "deductions_amount": "0",
            "extra_withholding": "75",
        })
        election = db.query(W4Election).filter(
            W4Election.employee_id == salaried_employee.id
        ).first()
        assert election is not None
        assert election.filing_status == "married_filing_jointly"
        assert election.multiple_jobs is True
        assert float(election.dependents_amount) == pytest.approx(4000.0)
        assert float(election.extra_withholding) == pytest.approx(75.0)

    def test_w4_shows_on_profile(self, client, db, salaried_employee):
        db.add(W4Election(
            employee_id=salaried_employee.id,
            effective_date=date(2026, 1, 1),
            filing_status="single",
            extra_withholding=50,
        ))
        db.commit()
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "Single" in r.text
        assert "No W-4 on file" not in r.text

    def test_multiple_w4_elections_profile_shows_most_recent(self, client, db, salaried_employee):
        db.add(W4Election(employee_id=salaried_employee.id, effective_date=date(2025, 1, 1),
                          filing_status="single", extra_withholding=0))
        db.add(W4Election(employee_id=salaried_employee.id, effective_date=date(2026, 1, 1),
                          filing_status="married_filing_jointly", extra_withholding=100))
        db.commit()
        r = client.get(f"/employees/{salaried_employee.id}")
        assert "Married Filing Jointly" in r.text


class TestOKWithholdingElections:
    def test_ok_form_renders(self, client, salaried_employee):
        r = client.get(f"/employees/{salaried_employee.id}/ok-withholding/new")
        assert r.status_code == 200
        assert "Oklahoma" in r.text

    def test_ok_form_missing_employee_returns_404(self, client):
        r = client.get("/employees/9999/ok-withholding/new")
        assert r.status_code == 404

    def test_create_ok_withholding_redirects(self, client, salaried_employee):
        r = client.post(f"/employees/{salaried_employee.id}/ok-withholding/new", data={
            "effective_date": "2026-01-01",
            "filing_status": "married",
            "allowances": "2",
            "extra_withholding": "0",
        })
        assert r.status_code == 303

    def test_create_ok_withholding_persists(self, client, db, salaried_employee):
        client.post(f"/employees/{salaried_employee.id}/ok-withholding/new", data={
            "effective_date": "2026-03-01",
            "filing_status": "single",
            "allowances": "1",
            "extra_withholding": "25",
        })
        election = db.query(OKWithholdingElection).filter(
            OKWithholdingElection.employee_id == salaried_employee.id
        ).first()
        assert election is not None
        assert election.filing_status == "single"
        assert election.allowances == 1
        assert float(election.extra_withholding) == pytest.approx(25.0)
        assert election.effective_date == date(2026, 3, 1)


class TestBenefitEnrollments:
    def test_enroll_in_benefit_plan(self, client, db, salaried_employee, benefit_plan):
        r = client.post(f"/employees/{salaried_employee.id}/benefits/enroll", data={
            "benefit_plan_id": benefit_plan.id,
            "effective_date": "2026-01-01",
        })
        assert r.status_code == 303
        enrollment = db.query(EmployeeBenefitEnrollment).filter(
            EmployeeBenefitEnrollment.employee_id == salaried_employee.id
        ).first()
        assert enrollment is not None
        assert enrollment.benefit_plan_id == benefit_plan.id
        assert enrollment.effective_date == date(2026, 1, 1)
        assert enrollment.end_date is None

    def test_enroll_with_amount_override(self, client, db, salaried_employee, benefit_plan):
        client.post(f"/employees/{salaried_employee.id}/benefits/enroll", data={
            "benefit_plan_id": benefit_plan.id,
            "effective_date": "2026-01-01",
            "employee_override_amount": "200",
        })
        enrollment = db.query(EmployeeBenefitEnrollment).filter(
            EmployeeBenefitEnrollment.employee_id == salaried_employee.id
        ).first()
        assert float(enrollment.employee_override_amount) == pytest.approx(200.0)

    def test_terminate_enrollment(self, client, db, salaried_employee, benefit_plan):
        enrollment = EmployeeBenefitEnrollment(
            employee_id=salaried_employee.id,
            benefit_plan_id=benefit_plan.id,
            effective_date=date(2026, 1, 1),
        )
        db.add(enrollment)
        db.commit()
        db.refresh(enrollment)

        r = client.post(
            f"/employees/{salaried_employee.id}/benefits/{enrollment.id}/terminate",
            data={"end_date": "2026-12-31"},
        )
        assert r.status_code == 303
        db.refresh(enrollment)
        assert enrollment.end_date == date(2026, 12, 31)

    def test_terminate_nonexistent_enrollment_is_a_noop(self, client, salaried_employee):
        r = client.post(
            f"/employees/{salaried_employee.id}/benefits/9999/terminate",
            data={"end_date": "2026-12-31"},
        )
        assert r.status_code == 303  # silently ignored, still redirects
