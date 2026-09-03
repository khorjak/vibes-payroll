"""
Direct unit tests for the require_role dependency factory — no HTTP involved.
"""
import pytest
from fastapi import HTTPException
from models.user import User
from routers.auth import require_role, require_admin, require_preparer, require_approver


def _user(role: str) -> User:
    return User(id=1, username="u", hashed_password="x", role=role, is_active=True)


class TestRequireRole:
    def test_admin_satisfies_any_role_requirement(self):
        dep = require_role("preparer")
        assert dep(_user("admin")) is not None

    def test_matching_role_passes(self):
        dep = require_role("preparer")
        result = dep(_user("preparer"))
        assert result.role == "preparer"

    def test_non_matching_role_raises_403(self):
        dep = require_role("preparer")
        with pytest.raises(HTTPException) as exc_info:
            dep(_user("read_only"))
        assert exc_info.value.status_code == 403

    def test_multiple_allowed_roles(self):
        dep = require_role("preparer", "approver")
        assert dep(_user("approver")).role == "approver"
        with pytest.raises(HTTPException):
            dep(_user("read_only"))


class TestRequireAdmin:
    def test_admin_passes(self):
        assert require_admin(_user("admin")).role == "admin"

    def test_preparer_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            require_admin(_user("preparer"))
        assert exc_info.value.status_code == 403

    def test_approver_rejected(self):
        with pytest.raises(HTTPException):
            require_admin(_user("approver"))

    def test_read_only_rejected(self):
        with pytest.raises(HTTPException):
            require_admin(_user("read_only"))


class TestRequirePreparer:
    def test_preparer_passes(self):
        assert require_preparer(_user("preparer")).role == "preparer"

    def test_admin_passes(self):
        assert require_preparer(_user("admin")).role == "admin"

    def test_approver_rejected(self):
        with pytest.raises(HTTPException):
            require_preparer(_user("approver"))

    def test_read_only_rejected(self):
        with pytest.raises(HTTPException):
            require_preparer(_user("read_only"))


class TestRequireApprover:
    def test_approver_passes(self):
        assert require_approver(_user("approver")).role == "approver"

    def test_admin_passes(self):
        assert require_approver(_user("admin")).role == "admin"

    def test_preparer_rejected(self):
        with pytest.raises(HTTPException):
            require_approver(_user("preparer"))

    def test_read_only_rejected(self):
        with pytest.raises(HTTPException):
            require_approver(_user("read_only"))
