import importlib
import json
import sys

from starlette.requests import Request


def request_with_cookie(path="/", method="GET", cookie=None, client_host="127.0.0.1"):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": (client_host, 12345),
        }
    )


def audit_events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == "questline.audit"]


def test_auth_events_are_logged(app_env, caplog):
    main = app_env["main"]
    db = app_env["db"]
    caplog.set_level("INFO", logger="questline.audit")

    register_response = main.Response()
    user = main.auth_register(
        main.RegisterRequest(
            email="audit@example.com",
            password="supersecret",
            display_name="Audit User",
        ),
        register_response,
        db,
        request_with_cookie(path="/api/auth/register", method="POST"),
    )
    login_response = main.Response()
    logged_in = main.auth_login(
        main.LoginRequest(email="audit@example.com", password="supersecret"),
        login_response,
        db,
        request_with_cookie(path="/api/auth/login", method="POST"),
    )
    session_cookie = login_response.headers.get("set-cookie").split(";", 1)[0]
    profile_response = main.Response()
    main.auth_update_profile(
        main.ProfileUpdate(display_name="Audit User", password="newsecret1"),
        request_with_cookie(path="/api/auth/profile", method="PUT", cookie=session_cookie),
        profile_response,
        db,
    )
    new_session_cookie = profile_response.headers.get("set-cookie").split(";", 1)[0]
    main.auth_logout(
        request_with_cookie(path="/api/auth/logout", method="POST", cookie=new_session_cookie),
        main.Response(),
        db,
    )

    events = audit_events(caplog)
    assert any(event["event"] == "registration_succeeded" and event["target_user_id"] == user["id"] for event in events)
    assert any(event["event"] == "login_succeeded" and event["target_user_id"] == logged_in["id"] for event in events)
    assert any(event["event"] == "password_changed" and event["actor_user_id"] == user["id"] for event in events)
    assert any(event["event"] == "logout_succeeded" and event["actor_user_id"] == user["id"] for event in events)


def test_login_failure_and_admin_update_are_logged(app_env, caplog):
    main = app_env["main"]
    db = app_env["db"]
    caplog.set_level("INFO", logger="questline.audit")

    admin_response = main.Response()
    admin = main.auth_register(
        main.RegisterRequest(
            email="admin-audit@example.com",
            password="supersecret",
            display_name="Admin",
        ),
        admin_response,
        db,
        request_with_cookie(path="/api/auth/register", method="POST"),
    )
    user_response = main.Response()
    user = main.auth_register(
        main.RegisterRequest(
            email="user-audit@example.com",
            password="supersecret",
            display_name="User",
        ),
        user_response,
        db,
        request_with_cookie(path="/api/auth/register", method="POST"),
    )
    admin_cookie = admin_response.headers.get("set-cookie").split(";", 1)[0]

    try:
        main.auth_login(
            main.LoginRequest(email="user-audit@example.com", password="wrongpass"),
            main.Response(),
            db,
            request_with_cookie(path="/api/auth/login", method="POST"),
        )
        assert False, "Expected invalid login to fail"
    except main.HTTPException:
        pass

    updated = main.update_admin_user(
        user["id"],
        main.AdminUserUpdate(role="admin", is_active=True),
        request_with_cookie(path=f"/api/admin/users/{user['id']}", method="PUT", cookie=admin_cookie),
        db,
    )

    events = audit_events(caplog)
    failed_login = next(event for event in events if event["event"] == "login_failed")
    admin_update = next(event for event in events if event["event"] == "admin_user_updated")

    assert failed_login["outcome"] == "failure"
    assert failed_login["reason"] == "invalid_credentials"
    assert failed_login["email"] == "user-audit@example.com"
    assert admin_update["actor_user_id"] == admin["id"]
    assert admin_update["target_user_id"] == updated["id"]
    assert admin_update["previous_role"] == "user"
    assert admin_update["new_role"] == "admin"


def test_password_recovery_request_is_audited(app_env, caplog):
    main = app_env["main"]
    db = app_env["db"]
    caplog.set_level("INFO", logger="questline.audit")

    user = main.auth_register(
        main.RegisterRequest(
            email="recovery-audit@example.com",
            password="supersecret",
            display_name="Recovery Audit",
        ),
        main.Response(),
        db,
        request_with_cookie(path="/api/auth/register", method="POST"),
    )

    main.auth_password_recovery_request(
        main.PasswordRecoveryRequest(email=user["email"]),
        db,
        request_with_cookie(path="/api/auth/password-recovery-request", method="POST"),
    )

    events = audit_events(caplog)
    recovery_request = next(event for event in events if event["event"] == "password_recovery_requested")
    assert recovery_request["target_user_id"] == user["id"]
    assert recovery_request["email"] == user["email"]


def test_audit_log_path_writes_json_lines(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    audit_log_path = tmp_path / "audit.log"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUESTLINE_ENV", "development")
    monkeypatch.setenv("QUESTLINE_ALLOW_INSECURE_COOKIES", "true")
    monkeypatch.setenv("QUESTLINE_AUDIT_LOG_PATH", str(audit_log_path))

    for module_name in ("main", "models", "database", "authz", "filters_logic"):
        sys.modules.pop(module_name, None)

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    db = database.SessionLocal()
    try:
        main.auth_register(
            main.RegisterRequest(
                email="file-audit@example.com",
                password="supersecret",
                display_name="File Audit",
            ),
            main.Response(),
            db,
            request_with_cookie(path="/api/auth/register", method="POST"),
        )
        lines = audit_log_path.read_text().strip().splitlines()
        assert lines
        payload = json.loads(lines[-1])
        assert payload["event"] == "registration_succeeded"
        assert payload["email"] == "file-audit@example.com"
    finally:
        db.close()
        database.engine.dispose()
