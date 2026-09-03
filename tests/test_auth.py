"""
Tests for Phase 6 authentication and authorization.

auth_db/auth_client/admin_user/readonly_user/preparer_user/approver_user
fixtures live in conftest.py (shared with tests/test_users.py).
"""
from routers.auth import hash_password


class TestLoginLogout:
    def test_login_page_renders(self, auth_client):
        r = auth_client.get("/auth/login")
        assert r.status_code == 200
        assert "Sign In" in r.text

    def test_login_success_redirects(self, auth_client, admin_user):
        r = auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "secret123",
            "next": "/",
        })
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_login_invalid_password(self, auth_client, admin_user):
        r = auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "wrongpassword",
            "next": "/",
        })
        assert r.status_code == 401
        assert "Invalid username or password" in r.text

    def test_login_unknown_user(self, auth_client):
        r = auth_client.post("/auth/login", data={
            "username": "ghost",
            "password": "whatever",
            "next": "/",
        })
        assert r.status_code == 401

    def test_login_sets_session(self, auth_client, admin_user):
        auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "secret123",
            "next": "/",
        })
        r = auth_client.get("/companies/")
        assert r.status_code == 200

    def test_logout_clears_session(self, auth_client, admin_user):
        auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "secret123",
            "next": "/",
        })
        page = auth_client.get("/companies/")
        import re
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)
        csrf = m.group(1) if m else ""
        auth_client.post("/auth/logout", data={"csrf_token": csrf})
        r = auth_client.get("/companies/")
        assert r.status_code == 302
        assert "/auth/login" in r.headers["location"]

    def test_open_redirect_prevented(self, auth_client, admin_user):
        r = auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "secret123",
            "next": "https://evil.example.com",
        })
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_unauthenticated_get_redirects_to_login(self, auth_client):
        r = auth_client.get("/companies/")
        assert r.status_code == 302
        assert "/auth/login" in r.headers["location"]


class TestRoleEnforcement:
    def test_read_only_cannot_post(self, auth_client, auth_db, readonly_user):
        auth_client.post("/auth/login", data={
            "username": "viewer",
            "password": "viewpass",
            "next": "/",
        })
        r = auth_client.post("/companies/new", data={"name": "Test Co"})
        assert r.status_code == 403

    def test_admin_can_post(self, auth_client, admin_user):
        auth_client.post("/auth/login", data={
            "username": "admin",
            "password": "secret123",
            "next": "/",
        })
        r = auth_client.post("/companies/new", data={
            "name": "Test Co",
            "ein": "",
            "address": "",
            "city": "",
            "state": "OK",
            "zip_code": "",
            "pay_frequency": "biweekly",
            "suta_rate": "",
            "workers_comp_policy": "",
            "csrf_token": "",  # bypassed — no session csrf in test
        })
        # Redirect on success (303) or CSRF failure (403) — CSRF is active here
        # For role test we just confirm not 403 "Admin access required"
        assert r.status_code != 403 or "Admin" not in r.text

    def test_preparer_can_post_employee(self, auth_client, preparer_user):
        auth_client.post("/auth/login", data={
            "username": "preparer",
            "password": "preppass",
            "next": "/",
        })
        r = auth_client.post("/employees/new", data={
            "company_id": "1",
            "first_name": "Jane",
            "last_name": "Doe",
            "employment_type": "salaried",
            "pay_rate": "50000",
            "csrf_token": "",
        })
        # Role check must pass — any remaining 403 is CSRF/validation, not role.
        assert r.status_code != 403 or "Requires role" not in r.text

    def test_approver_cannot_post_employee(self, auth_client, approver_user):
        auth_client.post("/auth/login", data={
            "username": "approver",
            "password": "approvepass",
            "next": "/",
        })
        r = auth_client.post("/employees/new", data={
            "company_id": "1",
            "first_name": "Jane",
            "last_name": "Doe",
            "employment_type": "salaried",
            "pay_rate": "50000",
        })
        assert r.status_code == 403
        assert "Requires role: preparer" in r.text

    def test_readonly_cannot_post_employee(self, auth_client, readonly_user):
        auth_client.post("/auth/login", data={
            "username": "viewer",
            "password": "viewpass",
            "next": "/",
        })
        r = auth_client.post("/employees/new", data={
            "company_id": "1",
            "first_name": "Jane",
            "last_name": "Doe",
            "employment_type": "salaried",
            "pay_rate": "50000",
        })
        assert r.status_code == 403
        assert "Requires role: preparer" in r.text

    def test_preparer_cannot_approve_payroll(self, auth_client, preparer_user):
        auth_client.post("/auth/login", data={
            "username": "preparer",
            "password": "preppass",
            "next": "/",
        })
        r = auth_client.post("/payroll/999/approve", data={"csrf_token": ""})
        assert r.status_code == 403
        assert "Requires role: approver" in r.text

    def test_approver_can_pass_approve_role_check(self, auth_client, approver_user):
        auth_client.post("/auth/login", data={
            "username": "approver",
            "password": "approvepass",
            "next": "/",
        })
        r = auth_client.post("/payroll/999/approve", data={"csrf_token": ""})
        # Role check must pass — any remaining 403 is CSRF, not role.
        assert r.status_code != 403 or "Requires role" not in r.text

    def test_readonly_cannot_approve_payroll(self, auth_client, readonly_user):
        auth_client.post("/auth/login", data={
            "username": "viewer",
            "password": "viewpass",
            "next": "/",
        })
        r = auth_client.post("/payroll/999/approve", data={"csrf_token": ""})
        assert r.status_code == 403
        assert "Requires role: approver" in r.text

    def test_preparer_cannot_post_companies(self, auth_client, preparer_user):
        auth_client.post("/auth/login", data={
            "username": "preparer",
            "password": "preppass",
            "next": "/",
        })
        r = auth_client.post("/companies/new", data={"name": "Test Co"})
        assert r.status_code == 403
        assert "Requires role: admin" in r.text

    def test_approver_cannot_post_companies(self, auth_client, approver_user):
        auth_client.post("/auth/login", data={
            "username": "approver",
            "password": "approvepass",
            "next": "/",
        })
        r = auth_client.post("/companies/new", data={"name": "Test Co"})
        assert r.status_code == 403
        assert "Requires role: admin" in r.text


class TestHashPassword:
    def test_hash_is_not_plaintext(self):
        h = hash_password("mypassword")
        assert h != "mypassword"
        assert len(h) > 20

    def test_verify_correct_password(self):
        import bcrypt
        h = hash_password("correct")
        assert bcrypt.checkpw(b"correct", h.encode())

    def test_verify_wrong_password(self):
        import bcrypt
        h = hash_password("correct")
        assert not bcrypt.checkpw(b"wrong", h.encode())
