from starlette.responses import RedirectResponse


def request_with_cookie(path="/", cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return {"type": "http", "method": "GET", "path": path, "headers": headers}


def register_and_cookie(main, db, email, display_name):
    response = main.Response()
    user = main.auth_register(
        main.RegisterRequest(
            email=email,
            password="supersecret",
            display_name=display_name,
        ),
        response,
        db,
    )
    cookie_header = response.headers.get("set-cookie")
    if cookie_header:
        return user, cookie_header.split(";", 1)[0]

    admin = db.query(main.models.User).filter(main.models.User.role == "admin").order_by(main.models.User.id).first()
    admin_response = main.Response()
    main.auth_login(main.LoginRequest(email=admin.email, password="supersecret"), admin_response, db)
    admin_cookie = admin_response.headers.get("set-cookie").split(";", 1)[0]
    main.update_admin_user(
        user["id"],
        main.AdminUserUpdate(is_active=True),
        main.Request(request_with_cookie(path=f"/api/admin/users/{user['id']}", cookie=admin_cookie)),
        db,
    )
    login_response = main.Response()
    main.auth_login(main.LoginRequest(email=email, password="supersecret"), login_response, db)
    return user, login_response.headers.get("set-cookie").split(";", 1)[0]


def test_first_registered_user_becomes_admin(app_env):
    main = app_env["main"]
    db = app_env["db"]

    user, _ = register_and_cookie(main, db, "admin@example.com", "Admin")

    assert user["role"] == "admin"


def test_admin_can_access_all_hubs_without_membership(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin, admin_cookie = register_and_cookie(main, db, "admin2@example.com", "Admin")
    owner, owner_cookie = register_and_cookie(main, db, "owner2@example.com", "Owner")

    board = main.create_board(
        main.BoardCreate(name="Foreign Hub"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )

    boards = main.get_boards(main.Request(request_with_cookie(cookie=admin_cookie)), db)
    assert any(entry["id"] == board["id"] and entry["role"] == "admin" for entry in boards)

    page = main.board_page(
        main.Request(request_with_cookie(path=f"/board/{board['id']}", cookie=admin_cookie)),
        board["id"],
        db,
    )
    assert page.status_code == 200
    assert page.context["board_role"] == "admin"
    assert admin["role"] == "admin"


def test_admin_page_requires_admin_and_lists_users(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "admin3@example.com", "Admin")
    user, user_cookie = register_and_cookie(main, db, "user3@example.com", "User")

    page = main.admin_page(
        main.Request(request_with_cookie(path="/admin", cookie=admin_cookie)),
        db,
    )
    assert page.status_code == 200

    users = main.get_admin_users(main.Request(request_with_cookie(path="/api/admin/users", cookie=admin_cookie)), db)
    assert any(entry["email"] == "user3@example.com" and entry["role"] == "user" for entry in users)

    try:
        main.admin_page(
            main.Request(request_with_cookie(path="/admin", cookie=user_cookie)),
            db,
        )
        assert False, "Expected non-admin admin page access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    redirect = main.admin_page(main.Request(request_with_cookie(path="/admin")), db)
    assert isinstance(redirect, RedirectResponse)
    assert redirect.status_code == 303

    assert user["role"] == "user"


def test_admin_can_promote_users_and_cannot_remove_last_admin(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin, admin_cookie = register_and_cookie(main, db, "admin4@example.com", "Admin")
    user, user_cookie = register_and_cookie(main, db, "user4@example.com", "User")

    updated = main.update_admin_user(
        user["id"],
        main.AdminUserUpdate(role="admin"),
        main.Request(request_with_cookie(path=f"/api/admin/users/{user['id']}", cookie=admin_cookie)),
        db,
    )
    assert updated["role"] == "admin"

    updated_self = main.update_admin_user(
        admin["id"],
        main.AdminUserUpdate(role="user"),
        main.Request(request_with_cookie(path=f"/api/admin/users/{admin['id']}", cookie=admin_cookie)),
        db,
    )
    assert updated_self["role"] == "user"

    try:
        main.update_admin_user(
            user["id"],
            main.AdminUserUpdate(role="user"),
            main.Request(request_with_cookie(path=f"/api/admin/users/{user['id']}", cookie=user_cookie)),
            db,
        )
        assert False, "Expected last admin downgrade to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_last_admin_cannot_demote_self(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin, admin_cookie = register_and_cookie(main, db, "admin5@example.com", "Admin")

    try:
        main.update_admin_user(
            admin["id"],
            main.AdminUserUpdate(role="user"),
            main.Request(request_with_cookie(path=f"/api/admin/users/{admin['id']}", cookie=admin_cookie)),
            db,
        )
        assert False, "Expected last admin downgrade to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_admin_can_update_instance_settings_and_board_defaults(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin, admin_cookie = register_and_cookie(main, db, "admin6@example.com", "Admin")

    settings = main.get_admin_settings(
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )
    assert settings["registration_enabled"] is True
    assert settings["default_board_color"]
    assert settings["new_accounts_active_by_default"] is False
    assert settings["instance_theme_color"] == "#1d4ed8"
    assert settings["recurrence_worker_interval_seconds"] == 60

    updated = main.update_admin_settings(
        main.AdminSettingsUpdate(
            registration_enabled=False,
            default_board_color="#10b981",
            new_accounts_active_by_default=False,
            instance_theme_color="#0f766e",
            recurrence_worker_interval_seconds=45,
        ),
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )
    assert updated["registration_enabled"] is False
    assert updated["default_board_color"] == "#10b981"
    assert updated["new_accounts_active_by_default"] is False
    assert updated["instance_theme_color"] == "#0f766e"
    assert updated["recurrence_worker_interval_seconds"] == 45

    board = main.create_board(
        main.BoardCreate(name="Green Hub"),
        db,
        main.Request(request_with_cookie(path="/api/boards", cookie=admin_cookie)),
    )
    assert board["color"] == "#10b981"
    assert admin["role"] == "admin"


def test_registration_can_be_disabled_after_first_user(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "admin7@example.com", "Admin")

    main.update_admin_settings(
        main.AdminSettingsUpdate(
            registration_enabled=False,
            default_board_color="#2563eb",
            new_accounts_active_by_default=True,
            instance_theme_color="#1d4ed8",
            recurrence_worker_interval_seconds=60,
        ),
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )

    try:
        main.auth_register(
            main.RegisterRequest(
                email="blocked@example.com",
                password="supersecret",
                display_name="Blocked",
            ),
            main.Response(),
            db,
        )
        assert False, "Expected registration to be disabled"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_admin_settings_require_admin(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "admin8@example.com", "Admin")
    _, user_cookie = register_and_cookie(main, db, "user8@example.com", "User")

    settings = main.get_admin_settings(
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )
    assert settings["registration_enabled"] is True
    assert settings["recurrence_worker_interval_seconds"] == 60

    try:
        main.get_admin_settings(
            main.Request(request_with_cookie(path="/api/admin/settings", cookie=user_cookie)),
            db,
        )
        assert False, "Expected non-admin settings access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_admin_settings_validate_recurrence_worker_interval(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "admin11@example.com", "Admin")

    try:
        main.update_admin_settings(
            main.AdminSettingsUpdate(
                registration_enabled=True,
                default_board_color="#2563eb",
                new_accounts_active_by_default=True,
                instance_theme_color="#1d4ed8",
                recurrence_worker_interval_seconds=1,
            ),
            main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
            db,
        )
        assert False, "Expected too-small recurrence worker interval to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_admin_can_activate_and_deactivate_accounts(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "admin9@example.com", "Admin")
    user, user_cookie = register_and_cookie(main, db, "user9@example.com", "User")

    deactivated = main.update_admin_user(
        user["id"],
        main.AdminUserUpdate(is_active=False),
        main.Request(request_with_cookie(path=f"/api/admin/users/{user['id']}", cookie=admin_cookie)),
        db,
    )
    assert deactivated["is_active"] is False

    try:
        main.auth_me(main.Request(request_with_cookie(path="/api/auth/me", cookie=user_cookie)), db)
        assert False, "Expected deactivated session to be blocked"
    except main.HTTPException as exc:
        assert exc.status_code == 401

    reactivated = main.update_admin_user(
        user["id"],
        main.AdminUserUpdate(is_active=True),
        main.Request(request_with_cookie(path=f"/api/admin/users/{user['id']}", cookie=admin_cookie)),
        db,
    )
    assert reactivated["is_active"] is True


def test_admin_cannot_deactivate_self(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin, admin_cookie = register_and_cookie(main, db, "admin10@example.com", "Admin")

    try:
        main.update_admin_user(
            admin["id"],
            main.AdminUserUpdate(is_active=False),
            main.Request(request_with_cookie(path=f"/api/admin/users/{admin['id']}", cookie=admin_cookie)),
            db,
        )
        assert False, "Expected self-deactivation to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 400
