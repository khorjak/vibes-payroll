import pytest
from models.company import Company
from models.workers_comp import WorkersCompCode
from models.benefit import BenefitPlan


class TestCompanyList:
    def test_empty_list_renders(self, client):
        r = client.get("/companies/")
        assert r.status_code == 200
        assert "No companies yet" in r.text

    def test_shows_existing_companies(self, client, company):
        r = client.get("/companies/")
        assert r.status_code == 200
        assert "Test Co" in r.text

    def test_shows_pay_frequency_badge(self, client, company):
        r = client.get("/companies/")
        assert "Biweekly" in r.text


class TestCompanyCreate:
    def test_new_form_renders(self, client):
        r = client.get("/companies/new")
        assert r.status_code == 200
        assert "New Company" in r.text

    def test_create_success_redirects(self, client):
        r = client.post("/companies/new", data={
            "name": "ACME Corp",
            "pay_frequency": "biweekly",
            "state": "OK",
        })
        assert r.status_code == 303
        assert "/companies/" in r.headers["location"]

    def test_create_persists_to_db(self, client, db):
        client.post("/companies/new", data={
            "name": "Persistence Test Co",
            "ein": "12-3456789",
            "pay_frequency": "weekly",
            "state": "OK",
            "suta_rate": "0.027",
        })
        co = db.query(Company).filter(Company.name == "Persistence Test Co").first()
        assert co is not None
        assert co.ein == "12-3456789"
        assert co.pay_frequency == "weekly"
        assert float(co.suta_rate) == pytest.approx(0.027)

    def test_create_missing_name_returns_422(self, client):
        r = client.post("/companies/new", data={
            "name": "",
            "pay_frequency": "biweekly",
            "state": "OK",
        })
        assert r.status_code == 422
        assert "required" in r.text.lower()

    def test_create_missing_name_does_not_persist(self, client, db):
        client.post("/companies/new", data={"name": "", "pay_frequency": "biweekly", "state": "OK"})
        count = db.query(Company).count()
        assert count == 0


class TestCompanyDetail:
    def test_get_existing_company(self, client, company):
        r = client.get(f"/companies/{company.id}")
        assert r.status_code == 200
        assert "Test Co" in r.text

    def test_get_missing_company_returns_404(self, client):
        r = client.get("/companies/9999")
        assert r.status_code == 404

    def test_detail_shows_edit_link(self, client, company):
        r = client.get(f"/companies/{company.id}")
        assert f"/companies/{company.id}/edit" in r.text

    def test_detail_shows_employee_count(self, client, company):
        r = client.get(f"/companies/{company.id}")
        assert "0" in r.text  # 0 employees

    def test_flash_message_on_create(self, client, company):
        r = client.get(f"/companies/{company.id}?flash=created")
        assert r.status_code == 200
        assert "created successfully" in r.text.lower()

    def test_flash_message_on_update(self, client, company):
        r = client.get(f"/companies/{company.id}?flash=updated")
        assert "Changes saved" in r.text


class TestCompanyEdit:
    def test_edit_form_renders_with_existing_values(self, client, company):
        r = client.get(f"/companies/{company.id}/edit")
        assert r.status_code == 200
        assert "Test Co" in r.text

    def test_edit_missing_company_returns_404(self, client):
        r = client.get("/companies/9999/edit")
        assert r.status_code == 404

    def test_update_redirects_on_success(self, client, company):
        r = client.post(f"/companies/{company.id}/edit", data={
            "name": "Updated Name",
            "pay_frequency": "monthly",
            "state": "OK",
        })
        assert r.status_code == 303
        assert f"/companies/{company.id}" in r.headers["location"]

    def test_update_persists_changes(self, client, db, company):
        client.post(f"/companies/{company.id}/edit", data={
            "name": "Renamed Co",
            "pay_frequency": "semi_monthly",
            "state": "TX",
            "suta_rate": "0.035",
        })
        db.refresh(company)
        assert company.name == "Renamed Co"
        assert company.pay_frequency == "semi_monthly"
        assert company.state == "TX"
        assert float(company.suta_rate) == pytest.approx(0.035)

    def test_update_missing_company_returns_404(self, client):
        r = client.post("/companies/9999/edit", data={
            "name": "Ghost", "pay_frequency": "weekly", "state": "OK"
        })
        assert r.status_code == 404


class TestWorkersCompCodes:
    def test_add_wc_code_redirects(self, client, company):
        r = client.post(f"/companies/{company.id}/wc-codes/new", data={
            "ncci_code": "8810",
            "description": "Clerical Office",
            "rate_per_100_wages": "0.12",
        })
        assert r.status_code == 303

    def test_add_wc_code_persists(self, client, db, company):
        client.post(f"/companies/{company.id}/wc-codes/new", data={
            "ncci_code": "5645",
            "description": "Carpentry",
            "rate_per_100_wages": "8.5",
        })
        code = db.query(WorkersCompCode).filter(WorkersCompCode.ncci_code == "5645").first()
        assert code is not None
        assert code.description == "Carpentry"
        assert float(code.rate_per_100_wages) == pytest.approx(8.5)

    def test_add_wc_code_shows_in_company_detail(self, client, db, company):
        db.add(WorkersCompCode(ncci_code="8810", description="Clerical", rate_per_100_wages=0.12))
        db.commit()
        r = client.get(f"/companies/{company.id}")
        assert "8810" in r.text
        assert "Clerical" in r.text


class TestBenefitPlans:
    def test_add_benefit_plan_redirects(self, client, company):
        r = client.post(f"/companies/{company.id}/benefits/new", data={
            "name": "Dental",
            "benefit_type": "dental",
            "employee_contribution_type": "fixed",
            "employee_contribution_amount": "25.00",
        })
        assert r.status_code == 303

    def test_add_benefit_plan_persists(self, client, db, company):
        client.post(f"/companies/{company.id}/benefits/new", data={
            "name": "401k Plan",
            "benefit_type": "traditional_401k",
            "employee_contribution_type": "percent",
            "employee_contribution_amount": "5",
            "employer_match_percent": "50",
            "employer_match_cap_percent": "4",
            "pre_tax": "on",
        })
        plan = db.query(BenefitPlan).filter(BenefitPlan.company_id == company.id).first()
        assert plan is not None
        assert plan.name == "401k Plan"
        assert plan.pre_tax is True
        assert float(plan.employer_match_percent) == pytest.approx(50.0)
        assert float(plan.employer_match_cap_percent) == pytest.approx(4.0)

    def test_benefit_plan_without_pre_tax(self, client, db, company):
        client.post(f"/companies/{company.id}/benefits/new", data={
            "name": "Roth 401k",
            "benefit_type": "roth_401k",
            "employee_contribution_type": "percent",
            "employee_contribution_amount": "3",
        })
        plan = db.query(BenefitPlan).filter(BenefitPlan.name == "Roth 401k").first()
        assert plan is not None
        assert plan.pre_tax is False


class TestBenefitPlanManagement:
    def _make_plan(self, db, company):
        plan = BenefitPlan(
            company_id=company.id, name="Dental", benefit_type="dental",
            employee_contribution_type="fixed", employee_contribution_amount=50,
            pre_tax=True, active=True,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    def test_list_page_renders(self, client, company):
        r = client.get(f"/companies/{company.id}/benefits")
        assert r.status_code == 200
        assert "Benefit Plans" in r.text

    def test_edit_page_renders(self, client, db, company):
        plan = self._make_plan(db, company)
        r = client.get(f"/companies/{company.id}/benefits/{plan.id}/edit")
        assert r.status_code == 200
        assert "Dental" in r.text

    def test_update_plan(self, client, db, company):
        plan = self._make_plan(db, company)
        r = client.post(f"/companies/{company.id}/benefits/{plan.id}/edit", data={
            "name": "Dental Plus",
            "benefit_type": "dental",
            "employee_contribution_type": "fixed",
            "employee_contribution_amount": "75",
        })
        assert r.status_code == 303
        db.refresh(plan)
        assert plan.name == "Dental Plus"
        assert float(plan.employee_contribution_amount) == 75.0

    def test_toggle_deactivates(self, client, db, company):
        plan = self._make_plan(db, company)
        assert plan.active is True
        r = client.post(f"/companies/{company.id}/benefits/{plan.id}/toggle")
        assert r.status_code == 303
        db.refresh(plan)
        assert plan.active is False

    def test_toggle_reactivates(self, client, db, company):
        plan = self._make_plan(db, company)
        plan.active = False
        db.commit()
        r = client.post(f"/companies/{company.id}/benefits/{plan.id}/toggle")
        assert r.status_code == 303
        db.refresh(plan)
        assert plan.active is True


class TestWCCodeManagement:
    def _make_code(self, db):
        code = WorkersCompCode(ncci_code="8810", description="Clerical Office", rate_per_100_wages=0.45)
        db.add(code)
        db.commit()
        db.refresh(code)
        return code

    def test_list_page_renders(self, client, company):
        r = client.get(f"/companies/{company.id}/wc-codes")
        assert r.status_code == 200
        assert "Workers Comp" in r.text

    def test_edit_page_renders(self, client, db, company):
        code = self._make_code(db)
        r = client.get(f"/companies/{company.id}/wc-codes/{code.id}/edit")
        assert r.status_code == 200
        assert "8810" in r.text

    def test_update_wc_code(self, client, db, company):
        code = self._make_code(db)
        r = client.post(f"/companies/{company.id}/wc-codes/{code.id}/edit", data={
            "ncci_code": "8810",
            "description": "Clerical Updated",
            "rate_per_100_wages": "0.55",
        })
        assert r.status_code == 303
        db.refresh(code)
        assert code.description == "Clerical Updated"
        assert float(code.rate_per_100_wages) == pytest.approx(0.55)


class TestOffCyclePayroll:
    def test_off_cycle_form_renders(self, client):
        r = client.get("/payroll/off-cycle/new")
        assert r.status_code == 200
        assert "Off-Cycle" in r.text

    def test_create_off_cycle(self, client, db, company, salaried_employee):
        from models.payroll import PayPeriod, Paycheck
        r = client.post("/payroll/off-cycle/new", data={
            "company_id": company.id,
            "employee_id": salaried_employee.id,
            "pay_date": "2026-06-15",
            "frequency": "biweekly",
            "gross_amount": "1000",
            "description": "Bonus",
        })
        assert r.status_code == 303
        pp = db.query(PayPeriod).order_by(PayPeriod.id.desc()).first()
        assert pp.status == "draft"
        paycheck = db.query(Paycheck).filter(Paycheck.pay_period_id == pp.id).first()
        assert paycheck is not None

    def test_off_cycle_missing_amount_returns_422(self, client, company, salaried_employee):
        r = client.post("/payroll/off-cycle/new", data={
            "company_id": company.id,
            "employee_id": salaried_employee.id,
            "pay_date": "2026-06-15",
            "frequency": "biweekly",
            "gross_amount": "0",
        })
        assert r.status_code == 422
