from datetime import date, timedelta


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


def test_assignment_creates_notification_for_new_assignee(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-notify@example.com", "Owner")
    assignee, assignee_cookie = register_and_cookie(main, db, "assignee-notify@example.com", "Assignee")

    board = main.create_board(
        main.BoardCreate(name="Notify Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    assignee_row = db.query(models.User).filter(models.User.id == assignee["id"]).first()
    main.ensure_board_membership(board_row, assignee_row, "viewer", db)
    db.commit()

    stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=board["id"]),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    task = main.create_task(
        main.TaskCreate(title="Assigned item", stage_id=stage["id"]),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )

    main.update_task(
        task["id"],
        main.TaskUpdate(assignee_user_id=assignee["id"]),
        db,
        main.Request(request_with_cookie(path=f"/api/tasks/{task['id']}", cookie=owner_cookie)),
    )

    payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=assignee_cookie)),
        db,
    )
    assert any(item["type"] == "task_assigned" and "Assigned item" in item["body"] for item in payload["items"])


def test_board_shared_creates_notification_for_new_member(app_env):
    main = app_env["main"]
    db = app_env["db"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-share@example.com", "Owner")
    viewer, viewer_cookie = register_and_cookie(main, db, "viewer-share@example.com", "Viewer")

    board = main.create_board(
        main.BoardCreate(name="Shared Hub"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )

    main.add_board_member(
        board["id"],
        main.BoardMemberCreate(email=viewer["email"], role="viewer"),
        db,
        main.Request(request_with_cookie(path=f"/api/boards/{board['id']}/members", cookie=owner_cookie)),
    )

    payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=viewer_cookie)),
        db,
    )
    assert any(item["type"] == "board_shared" and "Shared Hub" in item["body"] for item in payload["items"])


def test_due_today_notifications_are_generated_for_assigned_tasks(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-due@example.com", "Owner")
    assignee, assignee_cookie = register_and_cookie(main, db, "assignee-due@example.com", "Assignee")

    board = main.create_board(
        main.BoardCreate(name="Due Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    assignee_row = db.query(models.User).filter(models.User.id == assignee["id"]).first()
    main.ensure_board_membership(board_row, assignee_row, "viewer", db)
    db.commit()

    stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=board["id"]),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    task = main.create_task(
        main.TaskCreate(title="Due today", stage_id=stage["id"], due_date=date.today().isoformat()),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    main.update_task(
        task["id"],
        main.TaskUpdate(assignee_user_id=assignee["id"]),
        db,
        main.Request(request_with_cookie(path=f"/api/tasks/{task['id']}", cookie=owner_cookie)),
    )

    payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=assignee_cookie)),
        db,
    )
    assert any(item["type"] == "task_due_today" and item["body"] == "Due today" for item in payload["items"])


def test_overdue_notifications_are_generated_for_assigned_tasks(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner, owner_cookie = register_and_cookie(main, db, "owner-overdue@example.com", "Owner")
    assignee, assignee_cookie = register_and_cookie(main, db, "assignee-overdue@example.com", "Assignee")

    board = main.create_board(
        main.BoardCreate(name="Overdue Board"),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    assignee_row = db.query(models.User).filter(models.User.id == assignee["id"]).first()
    main.ensure_board_membership(board_row, assignee_row, "viewer", db)
    db.commit()

    stage = main.create_stage(
        main.StageCreate(name="Backlog", board_id=board["id"]),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    task = main.create_task(
        main.TaskCreate(title="Overdue item", stage_id=stage["id"], due_date=(date.today() - timedelta(days=1)).isoformat()),
        db,
        main.Request(request_with_cookie(cookie=owner_cookie)),
    )
    main.update_task(
        task["id"],
        main.TaskUpdate(assignee_user_id=assignee["id"]),
        db,
        main.Request(request_with_cookie(path=f"/api/tasks/{task['id']}", cookie=owner_cookie)),
    )

    payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=assignee_cookie)),
        db,
    )
    assert any(item["type"] == "task_overdue" and item["body"] == "Overdue item" for item in payload["items"])


def test_password_recovery_request_notifies_all_admins(app_env):
    main = app_env["main"]
    db = app_env["db"]

    admin1, admin1_cookie = register_and_cookie(main, db, "admin-reset-1@example.com", "Admin One")
    admin2, _ = register_and_cookie(main, db, "admin-reset-2@example.com", "Admin Two")
    user, _ = register_and_cookie(main, db, "user-reset@example.com", "Needs Help")

    main.update_admin_user(
        admin2["id"],
        main.AdminUserUpdate(role="admin"),
        main.Request(request_with_cookie(path=f"/api/admin/users/{admin2['id']}", cookie=admin1_cookie)),
        db,
    )

    admin2_login = main.Response()
    main.auth_login(main.LoginRequest(email=admin2["email"], password="supersecret"), admin2_login, db)
    admin2_cookie = admin2_login.headers.get("set-cookie").split(";", 1)[0]

    main.auth_password_recovery_request(
        main.PasswordRecoveryRequest(email=user["email"]),
        db,
        main.Request(request_with_cookie(path="/api/auth/password-recovery-request")),
    )

    user_row = db.query(main.models.User).filter(main.models.User.id == user["id"]).first()
    assert user_row.password_reset_requested is True

    admin1_payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=admin1_cookie)),
        db,
    )
    admin2_payload = main.get_notifications(
        main.Request(request_with_cookie(path="/api/notifications", cookie=admin2_cookie)),
        db,
    )
    assert any(item["type"] == "password_recovery_requested" and user["email"] in item["body"] for item in admin1_payload["items"])
    assert any(item["type"] == "password_recovery_requested" and user["email"] in item["body"] for item in admin2_payload["items"])
