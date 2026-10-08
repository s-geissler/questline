from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


def create_task_client(app_env):
    main = app_env["main"]
    models = app_env["models"]
    db = app_env["db"]

    owner = models.User(
        email="attachment-owner@example.com",
        password_hash="unused",
        display_name="Attachment Owner",
        role="admin",
        is_active=True,
    )
    db.add(owner)
    db.commit()

    board = models.Board(name="Attachments", owner_user_id=owner.id)
    db.add(board)
    db.flush()
    main.ensure_board_membership(board, owner, "owner", db)
    stage = models.Stage(name="Backlog", board_id=board.id)
    db.add(stage)
    db.flush()
    task = models.Task(title="Task with files", stage_id=stage.id)
    db.add(task)
    db.commit()

    session_token, csrf_token = main.create_user_session(owner, db)
    client = TestClient(main.app)
    client.cookies.set("questline_session", session_token)
    client.cookies.set("questline_csrf", csrf_token)
    headers = {**XHR_HEADERS, "X-CSRF-Token": csrf_token}
    return {
        "main": main,
        "models": models,
        "db": db,
        "board": board,
        "task": task,
        "owner": owner,
        "client": client,
        "headers": headers,
    }


def test_attachment_upload_list_download_delete_and_task_cascade(app_env):
    ctx = create_task_client(app_env)
    client = ctx["client"]
    headers = ctx["headers"]
    task_id = ctx["task"].id

    upload = client.post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": ("../notes.txt", b"task file", "text/plain")},
        headers=headers,
    )

    assert upload.status_code == 201
    attachment = upload.json()
    assert attachment["filename"] == "notes.txt"
    assert attachment["size_bytes"] == len(b"task file")
    assert "content" not in attachment

    listing = client.get(f"/api/tasks/{task_id}/attachments")
    assert listing.status_code == 200
    assert listing.json() == [attachment]
    stages = client.get(f"/api/stages?board_id={ctx['board'].id}").json()
    stage_task = stages[0]["tasks"][0]
    assert stage_task["id"] == task_id
    assert stage_task["attachment_count"] == 1
    assert client.get(f"/api/tasks/{task_id}").json()["attachment_count"] == 1

    download = client.get(
        f"/api/tasks/{task_id}/attachments/{attachment['id']}/download"
    )
    assert download.status_code == 200
    assert download.content == b"task file"
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"

    deleted = client.delete(
        f"/api/tasks/{task_id}/attachments/{attachment['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/tasks/{task_id}/attachments").json() == []
    assert client.get(f"/api/tasks/{task_id}").json()["attachment_count"] == 0

    second_upload = client.post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": ("keep.txt", b"delete with task", "text/plain")},
        headers=headers,
    )
    assert second_upload.status_code == 201
    task_delete = client.delete(f"/api/tasks/{task_id}", headers=headers)
    assert task_delete.status_code == 200
    assert ctx["db"].query(ctx["models"].TaskAttachment).count() == 0


def test_attachment_permissions_and_task_scoping(app_env):
    ctx = create_task_client(app_env)
    main = ctx["main"]
    models = ctx["models"]
    db = ctx["db"]
    task_id = ctx["task"].id
    upload = ctx["client"].post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": ("private.txt", b"private", "text/plain")},
        headers=ctx["headers"],
    )
    assert upload.status_code == 201
    attachment_id = upload.json()["id"]

    other_task = models.Task(title="Other task", stage_id=ctx["task"].stage_id)
    db.add(other_task)
    db.commit()
    mismatched_download = ctx["client"].get(
        f"/api/tasks/{other_task.id}/attachments/{attachment_id}/download"
    )
    assert mismatched_download.status_code == 404

    viewer = models.User(
        email="attachment-viewer@example.com",
        password_hash="unused",
        display_name="Attachment Viewer",
        is_active=True,
    )
    db.add(viewer)
    db.flush()
    main.ensure_board_membership(ctx["board"], viewer, "viewer", db)
    db.commit()
    viewer_token, viewer_csrf = main.create_user_session(viewer, db)
    viewer_client = TestClient(main.app)
    viewer_client.cookies.set("questline_session", viewer_token)
    viewer_client.cookies.set("questline_csrf", viewer_csrf)
    viewer_headers = {**XHR_HEADERS, "X-CSRF-Token": viewer_csrf}

    assert viewer_client.get(f"/api/tasks/{task_id}/attachments").status_code == 200
    assert viewer_client.get(
        f"/api/tasks/{task_id}/attachments/{attachment_id}/download"
    ).content == b"private"
    assert viewer_client.post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": ("blocked.txt", b"no", "text/plain")},
        headers=viewer_headers,
    ).status_code == 403
    assert viewer_client.delete(
        f"/api/tasks/{task_id}/attachments/{attachment_id}",
        headers=viewer_headers,
    ).status_code == 403

    editor = models.User(
        email="attachment-editor@example.com",
        password_hash="unused",
        display_name="Attachment Editor",
        is_active=True,
    )
    db.add(editor)
    db.flush()
    main.ensure_board_membership(ctx["board"], editor, "editor", db)
    db.commit()
    editor_token, editor_csrf = main.create_user_session(editor, db)
    editor_client = TestClient(main.app)
    editor_client.cookies.set("questline_session", editor_token)
    editor_client.cookies.set("questline_csrf", editor_csrf)
    editor_headers = {**XHR_HEADERS, "X-CSRF-Token": editor_csrf}
    editor_upload = editor_client.post(
        f"/api/tasks/{task_id}/attachments",
        files={"file": ("editor.txt", b"editable", "text/plain")},
        headers=editor_headers,
    )
    assert editor_upload.status_code == 201
    assert editor_client.delete(
        f"/api/tasks/{task_id}/attachments/{editor_upload.json()['id']}",
        headers=editor_headers,
    ).status_code == 200

    outsider = models.User(
        email="attachment-outsider@example.com",
        password_hash="unused",
        display_name="Attachment Outsider",
        is_active=True,
    )
    db.add(outsider)
    db.commit()
    outsider_token, outsider_csrf = main.create_user_session(outsider, db)
    outsider_client = TestClient(main.app)
    outsider_client.cookies.set("questline_session", outsider_token)
    outsider_client.cookies.set("questline_csrf", outsider_csrf)
    assert outsider_client.get(f"/api/tasks/{task_id}/attachments").status_code == 403


def test_attachment_size_limit_and_per_task_count(app_env):
    ctx = create_task_client(app_env)
    client = ctx["client"]
    task_id = ctx["task"].id
    path = f"/api/tasks/{task_id}/attachments"

    exact_limit = client.post(
        path,
        files={"file": ("limit.bin", b"x" * MAX_ATTACHMENT_SIZE, "application/octet-stream")},
        headers=ctx["headers"],
    )
    assert exact_limit.status_code == 201
    assert exact_limit.json()["size_bytes"] == MAX_ATTACHMENT_SIZE

    too_large = client.post(
        path,
        files={"file": ("too-large.bin", b"x" * (MAX_ATTACHMENT_SIZE + 1), "application/octet-stream")},
        headers=ctx["headers"],
    )
    assert too_large.status_code == 413

    oversized_request = client.post(
        path,
        files={
            "file": (
                "oversized-request.bin",
                b"x" * (MAX_ATTACHMENT_SIZE + 128 * 1024),
                "application/octet-stream",
            )
        },
        headers=ctx["headers"],
    )
    assert oversized_request.status_code == 413
    assert oversized_request.headers["x-content-type-options"] == "nosniff"

    client.delete(
        f"{path}/{exact_limit.json()['id']}",
        headers=ctx["headers"],
    )
    for index in range(5):
        response = client.post(
            path,
            files={"file": (f"{index}.txt", b"x", "text/plain")},
            headers=ctx["headers"],
        )
        assert response.status_code == 201

    sixth = client.post(
        path,
        files={"file": ("sixth.txt", b"x", "text/plain")},
        headers=ctx["headers"],
    )
    assert sixth.status_code == 409
    assert len(client.get(path).json()) == 5


def test_concurrent_uploads_do_not_exceed_per_task_count(app_env):
    ctx = create_task_client(app_env)
    client = ctx["client"]
    task_id = ctx["task"].id
    path = f"/api/tasks/{task_id}/attachments"

    for index in range(4):
        response = client.post(
            path,
            files={"file": (f"{index}.txt", b"x", "text/plain")},
            headers=ctx["headers"],
        )
        assert response.status_code == 201

    second_client = TestClient(ctx["main"].app)
    for cookie_name in ("questline_session", "questline_csrf"):
        second_client.cookies.set(cookie_name, client.cookies.get(cookie_name))

    def upload(index, upload_client):
        return upload_client.post(
            path,
            files={"file": (f"concurrent-{index}.txt", b"x", "text/plain")},
            headers=ctx["headers"],
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(upload, (1, 2), (client, second_client)))

    assert sorted(statuses) == [201, 409]
    assert len(client.get(path).json()) == 5


def test_chunked_attachment_request_body_limit(app_env):
    ctx = create_task_client(app_env)
    boundary = "questline-test-boundary"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="large.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    remaining = MAX_ATTACHMENT_SIZE + 128 * 1024

    def body_chunks():
        nonlocal remaining
        yield prefix
        chunk = b"x" * (64 * 1024)
        while remaining:
            next_chunk = chunk[:remaining]
            yield next_chunk
            remaining -= len(next_chunk)
        yield suffix

    response = ctx["client"].post(
        f"/api/tasks/{ctx['task'].id}/attachments",
        content=body_chunks(),
        headers={
            **ctx["headers"],
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    assert response.status_code == 413, response.text
