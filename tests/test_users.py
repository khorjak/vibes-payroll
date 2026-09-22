"""
Tests for user management (routers/users.py): CRUD, access control, lockout guard.
"""
from models.user import User
from models.audit import AuditLog
from models.user_company import UserCompany


class TestUserCrud:
    """CRUD mechanics via the `client` fixture (admin dependency overrides)."""

    def test_create_user_persists_hashed_password(self, client, db):
        r = client.post("/users/new", data={
            "username": "newpreparer",
            "password": "supersecret1",
            "role": "preparer",
            "csrf_token": "",
        })
        assert r.status_code == 303
        user = db.query(User).filter(User.username == "newpreparer").first()
        assert user is not None
        assert user.role == "preparer"
        assert user.is_active is True
        assert user.hashed_password != "supersecret1"

    def test_create_user_logs_audit_entry(self, client, db):
        client.post("/users/new", data={
            "username": "audited",
            "password": "supersecret1",
            "role": "read_only",
            "csrf_token": "",
        })
        entry = db.query(AuditLog).filter(
            AuditLog.table_name == "users", AuditLog.action == "insert",
        ).first()
        assert entry is not None

    def test_create_user_duplicate_username_race_returns_422_not_500(self, client, db, monkeypatch):
        """
        Simulates two concurrent creates: the pre-check .first() passes (no
        row yet), but the DB's unique constraint still catches the collision
        on flush. Should be handled as a form error, not surfaced as a 500.
        """
        from sqlalchemy.exc import IntegrityError

        original_flush = db.flush

        def _raise_only_when_inserting_user(*args, **kwargs):
            # Autoflush fires on every query (e.g. the route's own uniqueness
            # check) — only fail the flush that actually persists the new user.
            if any(isinstance(obj, User) for obj in db.new):
                raise IntegrityError("UNIQUE constraint failed: users.username", None, None)
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", _raise_only_when_inserting_user)
        r = client.post("/users/new", data={
            "username": "raceduser", "password": "supersecret1", "role": "preparer", "csrf_token": "",
        })
        assert r.status_code == 422
        assert "already taken" in r.text

    def test_create_user_duplicate_username_rejected(self, client, db):
        client.post("/users/new", data={
            "username": "dupe", "password": "supersecret1", "role": "preparer", "csrf_token": "",
        })
        r = client.post("/users/new", data={
            "username": "dupe", "password": "supersecret1", "role": "preparer", "csrf_token": "",
        })
        assert r.status_code == 422
        assert db.query(User).filter(User.username == "dupe").count() == 1

    def test_create_user_short_password_rejected(self, client, db):
        r = client.post("/users/new", data={
            "username": "shortpw", "password": "short", "role": "preparer", "csrf_token": "",
        })
        assert r.status_code == 422
        assert db.query(User).filter(User.username == "shortpw").first() is None

    def test_edit_user_role_and_active(self, client, db):
        user = User(username="editme", hashed_password="x", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        r = client.post(f"/users/{user.id}/edit", data={
            "role": "approver", "is_active": "on", "csrf_token": "",
        })
        assert r.status_code == 303
        db.refresh(user)
        assert user.role == "approver"
        assert user.is_active is True

    def test_reset_password_persists_new_hash(self, client, db):
        user = User(username="resetme", hashed_password="oldhash", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        r = client.post(f"/users/{user.id}/reset-password", data={
            "new_password": "brandnewpass1",
            "confirm_password": "brandnewpass1",
            "csrf_token": "",
        })
        assert r.status_code == 303
        db.refresh(user)
        assert user.hashed_password != "oldhash"
        assert user.hashed_password != "brandnewpass1"

    def test_reset_password_mismatch_rejected(self, client, db):
        user = User(username="mismatch", hashed_password="oldhash", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        r = client.post(f"/users/{user.id}/reset-password", data={
            "new_password": "brandnewpass1",
            "confirm_password": "different1",
            "csrf_token": "",
        })
        assert r.status_code == 422
        db.refresh(user)
        assert user.hashed_password == "oldhash"


class TestUserLockoutGuard:
    def test_cannot_demote_last_active_admin(self, client, db):
        only_admin = User(username="soleadmin", hashed_password="x", role="admin", is_active=True)
        db.add(only_admin)
        db.commit()
        db.refresh(only_admin)

        r = client.post(f"/users/{only_admin.id}/edit", data={
            "role": "preparer", "is_active": "on", "csrf_token": "",
        })
        assert r.status_code == 422
        db.refresh(only_admin)
        assert only_admin.role == "admin"

    def test_cannot_deactivate_last_active_admin(self, client, db):
        only_admin = User(username="soleadmin2", hashed_password="x", role="admin", is_active=True)
        db.add(only_admin)
        db.commit()
        db.refresh(only_admin)

        r = client.post(f"/users/{only_admin.id}/edit", data={
            "role": "admin", "is_active": "", "csrf_token": "",
        })
        assert r.status_code == 422
        db.refresh(only_admin)
        assert only_admin.is_active is True

    def test_can_demote_admin_when_another_admin_active(self, client, db):
        db.add(User(username="otheradmin", hashed_password="x", role="admin", is_active=True))
        target = User(username="demoteme", hashed_password="x", role="admin", is_active=True)
        db.add(target)
        db.commit()
        db.refresh(target)

        r = client.post(f"/users/{target.id}/edit", data={
            "role": "preparer", "is_active": "on", "csrf_token": "",
        })
        assert r.status_code == 303
        db.refresh(target)
        assert target.role == "preparer"


class TestUserManagementAccessControl:
    """Only admin can reach any /users/* route — verified with real auth (no overrides)."""

    def test_admin_can_list_users(self, auth_client, admin_user):
        auth_client.post("/auth/login", data={
            "username": "admin", "password": "secret123", "next": "/",
        })
        r = auth_client.get("/users/")
        assert r.status_code == 200

    def test_preparer_cannot_list_users(self, auth_client, preparer_user):
        auth_client.post("/auth/login", data={
            "username": "preparer", "password": "preppass", "next": "/",
        })
        r = auth_client.get("/users/")
        assert r.status_code == 403

    def test_approver_cannot_list_users(self, auth_client, approver_user):
        auth_client.post("/auth/login", data={
            "username": "approver", "password": "approvepass", "next": "/",
        })
        r = auth_client.get("/users/")
        assert r.status_code == 403

    def test_readonly_cannot_list_users(self, auth_client, readonly_user):
        auth_client.post("/auth/login", data={
            "username": "viewer", "password": "viewpass", "next": "/",
        })
        r = auth_client.get("/users/")
        assert r.status_code == 403

    def test_preparer_cannot_create_user(self, auth_client, preparer_user):
        auth_client.post("/auth/login", data={
            "username": "preparer", "password": "preppass", "next": "/",
        })
        r = auth_client.post("/users/new", data={
            "username": "sneaky", "password": "supersecret1", "role": "admin",
        })
        assert r.status_code == 403


class TestCompanyAssignment:
    def test_create_user_with_companies(self, client, db, company, second_company):
        client.post("/users/new", data={
            "username": "scoped", "password": "longenough1", "role": "preparer",
            "company_ids": [str(company.id)],
        })
        user = db.query(User).filter(User.username == "scoped").first()
        rows = db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
        assert [r.company_id for r in rows] == [company.id]

    def test_admin_gets_no_assignment_rows(self, client, db, company):
        client.post("/users/new", data={
            "username": "newboss", "password": "longenough1", "role": "admin",
            "company_ids": [str(company.id)],
        })
        user = db.query(User).filter(User.username == "newboss").first()
        assert db.query(UserCompany).filter(UserCompany.user_id == user.id).count() == 0

    def test_edit_adds_and_removes_assignments(self, client, db, company, second_company):
        user = User(username="shifter", hashed_password="x", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(UserCompany(user_id=user.id, company_id=company.id))
        db.commit()

        client.post(f"/users/{user.id}/edit", data={
            "role": "preparer", "is_active": "on",
            "company_ids": [str(second_company.id)],
        })
        rows = db.query(UserCompany).filter(UserCompany.user_id == user.id).all()
        assert [r.company_id for r in rows] == [second_company.id]

    def test_assignment_changes_are_audit_logged(self, client, db, company):
        client.post("/users/new", data={
            "username": "audited", "password": "longenough1", "role": "preparer",
            "company_ids": [str(company.id)],
        })
        rows = db.query(AuditLog).filter(AuditLog.table_name == "user_companies").all()
        assert len(rows) == 1
        assert rows[0].action == "insert"

    def test_revoking_access_is_audit_logged(self, client, db, company):
        user = User(username="revoked", hashed_password="x", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(UserCompany(user_id=user.id, company_id=company.id))
        db.commit()

        client.post(f"/users/{user.id}/edit", data={"role": "preparer", "is_active": "on"})
        rows = db.query(AuditLog).filter(
            AuditLog.table_name == "user_companies", AuditLog.action == "delete",
        ).all()
        assert len(rows) == 1

    def test_promoting_to_admin_drops_assignments_from_ui(self, client, db, company):
        """Admins bypass scope; the form's checkboxes are ignored for them."""
        user = User(username="promoted", hashed_password="x", role="preparer", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        client.post(f"/users/{user.id}/edit", data={
            "role": "admin", "is_active": "on", "company_ids": [str(company.id)],
        })
        assert db.query(UserCompany).filter(UserCompany.user_id == user.id).count() == 0
