import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def type_visibility_env(app_env):
    client = TestClient(app_env["main"].app)
    client.headers["X-Requested-With"] = "XMLHttpRequest"
    client.post(
        "/api/auth/register",
        json={"email": "type-owner@example.com", "password": "test-password-only"},
    ).raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies["questline_csrf"]
    board = client.post("/api/boards", json={"name": "Type visibility"}).json()
    stage = client.post(
        "/api/stages", json={"board_id": board["id"], "name": "Inbox"}
    ).json()
    task_type = client.post(
        "/api/task-types", json={"board_id": board["id"], "name": "Bug"}
    ).json()
    task = client.post(
        "/api/tasks",
        json={"stage_id": stage["id"], "title": "A typed task", "task_type_id": task_type["id"]},
    ).json()
    yield {**app_env, "client": client, "board": board, "task_type": task_type, "task": task}
    client.close()


def test_type_name_visibility_defaults_updates_and_task_serialization(type_visibility_env):
    ctx = type_visibility_env
    client = ctx["client"]
    type_id = ctx["task_type"]["id"]
    type_url = f"/api/task-types/{type_id}"
    assert ctx["task_type"]["hide_name_on_card"] is False
    assert ctx["task"]["task_type"]["hide_name_on_card"] is False

    hidden = client.put(type_url, json={"hide_name_on_card": True})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["hide_name_on_card"] is True
    renamed = client.put(type_url, json={"name": "Hidden bug"})
    assert renamed.json()["hide_name_on_card"] is True

    types = client.get("/api/task-types", params={"board_id": ctx["board"]["id"]}).json()
    assert types[0]["hide_name_on_card"] is True
    task = client.get(f"/api/tasks/{ctx['task']['id']}").json()
    assert task["task_type"]["hide_name_on_card"] is True
    updated_task = client.put(f"/api/tasks/{ctx['task']['id']}", json={"title": "Renamed task"}).json()
    assert updated_task["task_type"]["hide_name_on_card"] is True
    stages = client.get("/api/stages", params={"board_id": ctx["board"]["id"]}).json()
    assert stages[0]["tasks"][0]["task_type"]["hide_name_on_card"] is True
    row = ctx["db"].get(ctx["models"].Task, ctx["task"]["id"])
    assert ctx["main"].task_to_dict(row)["task_type"]["hide_name_on_card"] is True
    ctx["db"].rollback()

    shown = client.put(type_url, json={"hide_name_on_card": False})
    assert shown.json()["hide_name_on_card"] is False
    assert client.get(f"/api/tasks/{ctx['task']['id']}").json()["task_type"]["hide_name_on_card"] is False
    created_hidden = client.post(
        "/api/task-types",
        json={"board_id": ctx["board"]["id"], "name": "Internal", "hide_name_on_card": True},
    )
    assert created_hidden.status_code == 200, created_hidden.text
    assert created_hidden.json()["hide_name_on_card"] is True


def test_type_name_visibility_rejects_null_before_mutation(type_visibility_env):
    ctx = type_visibility_env
    type_id = ctx["task_type"]["id"]
    response = ctx["client"].put(
        f"/api/task-types/{type_id}", json={"name": "Invalid change", "hide_name_on_card": None}
    )
    assert response.status_code == 422
    response = ctx["client"].post(
        "/api/task-types",
        json={"board_id": ctx["board"]["id"], "name": "Invalid create", "hide_name_on_card": None},
    )
    assert response.status_code == 422
    types = ctx["client"].get("/api/task-types", params={"board_id": ctx["board"]["id"]}).json()
    assert len(types) == 1
    assert types[0]["name"] == "Bug"
    assert types[0]["hide_name_on_card"] is False


def test_type_name_visibility_requires_editor_access(type_visibility_env):
    from authz import hash_password

    ctx = type_visibility_env
    db = ctx["db"]
    user = ctx["models"].User(
        email="type-viewer@example.com", display_name="Viewer", role="user",
        password_hash=hash_password("test-password-only"), is_active=True,
    )
    db.add(user)
    db.flush()
    membership = ctx["models"].BoardMembership(
        board_id=ctx["board"]["id"], user_id=user.id, role="viewer"
    )
    db.add(membership)
    db.commit()
    with TestClient(ctx["main"].app) as viewer:
        viewer.headers["X-Requested-With"] = "XMLHttpRequest"
        viewer.post(
            "/api/auth/login", json={"email": "type-viewer@example.com", "password": "test-password-only"}
        ).raise_for_status()
        viewer.headers["X-CSRF-Token"] = viewer.cookies["questline_csrf"]
        type_url = f"/api/task-types/{ctx['task_type']['id']}"
        denied = viewer.put(type_url, json={"hide_name_on_card": True})
        assert denied.status_code == 403
        types = viewer.get("/api/task-types", params={"board_id": ctx["board"]["id"]}).json()
        assert types[0]["hide_name_on_card"] is False
        membership.role = "editor"
        db.commit()
        allowed = viewer.put(type_url, json={"hide_name_on_card": True})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["hide_name_on_card"] is True


def test_type_name_visibility_migration_preserves_existing_types(type_visibility_env):
    ctx = type_visibility_env
    engine = ctx["database"].engine
    with engine.begin() as conn:
        columns = "id, name, board_id, color, is_epic, spawn_list_id, show_description_on_card, show_checklist_on_card"
        before = conn.execute(text(f"SELECT {columns} FROM task_types ORDER BY id")).fetchall()
        conn.execute(text("ALTER TABLE task_types DROP COLUMN hide_name_on_card"))
    for _ in range(2):
        ctx["main"]._run_column_migrations()
        ctx["db"].expire_all()
        with engine.connect() as conn:
            assert conn.execute(text(f"SELECT {columns} FROM task_types ORDER BY id")).fetchall() == before
        types = ctx["client"].get("/api/task-types", params={"board_id": ctx["board"]["id"]}).json()
        assert types[0]["hide_name_on_card"] is False
    type_url = f"/api/task-types/{ctx['task_type']['id']}"
    ctx["client"].put(type_url, json={"hide_name_on_card": True}).raise_for_status()
    ctx["main"]._run_column_migrations()
    types = ctx["client"].get("/api/task-types", params={"board_id": ctx["board"]["id"]}).json()
    assert types[0]["hide_name_on_card"] is True
