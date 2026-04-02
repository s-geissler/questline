from starlette.responses import RedirectResponse


def request_with_cookie(path="/", cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
    }


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
    cookie = response.headers.get("set-cookie").split(";", 1)[0]
    return user, cookie


def test_home_redirects_unauthenticated_users(app_env):
    main = app_env["main"]
    db = app_env["db"]
    request = main.Request(request_with_cookie())

    response = main.home(request, db)
    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_instance_theme_color_is_used_for_home(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "overview-admin@example.com", "Overview Admin")
    main.update_admin_settings(
        main.AdminSettingsUpdate(
            registration_enabled=True,
            default_board_color="#2563eb",
            new_accounts_active_by_default=True,
            instance_theme_color="#0f766e",
        ),
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )

    response = main.home(main.Request(request_with_cookie(cookie=admin_cookie)), db)
    assert response.context["page_theme_color"] == "#0f766e"


def test_instance_theme_color_is_used_for_admin(app_env):
    main = app_env["main"]
    db = app_env["db"]

    _, admin_cookie = register_and_cookie(main, db, "instance-admin@example.com", "Instance Admin")
    main.update_admin_settings(
        main.AdminSettingsUpdate(
            registration_enabled=True,
            default_board_color="#2563eb",
            new_accounts_active_by_default=True,
            instance_theme_color="#7c3aed",
        ),
        main.Request(request_with_cookie(path="/api/admin/settings", cookie=admin_cookie)),
        db,
    )

    response = main.admin_page(main.Request(request_with_cookie(path="/admin", cookie=admin_cookie)), db)
    assert response.context["page_theme_color"] == "#7c3aed"


def test_get_boards_is_scoped_to_current_user(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner_user, owner_cookie = register_and_cookie(main, db, "owner@example.com", "Owner")
    viewer_user, viewer_cookie = register_and_cookie(main, db, "viewer@example.com", "Viewer")
    outsider_user, outsider_cookie = register_and_cookie(main, db, "outsider@example.com", "Outsider")
    viewer_row = db.query(models.User).filter(models.User.id == viewer_user["id"]).first()

    owned_board = main.create_board(
        main.BoardCreate(name="Owned Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    shared_board = main.create_board(
        main.BoardCreate(name="Shared Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )

    shared_row = db.query(models.Board).filter(models.Board.id == shared_board["id"]).first()
    main.ensure_board_membership(shared_row, viewer_row, "viewer", db)
    db.commit()

    owner_boards = main.get_boards(main.Request(request_with_cookie(cookie=owner_cookie)), db)
    viewer_boards = main.get_boards(main.Request(request_with_cookie(cookie=viewer_cookie)), db)
    outsider_boards = main.get_boards(main.Request(request_with_cookie(cookie=outsider_cookie)), db)

    assert [board["name"] for board in owner_boards] == ["Owned Board", "Shared Board"]
    assert [board["role"] for board in owner_boards] == ["admin", "admin"]
    assert [board["is_shared"] for board in owner_boards] == [False, True]
    assert [board["name"] for board in viewer_boards] == ["Shared Board"]
    assert [board["role"] for board in viewer_boards] == ["viewer"]
    assert [board["is_shared"] for board in viewer_boards] == [True]
    assert outsider_boards == []
    assert owner_user["id"] != outsider_user["id"]


def test_board_creation_via_authenticated_route_assigns_owner_membership(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    user, cookie = register_and_cookie(main, db, "creator@example.com", "Creator")
    board = main.create_board(
        main.BoardCreate(name="Created Board"),
        db,
        main.Request(request_with_cookie(cookie=cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board["id"],
            models.BoardMembership.user_id == user["id"],
        )
        .first()
    )

    assert board_row.owner_user_id == user["id"]
    assert membership is not None
    assert membership.role == "owner"


def test_board_page_requires_membership_and_allows_shared_user(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner_user, owner_cookie = register_and_cookie(main, db, "owner2@example.com", "Owner Two")
    viewer_user, viewer_cookie = register_and_cookie(main, db, "viewer2@example.com", "Viewer Two")
    _, outsider_cookie = register_and_cookie(main, db, "outsider2@example.com", "Outsider Two")
    viewer_row = db.query(models.User).filter(models.User.id == viewer_user["id"]).first()

    board = main.create_board(
        main.BoardCreate(name="Shared Hub"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    main.ensure_board_membership(board_row, viewer_row, "viewer", db)
    db.commit()

    viewer_page = main.board_page(
        main.Request(request_with_cookie(path=f"/board/{board['id']}", cookie=viewer_cookie)),
        board["id"],
        db,
    )
    assert viewer_page.status_code == 200

    try:
        main.board_page(
            main.Request(request_with_cookie(path=f"/board/{board['id']}", cookie=outsider_cookie)),
            board["id"],
            db,
        )
        assert False, "Expected outsider board access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    login_redirect = main.board_page(
        main.Request(request_with_cookie(path=f"/board/{board['id']}")),
        board["id"],
        db,
    )
    assert isinstance(login_redirect, RedirectResponse)
    assert login_redirect.status_code == 303
    assert login_redirect.headers["location"] == "/login"


def test_boards_for_nav_includes_membership_role(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner_user, owner_cookie = register_and_cookie(main, db, "owner-nav@example.com", "Owner Nav")
    viewer_user, _ = register_and_cookie(main, db, "viewer-nav@example.com", "Viewer Nav")
    viewer_row = db.query(models.User).filter(models.User.id == viewer_user["id"]).first()

    owned_board = main.create_board(
        main.BoardCreate(name="Owned Hub"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    shared_board = main.create_board(
        main.BoardCreate(name="Shared Hub"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    shared_row = db.query(models.Board).filter(models.Board.id == shared_board["id"]).first()
    main.ensure_board_membership(shared_row, viewer_row, "viewer", db)
    db.commit()

    owner_row = db.query(models.User).filter(models.User.id == owner_user["id"]).first()
    owner_nav = main._boards_for_nav(db, owner_row)
    viewer_nav = main._boards_for_nav(db, viewer_row)

    assert {board["id"]: board["role"] for board in owner_nav} == {
        owned_board["id"]: "admin",
        shared_board["id"]: "admin",
    }
    assert {board["id"]: board["is_shared"] for board in owner_nav} == {
        owned_board["id"]: False,
        shared_board["id"]: True,
    }
    assert viewer_nav == [
        {
            "id": shared_board["id"],
            "name": "Shared Hub",
            "color": "#2563eb",
            "role": "viewer",
            "is_shared": True,
        }
    ]
