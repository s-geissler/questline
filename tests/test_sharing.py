def request_with_cookie(cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return {"type": "http", "method": "GET", "path": "/", "headers": headers}


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
        main.Request(request_with_cookie(admin_cookie)),
        db,
    )
    login_response = main.Response()
    main.auth_login(main.LoginRequest(email=email, password="supersecret"), login_response, db)
    return user, login_response.headers.get("set-cookie").split(";", 1)[0]


def setup_board_with_users(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-share@example.com", "Owner")
    editor, editor_cookie = register_and_cookie(main, db, "editor-share@example.com", "Editor")
    viewer, viewer_cookie = register_and_cookie(main, db, "viewer-share@example.com", "Viewer")
    outsider, outsider_cookie = register_and_cookie(main, db, "outsider-share@example.com", "Outsider")

    board = main.create_board(
        main.BoardCreate(name="Shared Hub"),
        db,
        main.Request(request_with_cookie(owner_cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    editor_row = db.query(models.User).filter(models.User.id == editor["id"]).first()
    viewer_row = db.query(models.User).filter(models.User.id == viewer["id"]).first()
    main.ensure_board_membership(board_row, editor_row, "editor", db)
    main.ensure_board_membership(board_row, viewer_row, "viewer", db)
    db.commit()

    return {
        "main": main,
        "db": db,
        "models": models,
        "board": board,
        "owner": owner,
        "owner_cookie": owner_cookie,
        "editor": editor,
        "editor_cookie": editor_cookie,
        "viewer": viewer,
        "viewer_cookie": viewer_cookie,
        "outsider": outsider,
        "outsider_cookie": outsider_cookie,
    }


def test_owner_can_list_add_update_and_remove_board_members(app_env):
    ctx = setup_board_with_users(app_env)
    main = ctx["main"]
    db = ctx["db"]

    listed = main.get_board_members(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert listed["current_role"] == "admin"
    assert [member["role"] for member in listed["members"]] == ["owner", "editor", "viewer"]

    added = main.add_board_member(
        ctx["board"]["id"],
        main.BoardMemberCreate(email=ctx["outsider"]["email"], role="viewer"),
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert added["email"] == ctx["outsider"]["email"]
    assert added["role"] == "viewer"

    updated = main.update_board_member(
        ctx["board"]["id"],
        ctx["viewer"]["id"],
        main.BoardMemberUpdate(role="editor"),
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert updated["role"] == "editor"

    deleted = main.delete_board_member(
        ctx["board"]["id"],
        ctx["editor"]["id"],
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert deleted == {"ok": True}


def test_non_owner_cannot_manage_board_memberships(app_env):
    ctx = setup_board_with_users(app_env)
    main = ctx["main"]
    db = ctx["db"]

    for cookie in (ctx["editor_cookie"], ctx["viewer_cookie"], ctx["outsider_cookie"]):
        try:
            main.add_board_member(
                ctx["board"]["id"],
                main.BoardMemberCreate(email=ctx["outsider"]["email"], role="viewer"),
                db,
                main.Request(request_with_cookie(cookie)),
            )
            assert False, "Expected non-owner membership write to be denied"
        except main.HTTPException as exc:
            assert exc.status_code == 403

    listed = main.get_board_members(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )
    assert listed["current_role"] == "viewer"
    assert len(listed["members"]) == 3


def test_board_must_keep_at_least_one_owner(app_env):
    ctx = setup_board_with_users(app_env)
    main = ctx["main"]
    db = ctx["db"]

    try:
        main.update_board_member(
            ctx["board"]["id"],
            ctx["owner"]["id"],
            main.BoardMemberUpdate(role="editor"),
            db,
            main.Request(request_with_cookie(ctx["owner_cookie"])),
        )
        assert False, "Expected last owner demotion to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 400

    try:
        main.delete_board_member(
            ctx["board"]["id"],
            ctx["owner"]["id"],
            db,
            main.Request(request_with_cookie(ctx["owner_cookie"])),
        )
        assert False, "Expected last owner removal to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_promoting_new_owner_allows_original_owner_removal(app_env):
    ctx = setup_board_with_users(app_env)
    main = ctx["main"]
    db = ctx["db"]
    models = ctx["models"]

    promoted = main.update_board_member(
        ctx["board"]["id"],
        ctx["editor"]["id"],
        main.BoardMemberUpdate(role="owner"),
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert promoted["role"] == "owner"

    removed = main.delete_board_member(
        ctx["board"]["id"],
        ctx["owner"]["id"],
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert removed == {"ok": True}

    board_row = db.query(models.Board).filter(models.Board.id == ctx["board"]["id"]).first()
    assert board_row.owner_user_id == ctx["editor"]["id"]
