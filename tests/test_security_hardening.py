from fastapi.testclient import TestClient


XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def test_authenticated_writes_require_csrf_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    register = client.post(
        "/api/auth/register",
        json={
            "email": "csrf-owner@example.com",
            "password": "supersecret",
            "display_name": "CSRF Owner",
        },
        headers=XHR_HEADERS,
    )
    assert register.status_code == 200

    csrf_token = client.cookies.get("questline_csrf")
    assert csrf_token

    create_board = client.post(
        "/api/boards",
        json={"name": "Secure Board"},
        headers={**XHR_HEADERS, "X-CSRF-Token": csrf_token},
    )
    assert create_board.status_code == 200

    missing_csrf = client.put(
        "/api/auth/profile",
        json={"display_name": "Still Owner", "password": ""},
        headers=XHR_HEADERS,
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "CSRF validation failed"

    valid_csrf = client.put(
        "/api/auth/profile",
        json={"display_name": "Updated Owner", "password": ""},
        headers={**XHR_HEADERS, "X-CSRF-Token": csrf_token},
    )
    assert valid_csrf.status_code == 200
    assert valid_csrf.json()["display_name"] == "Updated Owner"


def test_login_requires_xhr_header_and_is_rate_limited(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    register = client.post(
        "/api/auth/register",
        json={
            "email": "limited@example.com",
            "password": "supersecret",
            "display_name": "Limited User",
        },
        headers=XHR_HEADERS,
    )
    assert register.status_code == 200

    client.cookies.clear()

    no_xhr = client.post(
        "/api/auth/login",
        json={"email": "limited@example.com", "password": "supersecret"},
    )
    assert no_xhr.status_code == 403
    assert no_xhr.json()["detail"] == "CSRF validation failed"

    for _ in range(5):
        res = client.post(
            "/api/auth/login",
            json={"email": "limited@example.com", "password": "wrongpass"},
            headers=XHR_HEADERS,
        )
        assert res.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"email": "limited@example.com", "password": "wrongpass"},
        headers=XHR_HEADERS,
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many login attempts. Try again later."


def test_duplicate_registration_is_generic(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    first = client.post(
        "/api/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "supersecret",
            "display_name": "First",
        },
        headers=XHR_HEADERS,
    )
    assert first.status_code == 200

    second = client.post(
        "/api/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "supersecret",
            "display_name": "Second",
        },
        headers=XHR_HEADERS,
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "Registration failed"
