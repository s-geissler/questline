import importlib
import sys

from starlette.requests import Request
from starlette.responses import RedirectResponse


def request_with_cookie(cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


def test_password_hash_round_trip(app_env):
    main = app_env["main"]
    password_hash = main.hash_password("supersecret")

    assert password_hash != "supersecret"
    assert main.verify_password("supersecret", password_hash) is True
    assert main.verify_password("wrongpass", password_hash) is False


def test_register_sets_session_and_returns_current_user(app_env):
    main = app_env["main"]
    db = app_env["db"]
    response = main.Response()

    registered = main.auth_register(
        main.RegisterRequest(
            email="user@example.com",
            password="supersecret",
            display_name="Quest User",
        ),
        response,
        db,
    )
    assert registered == {
        "id": 1,
        "email": "user@example.com",
        "display_name": "Quest User",
        "role": "admin",
        "is_active": True,
    }

    cookie_header = response.headers.get("set-cookie")
    assert cookie_header
    session_token = cookie_header.split(";", 1)[0]

    me = main.auth_me(request_with_cookie(session_token), db)
    assert me == registered


def test_register_rejects_duplicate_email(app_env):
    main = app_env["main"]
    db = app_env["db"]

    main.auth_register(
        main.RegisterRequest(
            email="duplicate@example.com",
            password="supersecret",
            display_name="Dup",
        ),
        main.Response(),
        db,
    )

    try:
        main.auth_register(
            main.RegisterRequest(
                email="duplicate@example.com",
                password="supersecret",
                display_name="Dup",
            ),
            main.Response(),
            db,
        )
        assert False, "Expected duplicate registration to fail"
    except main.HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "Registration failed"


def test_login_and_logout_flow(app_env):
    main = app_env["main"]
    db = app_env["db"]

    main.auth_register(
        main.RegisterRequest(
            email="login@example.com",
            password="supersecret",
            display_name="Login User",
        ),
        main.Response(),
        db,
    )

    try:
        main.auth_login(
            main.LoginRequest(email="login@example.com", password="wrongpass"),
            main.Response(),
            db,
        )
        assert False, "Expected invalid login to fail"
    except main.HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Invalid email or password"

    login_response = main.Response()
    logged_in = main.auth_login(
        main.LoginRequest(email="login@example.com", password="supersecret"),
        login_response,
        db,
    )
    assert logged_in["email"] == "login@example.com"

    session_token = login_response.headers.get("set-cookie").split(";", 1)[0]
    assert main.auth_me(request_with_cookie(session_token), db)["email"] == "login@example.com"

    logout_response = main.Response()
    logout = main.auth_logout(request_with_cookie(session_token), logout_response, db)
    assert logout == {"ok": True}

    try:
        main.auth_me(request_with_cookie(session_token), db)
        assert False, "Expected logged out session to be invalid"
    except main.HTTPException as exc:
        assert exc.status_code == 401


def test_auth_pages_redirect_authenticated_users(app_env):
    main = app_env["main"]
    db = app_env["db"]
    response = main.Response()
    main.auth_register(
        main.RegisterRequest(
            email="pages@example.com",
            password="supersecret",
            display_name="Pages User",
        ),
        response,
        db,
    )
    session_token = response.headers.get("set-cookie").split(";", 1)[0]
    request = request_with_cookie(session_token)

    login_page = main.login_page(request, db)
    register_page = main.register_page(request, db)

    assert isinstance(login_page, RedirectResponse)
    assert login_page.status_code == 303
    assert login_page.headers["location"] == "/"
    assert isinstance(register_page, RedirectResponse)
    assert register_page.status_code == 303
    assert register_page.headers["location"] == "/"


def test_profile_update_changes_display_name_and_password(app_env):
    main = app_env["main"]
    db = app_env["db"]
    response = main.Response()
    main.auth_register(
        main.RegisterRequest(
            email="profile@example.com",
            password="supersecret",
            display_name="Profile User",
        ),
        response,
        db,
    )
    session_token = response.headers.get("set-cookie").split(";", 1)[0]
    request = request_with_cookie(session_token)
    update_response = main.Response()

    updated = main.auth_update_profile(
        main.ProfileUpdate(display_name="Renamed User", password="newsecret1"),
        request,
        update_response,
        db,
    )
    assert updated["display_name"] == "Renamed User"
    new_session_token = update_response.headers.get("set-cookie").split(";", 1)[0]
    assert main.auth_me(request_with_cookie(new_session_token), db)["display_name"] == "Renamed User"

    try:
        main.auth_me(request, db)
        assert False, "Expected prior session to be invalid after password change"
    except main.HTTPException as exc:
        assert exc.status_code == 401

    try:
        main.auth_login(
            main.LoginRequest(email="profile@example.com", password="supersecret"),
            main.Response(),
            db,
        )
        assert False, "Expected old password to fail after profile update"
    except main.HTTPException as exc:
        assert exc.status_code == 401

    relogin = main.auth_login(
        main.LoginRequest(email="profile@example.com", password="newsecret1"),
        main.Response(),
        db,
    )
    assert relogin["display_name"] == "Renamed User"


def test_profile_update_requires_valid_display_name(app_env):
    main = app_env["main"]
    db = app_env["db"]
    response = main.Response()
    main.auth_register(
        main.RegisterRequest(
            email="invalid-profile@example.com",
            password="supersecret",
            display_name="Profile User",
        ),
        response,
        db,
    )
    session_token = response.headers.get("set-cookie").split(";", 1)[0]

    try:
        main.auth_update_profile(
            main.ProfileUpdate(display_name="   ", password=None),
            request_with_cookie(session_token),
            main.Response(),
            db,
        )
        assert False, "Expected blank display name to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_inactive_new_accounts_require_admin_activation(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin_response = main.Response()
    admin = main.auth_register(
        main.RegisterRequest(
            email="activation-admin@example.com",
            password="supersecret",
            display_name="Admin",
        ),
        admin_response,
        db,
    )
    admin_cookie = admin_response.headers.get("set-cookie").split(";", 1)[0]

    main.update_admin_settings(
        main.AdminSettingsUpdate(
            registration_enabled=True,
            default_board_color="#2563eb",
            new_accounts_active_by_default=False,
            instance_theme_color="#1d4ed8",
        ),
        request_with_cookie(admin_cookie),
        db,
    )

    response = main.Response()
    registered = main.auth_register(
        main.RegisterRequest(
            email="inactive@example.com",
            password="supersecret",
            display_name="Inactive User",
        ),
        response,
        db,
    )
    assert registered["is_active"] is False
    assert response.headers.get("set-cookie") is None

    try:
        main.auth_login(
            main.LoginRequest(email="inactive@example.com", password="supersecret"),
            main.Response(),
            db,
        )
        assert False, "Expected inactive login to be blocked"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    activated = main.update_admin_user(
        registered["id"],
        main.AdminUserUpdate(is_active=True),
        request_with_cookie(admin_cookie),
        db,
    )
    assert activated["is_active"] is True

    relogin = main.auth_login(
        main.LoginRequest(email="inactive@example.com", password="supersecret"),
        main.Response(),
        db,
    )
    assert relogin["is_active"] is True


def test_session_cookie_flags_can_be_configured(tmp_path, monkeypatch):
    db_path = tmp_path / "cookie-test.db"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUESTLINE_SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("QUESTLINE_SESSION_COOKIE_SAMESITE", "strict")

    for module_name in ("main", "models", "database", "authz"):
        sys.modules.pop(module_name, None)

    main = importlib.import_module("main")
    db = importlib.import_module("database").SessionLocal()
    try:
        response = main.Response()
        main.auth_register(
            main.RegisterRequest(
                email="cookie@example.com",
                password="supersecret",
                display_name="Cookie User",
            ),
            response,
            db,
        )
        cookie_header = response.headers.get("set-cookie")
        assert "Secure" in cookie_header
        assert "SameSite=strict" in cookie_header
    finally:
        db.close()
