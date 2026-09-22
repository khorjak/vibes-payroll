"""
Unit tests for utils/company_scope.py — no HTTP involved.
"""
import pytest
from fastapi import HTTPException

from models.company import Company
from models.user import User
from models.user_company import UserCompany
from utils.company_scope import (
    ALL,
    accessible_companies,
    accessible_company_ids,
    assert_company_access,
    get_scoped_employee,
    has_company_access,
    resolve_company_ids,
    scope_query,
)


def _user(db, role: str, username: str = "u") -> User:
    user = User(username=username, hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _assign(db, user, company):
    db.add(UserCompany(user_id=user.id, company_id=company.id))
    db.commit()


class TestAccessibleCompanyIds:
    def test_admin_is_unrestricted(self, db, company):
        assert accessible_company_ids(_user(db, "admin"), db) is ALL

    def test_assigned_user_gets_their_companies(self, db, company, second_company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert accessible_company_ids(user, db) == [company.id]

    def test_unassigned_user_gets_nothing(self, db, company):
        assert accessible_company_ids(_user(db, "preparer"), db) == []

    def test_admin_needs_no_assignment_rows(self, db, company, second_company):
        admin = _user(db, "admin")
        assert db.query(UserCompany).filter(UserCompany.user_id == admin.id).count() == 0
        assert {c.id for c in accessible_companies(admin, db)} == {company.id, second_company.id}


class TestAccessChecks:
    def test_admin_has_access_to_any_company(self, db, company, second_company):
        admin = _user(db, "admin")
        assert has_company_access(admin, second_company.id, db) is True

    def test_assigned_company_allowed(self, db, company, second_company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert has_company_access(user, company.id, db) is True
        assert has_company_access(user, second_company.id, db) is False

    def test_assert_raises_404_not_403(self, db, company, second_company):
        """404 so an out-of-scope record is indistinguishable from a missing one."""
        user = _user(db, "preparer")
        _assign(db, user, company)
        with pytest.raises(HTTPException) as exc_info:
            assert_company_access(user, second_company.id, db)
        assert exc_info.value.status_code == 404

    def test_assert_passes_for_allowed_company(self, db, company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert assert_company_access(user, company.id, db) is None


class TestScopeQuery:
    def test_admin_query_unfiltered(self, db, company, second_company):
        from models.employee import Employee
        q = scope_query(db.query(Employee), Employee.company_id, _user(db, "admin"), db)
        assert q.count() == db.query(Employee).count()

    def test_scoped_query_excludes_other_company(
        self, db, company, second_company, salaried_employee, other_employee,
    ):
        from models.employee import Employee
        user = _user(db, "preparer")
        _assign(db, user, company)
        rows = scope_query(db.query(Employee), Employee.company_id, user, db).all()
        assert [e.id for e in rows] == [salaried_employee.id]

    def test_unassigned_user_sees_nothing(
        self, db, company, salaried_employee,
    ):
        from models.employee import Employee
        user = _user(db, "preparer")
        assert scope_query(db.query(Employee), Employee.company_id, user, db).count() == 0


class TestResolveCompanyIds:
    def test_admin_unset_returns_all_ids(self, db, company, second_company):
        ids = resolve_company_ids(_user(db, "admin"), db)
        assert set(ids) == {company.id, second_company.id}

    def test_scoped_unset_returns_assigned_only(self, db, company, second_company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert resolve_company_ids(user, db) == [company.id]

    def test_explicit_company_is_validated(self, db, company, second_company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert resolve_company_ids(user, db, company.id) == [company.id]
        with pytest.raises(HTTPException) as exc_info:
            resolve_company_ids(user, db, second_company.id)
        assert exc_info.value.status_code == 404


class TestScopedLoaders:
    def test_loads_own_company_record(self, db, company, salaried_employee):
        user = _user(db, "preparer")
        _assign(db, user, company)
        assert get_scoped_employee(db, user, salaried_employee.id).id == salaried_employee.id

    def test_other_company_record_is_404(self, db, company, second_company, other_employee):
        user = _user(db, "preparer")
        _assign(db, user, company)
        with pytest.raises(HTTPException) as exc_info:
            get_scoped_employee(db, user, other_employee.id)
        assert exc_info.value.status_code == 404

    def test_missing_record_is_404(self, db, company):
        user = _user(db, "preparer")
        _assign(db, user, company)
        with pytest.raises(HTTPException) as exc_info:
            get_scoped_employee(db, user, 999999)
        assert exc_info.value.status_code == 404

    def test_admin_loads_any_company_record(self, db, company, second_company, other_employee):
        assert get_scoped_employee(db, _user(db, "admin"), other_employee.id).id == other_employee.id
