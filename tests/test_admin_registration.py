import json

import pytest
from fastapi.testclient import TestClient


XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
USER_DATA = {"email": "new-user@example.com", "password": "new-user-password", "display_name": "New User"}


@pytest.fixture()
def admin_client(app_env):
    client = TestClient(app_env["main"].app)
    response = client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "admin-password", "display_name": "Admin"},
        headers=XHR_HEADERS,
    )
    assert response.status_code == 200
    headers = {**XHR_HEADERS, "X-CSRF-Token": client.cookies.get("questline_csrf")}
    settings = client.get("/api/admin/settings").json()
    settings.update(registration_enabled=False, new_accounts_active_by_default=False)
    assert client.put("/api/admin/settings", json=settings, headers=headers).status_code == 200
    return client, headers


@pytest.mark.parametrize("is_active", [None, False])
def test_admin_creates_accounts_with_registration_closed(app_env, admin_client, caplog, is_active):
    caplog.set_level("INFO", logger="questline.audit")
    client, headers = admin_client
    admin = client.get("/api/auth/me").json()
    data = {**USER_DATA, "email": "  NEW-USER@EXAMPLE.COM  ", "display_name": "  New User  ", "role": "admin"}
    if is_active is not None:
        data["is_active"] = is_active
    response = client.post("/api/admin/users", json=data, headers=headers)
    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "new-user@example.com"
    assert user["display_name"] == "New User"
    assert user["role"] == "user"
    assert user["is_active"] is (is_active is not False)
    assert "password" not in user and "password_hash" not in user
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").json() == admin

    models, db = app_env["models"], app_env["db"]
    row = db.get(models.User, user["id"])
    assert row.password_hash != USER_DATA["password"]
    assert app_env["main"].verify_password(USER_DATA["password"], row.password_hash)
    assert db.query(models.UserSession).filter_by(user_id=row.id).count() == 0
    assert db.query(models.BoardMembership).filter_by(user_id=row.id).count() == 0
    assert any(entry["id"] == row.id for entry in client.get("/api/admin/users").json())
    events = [json.loads(record.getMessage()) for record in caplog.records if record.name == "questline.audit"]
    event = next(event for event in events if event["event"] == "admin_user_created")
    assert event["actor_user_id"] == admin["id"]
    assert event["target_user_id"] == row.id
    assert USER_DATA["password"] not in json.dumps(events)

    other_client = TestClient(app_env["main"].app)
    login = other_client.post("/api/auth/login", json=USER_DATA, headers=XHR_HEADERS)
    assert login.status_code == (403 if is_active is False else 200)
    blocked = other_client.post(
        "/api/auth/register", json={**USER_DATA, "email": "public@example.com"}, headers=XHR_HEADERS
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Registration is currently disabled"


def test_admin_creation_normalizes_duplicates_and_defaults_display_name(app_env, admin_client):
    client, headers = admin_client
    data = {"email": "  NEW-USER@EXAMPLE.COM  ", "password": USER_DATA["password"]}
    response = client.post("/api/admin/users", json=data, headers=headers)
    assert response.status_code == 201
    assert response.json()["display_name"] == "new-user"
    duplicate = client.post("/api/admin/users", json=USER_DATA, headers=headers)
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "A user with that email already exists"
    assert app_env["db"].query(app_env["models"].User).count() == 2


def test_admin_creation_handles_concurrent_duplicate(app_env, admin_client, monkeypatch):
    from routes.admin import AdminUserCreate, create_admin_user

    client, _ = admin_client
    db, models = app_env["db"], app_env["models"]
    original_commit = db.commit

    def commit_after_concurrent_creation():
        with app_env["database"].SessionLocal() as concurrent_db:
            concurrent_db.add(models.User(
                email=USER_DATA["email"], display_name="Concurrent user", password_hash="existing-hash", role="user"
            ))
            concurrent_db.commit()
        original_commit()

    monkeypatch.setattr(db, "commit", commit_after_concurrent_creation)
    request = app_env["main"].Request({
        "type": "http", "method": "POST", "path": "/api/admin/users",
        "headers": [(b"cookie", f"questline_session={client.cookies.get('questline_session')}".encode())],
    })
    with pytest.raises(app_env["main"].HTTPException) as exc:
        create_admin_user(AdminUserCreate(**USER_DATA), request, db)
    assert exc.value.status_code == 400
    assert db.query(models.User).filter_by(email=USER_DATA["email"]).one().display_name == "Concurrent user"


@pytest.mark.parametrize(("changes", "status"), [
    ({"email": "invalid"}, 400),
    ({"email": "   "}, 400),
    ({"password": "short"}, 400),
    ({"password": "x" * 4097}, 422),
    ({"email": "x" * 256}, 422),
    ({"display_name": "x" * 121}, 422),
    ({"is_active": None}, 422),
])
def test_admin_creation_validates_before_inserting(app_env, admin_client, changes, status):
    client, headers = admin_client
    response = client.post("/api/admin/users", json={**USER_DATA, **changes}, headers=headers)
    assert response.status_code == status
    assert app_env["db"].query(app_env["models"].User).count() == 1


def test_admin_creation_requires_admin_and_csrf(app_env, admin_client):
    client, headers = admin_client
    assert client.post("/api/admin/users", json=USER_DATA, headers=XHR_HEADERS).status_code == 403
    assert client.post("/api/admin/users", json=USER_DATA, headers=headers).status_code == 201
    other_client = TestClient(app_env["main"].app)
    assert other_client.post("/api/admin/users", json=USER_DATA, headers=XHR_HEADERS).status_code == 403
    login = other_client.post("/api/auth/login", json=USER_DATA, headers=XHR_HEADERS)
    assert login.status_code == 200
    user_headers = {**XHR_HEADERS, "X-CSRF-Token": other_client.cookies.get("questline_csrf")}
    denied = other_client.post("/api/admin/users", json={**USER_DATA, "email": "forbidden@example.com"}, headers=user_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Admin access denied"
    assert app_env["db"].query(app_env["models"].User).count() == 2


def test_closed_registration_hides_links_and_form_and_can_be_reopened(admin_client):
    client, headers = admin_client
    client.cookies.clear()
    login = client.get("/login")
    assert login.status_code == 200
    assert 'href="/register"' not in login.text
    closed = client.get("/register")
    assert closed.status_code == 403
    assert "Registration closed" in closed.text
    assert 'href="/register"' not in closed.text
    assert 'id="register-email-input"' not in closed.text
    assert 'id="register-submit"' not in closed.text

    assert client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin-password"}, headers=XHR_HEADERS
    ).status_code == 200
    headers["X-CSRF-Token"] = client.cookies.get("questline_csrf")
    settings = client.get("/api/admin/settings").json()
    settings["registration_enabled"] = True
    assert client.put("/api/admin/settings", json=settings, headers=headers).status_code == 200
    client.cookies.clear()
    assert client.get("/login").text.count('href="/register"') == 2
    registration = client.get("/register")
    assert registration.status_code == 200
    assert 'id="register-email-input"' in registration.text


def test_first_account_setup_remains_available_with_registration_disabled(app_env):
    db = app_env["db"]
    db.add(app_env["models"].InstanceSetting(key="registration_enabled", value="false"))
    db.commit()
    client = TestClient(app_env["main"].app)
    assert client.get("/login").text.count('href="/register"') == 2
    assert client.get("/register").status_code == 200
    response = client.post("/api/auth/register", json=USER_DATA, headers=XHR_HEADERS)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    client.cookies.clear()
    assert 'href="/register"' not in client.get("/login").text
    assert client.get("/register").status_code == 403
