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
    return user, response.headers.get("set-cookie").split(";", 1)[0]


def setup_shared_board(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-api@example.com", "Owner")
    editor, editor_cookie = register_and_cookie(main, db, "editor-api@example.com", "Editor")
    viewer, viewer_cookie = register_and_cookie(main, db, "viewer-api@example.com", "Viewer")
    outsider, outsider_cookie = register_and_cookie(main, db, "outsider-api@example.com", "Outsider")

    board = main.create_board(
        main.BoardCreate(name="Team Board"),
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
        "board": board,
        "owner_cookie": owner_cookie,
        "editor_cookie": editor_cookie,
        "viewer_cookie": viewer_cookie,
        "outsider_cookie": outsider_cookie,
    }


def test_board_update_is_owner_only(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]
    board_id = ctx["board"]["id"]

    updated = main.update_board(
        board_id,
        main.BoardUpdate(name="Renamed"),
        db,
        main.Request(request_with_cookie(ctx["owner_cookie"])),
    )
    assert updated["name"] == "Renamed"

    try:
        main.update_board(
            board_id,
            main.BoardUpdate(name="Nope"),
            db,
            main.Request(request_with_cookie(ctx["editor_cookie"])),
        )
        assert False, "Expected editor board rename to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_stage_and_task_reads_allow_viewer_but_block_outsider(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=ctx["board"]["id"]),
        db,
    )
    task = main.create_task(main.TaskCreate(title="Visible task", stage_id=stage["id"]), db)

    stages = main.get_stages(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )
    assert [s["name"] for s in stages] == ["Backlog"]

    fetched_task = main.get_task(
        task["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )
    assert fetched_task["title"] == "Visible task"

    try:
        main.get_stages(
            ctx["board"]["id"],
            db,
            main.Request(request_with_cookie(ctx["outsider_cookie"])),
        )
        assert False, "Expected outsider stage access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_editor_can_write_but_viewer_cannot_for_stages_and_tasks(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    try:
        main.create_stage(
            main.StageCreate(name="Viewer Stage", board_id=ctx["board"]["id"]),
            db,
            main.Request(request_with_cookie(ctx["viewer_cookie"])),
        )
        assert False, "Expected viewer stage creation to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    stage = main.create_stage(
        main.StageCreate(name="Editor Stage", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )
    task = main.create_task(
        main.TaskCreate(title="Editable task", stage_id=stage["id"]),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )
    updated = main.update_task(
        task["id"],
        main.TaskUpdate(title="Updated task"),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )
    assert updated["title"] == "Updated task"

    try:
        main.update_task(
            task["id"],
            main.TaskUpdate(title="Viewer edit"),
            db,
            main.Request(request_with_cookie(ctx["viewer_cookie"])),
        )
        assert False, "Expected viewer task update to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_editor_can_manage_filters_task_types_and_automations_while_viewer_cannot(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    saved_filter = main.create_saved_filter(
        main.SavedFilterCreate(name="Filter", board_id=ctx["board"]["id"], definition=main.default_filter_definition()),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )
    task_type = main.create_task_type(
        main.TaskTypeCreate(name="Bug", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )
    automation = main.create_automation(
        main.AutomationCreate(
            name="Auto",
            board_id=ctx["board"]["id"],
            trigger_type="task_created",
            action_type="set_done",
        ),
        db,
        main.Request(request_with_cookie(ctx["editor_cookie"])),
    )

    assert main.get_saved_filters(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )[0]["id"] == saved_filter["id"]
    assert main.get_task_types(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )[0]["id"] == task_type["id"]
    assert main.get_automations(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(ctx["viewer_cookie"])),
    )[0]["id"] == automation["id"]

    try:
        main.create_saved_filter(
            main.SavedFilterCreate(name="Blocked", board_id=ctx["board"]["id"], definition=main.default_filter_definition()),
            db,
            main.Request(request_with_cookie(ctx["viewer_cookie"])),
        )
        assert False, "Expected viewer filter create to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403
