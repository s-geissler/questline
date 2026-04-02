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
    return user, response.headers.get("set-cookie").split(";", 1)[0]


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
