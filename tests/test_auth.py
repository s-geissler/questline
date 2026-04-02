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
        assert exc.detail == "Email already registered"


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
