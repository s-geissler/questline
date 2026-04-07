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


def setup_shared_board(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-hardening@example.com", "Owner")
    editor, editor_cookie = register_and_cookie(main, db, "editor-hardening@example.com", "Editor")
    viewer, viewer_cookie = register_and_cookie(main, db, "viewer-hardening@example.com", "Viewer")
    outsider, outsider_cookie = register_and_cookie(main, db, "outsider-hardening@example.com", "Outsider")

    board = main.create_board(
        main.BoardCreate(name="Hardened Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
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


def test_board_scoped_pages_require_membership(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]
    board_id = ctx["board"]["id"]

    pages = (
        main.task_types_page,
        main.filters_page,
        main.automations_page,
    )

    for page in pages:
        viewer_page = page(
            main.Request(request_with_cookie(path=f"/board/{board_id}", cookie=ctx["viewer_cookie"])),
            board_id,
            db,
        )
        assert viewer_page.status_code == 200
        assert viewer_page.context["board_role"] == "viewer"

        try:
            page(
                main.Request(request_with_cookie(path=f"/board/{board_id}", cookie=ctx["outsider_cookie"])),
                board_id,
                db,
            )
            assert False, "Expected outsider page access to be denied"
        except main.HTTPException as exc:
            assert exc.status_code == 403

        redirect = page(
            main.Request(request_with_cookie(path=f"/board/{board_id}")),
            board_id,
            db,
        )
        assert isinstance(redirect, RedirectResponse)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/login"


def test_viewer_is_blocked_from_reorder_clear_and_checklist_mutations(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    backlog = main.create_stage(
        main.StageCreate(name="Backlog", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    done = main.create_stage(
        main.StageCreate(name="Done", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    task = main.create_task(
        main.TaskCreate(title="Quest", stage_id=backlog["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    checklist_item = main.add_checklist_item(
        task["id"],
        main.ChecklistItemCreate(title="Child objective"),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    main.update_task(
        task["id"],
        main.TaskUpdate(done=True),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    viewer_request = main.Request(request_with_cookie(cookie=ctx["viewer_cookie"]))

    denied_calls = (
        lambda: main.reorder_stages(
            main.ReorderStages(ids=[done["id"], backlog["id"]]),
            db,
            viewer_request,
        ),
        lambda: main.reorder_tasks(
            main.ReorderTasks(stage_id=done["id"], ids=[task["id"]]),
            db,
            viewer_request,
        ),
        lambda: main.move_task(
            task["id"],
            main.TaskMove(stage_id=done["id"], position=0),
            db,
            viewer_request,
        ),
        lambda: main.clear_completed_stage_tasks(done["id"], db, viewer_request),
        lambda: main.add_checklist_item(
            task["id"],
            main.ChecklistItemCreate(title="Blocked"),
            db,
            viewer_request,
        ),
        lambda: main.update_checklist_item(
            task["id"],
            checklist_item["id"],
            main.ChecklistItemUpdate(done=True),
            db,
            viewer_request,
        ),
        lambda: main.delete_checklist_item(task["id"], checklist_item["id"], db, viewer_request),
    )

    for denied_call in denied_calls:
        try:
            denied_call()
            assert False, "Expected viewer mutation to be denied"
        except main.HTTPException as exc:
            assert exc.status_code == 403


def test_removed_member_loses_board_access_immediately(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    listed_before = main.get_boards(
        main.Request(request_with_cookie(cookie=ctx["viewer_cookie"])),
        db,
    )
    assert [board["id"] for board in listed_before] == [ctx["board"]["id"]]

    deleted = main.delete_board_member(
        ctx["board"]["id"],
        ctx["viewer"]["id"],
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    assert deleted == {"ok": True}

    listed_after = main.get_boards(
        main.Request(request_with_cookie(cookie=ctx["viewer_cookie"])),
        db,
    )
    assert listed_after == []

    try:
        main.board_page(
            main.Request(request_with_cookie(path=f"/board/{ctx['board']['id']}", cookie=ctx["viewer_cookie"])),
            ctx["board"]["id"],
            db,
        )
        assert False, "Expected removed member board access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_cross_board_reorder_and_move_operations_are_rejected(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    source_stage = main.create_stage(
        main.StageCreate(name="Source", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    source_task = main.create_task(
        main.TaskCreate(title="Task A", stage_id=source_stage["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    other_board = main.create_board(
        main.BoardCreate(name="Other Board"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_stage = main.create_stage(
        main.StageCreate(name="Other Stage", board_id=other_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_task = main.create_task(
        main.TaskCreate(title="Task B", stage_id=other_stage["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    try:
        main.reorder_stages(
            main.ReorderStages(ids=[source_stage["id"], other_stage["id"]]),
            db,
            main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
        )
        assert False, "Expected cross-board stage reorder to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400

    try:
        main.reorder_tasks(
            main.ReorderTasks(stage_id=source_stage["id"], ids=[source_task["id"], other_task["id"]]),
            db,
            main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
        )
        assert False, "Expected cross-board task reorder to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400

    try:
        main.move_task(
            source_task["id"],
            main.TaskMove(stage_id=other_stage["id"], position=0),
            db,
            main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
        )
        assert False, "Expected cross-board move to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_cross_board_task_and_automation_references_are_rejected(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    stage = main.create_stage(
        main.StageCreate(name="Main Stage", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    task_type = main.create_task_type(
        main.TaskTypeCreate(name="Bug", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    local_field = main.add_custom_field(
        task_type["id"],
        main.CustomFieldCreate(name="Severity", field_type="text", show_on_card=False),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    other_board = main.create_board(
        main.BoardCreate(name="Other Board 2"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_stage = main.create_stage(
        main.StageCreate(name="Other Stage 2", board_id=other_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_task_type = main.create_task_type(
        main.TaskTypeCreate(name="Other Type", board_id=other_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_field = main.add_custom_field(
        other_task_type["id"],
        main.CustomFieldCreate(name="Foreign Field", field_type="text", show_on_card=False),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    task = main.create_task(
        main.TaskCreate(title="Main task", stage_id=stage["id"], task_type_id=task_type["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    try:
        main.update_task(
            task["id"],
            main.TaskUpdate(task_type_id=other_task_type["id"]),
            db,
            main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
        )
        assert False, "Expected cross-board task type assignment to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400

    try:
        main.update_task(
            task["id"],
            main.TaskUpdate(custom_fields={str(other_field["id"]): "x"}),
            db,
            main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
        )
        assert False, "Expected cross-board custom field update to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400

    updated = main.update_task(
        task["id"],
        main.TaskUpdate(custom_fields={str(local_field["id"]): "High"}),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    assert updated["custom_field_values"][str(local_field["id"])] == "High"

    try:
        main.create_automation(
            main.AutomationCreate(
                name="Bad auto",
                board_id=ctx["board"]["id"],
                trigger_type="task_created",
                action_type="move_to_stage",
                action_stage_id=other_stage["id"],
            ),
            db,
            main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
        )
        assert False, "Expected cross-board automation stage reference to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 400


def test_cross_board_spawn_target_requires_access_to_target_board(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    quest_type = main.create_task_type(
        main.TaskTypeCreate(name="Quest", board_id=ctx["board"]["id"], is_epic=True),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    other_board = main.create_board(
        main.BoardCreate(name="Restricted Target"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    other_stage = main.create_stage(
        main.StageCreate(name="Restricted Stage", board_id=other_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    try:
        main.update_task_type(
            quest_type["id"],
            main.TaskTypeUpdate(spawn_stage_id=other_stage["id"]),
            db,
            main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
        )
        assert False, "Expected spawn target update without target-board access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    owner_row = db.query(ctx["models"].User).filter(ctx["models"].User.id == ctx["editor"]["id"]).first()
    other_board_row = db.query(ctx["models"].Board).filter(ctx["models"].Board.id == other_board["id"]).first()
    main.ensure_board_membership(other_board_row, owner_row, "editor", db)
    db.commit()

    updated = main.update_task_type(
        quest_type["id"],
        main.TaskTypeUpdate(spawn_stage_id=other_stage["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    assert updated["spawn_stage_id"] == other_stage["id"]


def test_cross_hub_log_filter_can_pull_tasks_from_accessible_shared_hubs(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    my_stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    log_stage = main.create_stage(
        main.StageCreate(name="Overdue Log", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    shared_board = main.create_board(
        main.BoardCreate(name="Shared Source"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    shared_board_row = db.query(ctx["models"].Board).filter(ctx["models"].Board.id == shared_board["id"]).first()
    editor_row = db.query(ctx["models"].User).filter(ctx["models"].User.id == ctx["editor"]["id"]).first()
    main.ensure_board_membership(shared_board_row, editor_row, "viewer", db)
    db.commit()

    shared_stage = main.create_stage(
        main.StageCreate(name="Shared Backlog", board_id=shared_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    own_overdue = main.create_task(
        main.TaskCreate(
            title="Own overdue",
            stage_id=my_stage["id"],
            due_date=(main.date.today() - main.timedelta(days=1)).isoformat(),
        ),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    shared_overdue = main.create_task(
        main.TaskCreate(
            title="Shared overdue",
            stage_id=shared_stage["id"],
            due_date=(main.date.today() - main.timedelta(days=2)).isoformat(),
        ),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    main.create_task(
        main.TaskCreate(
            title="Shared future",
            stage_id=shared_stage["id"],
            due_date=(main.date.today() + main.timedelta(days=2)).isoformat(),
        ),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    saved_filter = main.create_saved_filter(
        main.SavedFilterCreate(
            name="Cross-hub overdue",
            board_id=ctx["board"]["id"],
            definition={
                "op": "and",
                "selected_task_type_id": None,
                "source_board_ids": [ctx["board"]["id"], shared_board["id"]],
                "rules": [
                    {"field": "due_date", "operator": "lt", "value": "today"},
                ],
            },
        ),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    main.update_stage_config(
        log_stage["id"],
        main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    stages = main.get_stages(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [shared_overdue["id"], own_overdue["id"]]
    assert rendered_log["tasks"][0]["board_id"] == shared_board["id"]
    assert rendered_log["tasks"][0]["stage_name"] == "Shared Backlog"


def test_cross_hub_log_filter_respects_access_revocation(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    my_stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    log_stage = main.create_stage(
        main.StageCreate(name="Shared Log", board_id=ctx["board"]["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    shared_board = main.create_board(
        main.BoardCreate(name="Revoked Source"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    shared_board_row = db.query(ctx["models"].Board).filter(ctx["models"].Board.id == shared_board["id"]).first()
    editor_row = db.query(ctx["models"].User).filter(ctx["models"].User.id == ctx["editor"]["id"]).first()
    main.ensure_board_membership(shared_board_row, editor_row, "viewer", db)
    db.commit()
    shared_stage = main.create_stage(
        main.StageCreate(name="External", board_id=shared_board["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )
    shared_task = main.create_task(
        main.TaskCreate(title="Shared visible", stage_id=shared_stage["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    saved_filter = main.create_saved_filter(
        main.SavedFilterCreate(
            name="Shared scope",
            board_id=ctx["board"]["id"],
            definition={
                "op": "and",
                "selected_task_type_id": None,
                "source_board_ids": [shared_board["id"]],
                "rules": [],
            },
        ),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    main.update_stage_config(
        log_stage["id"],
        main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]),
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )

    before = main.get_stages(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    rendered_before = next(stage for stage in before if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_before["tasks"]] == [shared_task["id"]]

    main.delete_board_member(
        shared_board["id"],
        ctx["editor"]["id"],
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    after = main.get_stages(
        ctx["board"]["id"],
        db,
        main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
    )
    rendered_after = next(stage for stage in after if stage["id"] == log_stage["id"])
    assert rendered_after["tasks"] == []


def test_cross_hub_filter_source_boards_require_view_access(app_env):
    ctx = setup_shared_board(app_env)
    main = ctx["main"]
    db = ctx["db"]

    restricted_board = main.create_board(
        main.BoardCreate(name="Restricted"),
        db,
        main.Request(request_with_cookie(cookie=ctx["owner_cookie"])),
    )

    try:
        main.create_saved_filter(
            main.SavedFilterCreate(
                name="Blocked scope",
                board_id=ctx["board"]["id"],
                definition={
                    "op": "and",
                    "selected_task_type_id": None,
                    "source_board_ids": [restricted_board["id"]],
                    "rules": [],
                },
            ),
            db,
            main.Request(request_with_cookie(cookie=ctx["editor_cookie"])),
        )
        assert False, "Expected inaccessible source board to be rejected"
    except main.HTTPException as exc:
        assert exc.status_code == 403
