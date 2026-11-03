import copy
import importlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def export_data():
    return {
        "name": "Imported Hub",
        "lists": [{"id": "done", "name": "Done", "pos": 200}, {"id": "todo", "name": "To do", "pos": 100}],
        "cards": [
            {"id": "second", "idList": "todo", "name": "Second", "pos": 140737488355328.5},
            {
                "id": "first", "idList": "todo", "name": "First", "pos": 140737488355328,
                "desc": "Original **Markdown** description.", "due": "2026-12-15T18:30:00.000Z",
                "dueComplete": False, "idMembers": ["alice", "missing"], "idChecklists": ["check-a", "check-b"],
                "attachments": [
                    {"name": "Spec [draft].pdf", "url": "https://trello.example/files/(draft).pdf?dl=1", "pos": 20},
                    {"name": "Unavailable file", "url": "javascript:alert(1)", "pos": 30},
                ],
                "customFieldItems": [{"idCustomField": "priority", "value": {"text": "High"}}],
                "labels": [{"name": "Important", "color": "red"}],
                "cover": {"color": "green"}, "recurrenceRule": {"frequency": "weekly"},
            },
            {"id": "complete", "idList": "done", "name": "Completed", "pos": 10, "dueComplete": True},
            {"id": "archived", "idList": "missing-list", "name": "x" * 201, "closed": True},
        ],
        "members": [{"id": "alice", "fullName": "Alice Example", "username": "alice"}],
        "checklists": [
            {"id": "check-b", "idCard": "first", "name": "Review", "pos": 20, "checkItems": [
                {"name": "Approve", "state": "incomplete", "pos": 10},
            ]},
            {"id": "check-a", "idCard": "first", "name": "Build", "pos": 10, "checkItems": [
                {"name": "Test", "state": "incomplete", "pos": 20},
                {"name": "Implement", "state": "complete", "pos": 10},
            ]},
            {"id": "check-archived", "idCard": "archived", "checkItems": [{"name": "Skip"}]},
        ],
        # Customization and history deliberately have no influence on the import.
        "customFields": {"unsupported": True}, "automations": ["ignored"], "actions": ["ignored"],
    }


@pytest.fixture
def ctx(app_env):
    models, db, main = app_env["models"], app_env["db"], app_env["main"]
    user = models.User(email="import-owner@example.invalid", display_name="Owner", password_hash="unused", role="user", is_active=True)
    db.add(user)
    db.commit()
    token, csrf = main.create_user_session(user, db)
    client = TestClient(main.app)
    client.cookies.set("questline_session", token)
    client.cookies.set("questline_csrf", csrf)
    return {**app_env, "user": user, "client": client, "headers": {"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf}}


def upload(ctx, data=None, *, preview=False, board_id=None, confirm=True, content=None):
    form = {}
    if board_id is not None:
        form["board_id"] = str(board_id)
    if confirm:
        form["confirm_replace"] = "true"
    return ctx["client"].post(
        "/api/boards/import-trello" + ("/preview" if preview else ""),
        files={"file": ("trello.json", content if content is not None else json.dumps(data if data is not None else export_data()).encode(), "application/json")},
        data=form, headers=ctx["headers"],
    )


def seed_existing(ctx):
    models, db = ctx["models"], ctx["db"]
    board = models.Board(name="Keep this name", color="#ef4444", position=7, owner_user_id=ctx["user"].id)
    db.add(board)
    db.flush()
    ctx["main"].ensure_board_membership(board, ctx["user"], "owner", db)
    stage = models.Stage(board=board, name="Old stage", row=0, position=0)
    other_stage = models.Stage(board=board, name="Old second stage", row=1, position=0)
    db.add_all([stage, other_stage])
    db.flush()
    task_type = models.TaskType(board=board, name="Existing Quest", is_epic=True, spawn_stage=stage)
    field = models.CustomFieldDef(task_type=task_type, name="Existing field")
    parent = models.Task(stage=stage, title="Old parent", task_type=task_type)
    child = models.Task(stage=other_stage, title="Old child", parent_task=parent)
    db.add_all([parent, child, field])
    db.flush()
    db.add_all([
        models.ChecklistItem(task=parent, title="Linked item", spawned_task=child),
        models.TaskAttachment(task=parent, filename="old.txt", content=b"old", size_bytes=3),
        models.CustomFieldValue(task=parent, field_def=field, value="old"),
        models.TaskRecurrence(task=parent, frequency="daily", next_run_on="2026-12-01", spawn_stage=stage),
        models.Notification(user=ctx["user"], type="task_assigned", title="Old", task_id=parent.id, board_id=board.id),
        models.Automation(board=board, name="Move new objectives", trigger_type="task_created", action_type="move_to_stage", trigger_stage=stage, action_stage=other_stage),
        models.Automation(board=board, name="Global rule", trigger_type="task_created", action_type="set_done"),
        models.SavedFilter(board=board, name="Keep filter", definition='{"rules": []}'),
        models.CalendarFeed(user=ctx["user"], board_id=board.id, name="Selected stages", all_stages=False, token_hash="hash", last_four="hash", stages=[stage]),
    ])
    other_board = models.Board(name="Unaffected")
    db.add(other_board)
    db.flush()
    db.add(models.Task(stage=models.Stage(board=other_board, name="Unaffected stage"), title="Unaffected task"))
    db.commit()
    return board.id, {stage.id, other_stage.id}, {parent.id, child.id}


def test_preview_and_new_hub_import_use_only_base_objectives(ctx):
    models, db = ctx["models"], ctx["db"]
    preview = upload(ctx, preview=True)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "name": "Imported Hub", "stage_count": 2, "task_count": 3, "checklist_item_count": 3,
        "skipped_archived_card_count": 1, "target_board": None,
    }
    assert db.query(models.Board).count() == 0

    response = upload(ctx)
    assert response.status_code == 201, response.text
    board_id = response.json()["board_id"]
    board = db.get(models.Board, board_id)
    assert board.name == "Imported Hub"
    assert board.owner_user_id == ctx["user"].id
    assert db.query(models.BoardMembership).filter_by(board_id=board_id).one().role == "owner"
    stages = ctx["client"].get(f"/api/stages?board_id={board_id}").json()
    assert [(s["name"], s["row"], s["position"], s["is_log"]) for s in stages] == [("To do", 0, 0, False), ("Done", 0, 1, False)]
    assert [t["title"] for t in stages[0]["tasks"]] == ["First", "Second"]
    first, second = stages[0]["tasks"]
    assert first["due_date"] == "2026-12-15"
    assert first["done"] is False
    assert stages[1]["tasks"][0]["done"] is True
    assert first["description"].startswith("Original **Markdown** description.\n\n---\n\n### Trello import notes")
    assert "Alice Example (@alice)" in first["description"]
    assert "Unknown Trello member (missing)" in first["description"]
    assert r"[Spec \[draft\].pdf](https://trello.example/files/%28draft%29.pdf?dl=1)" in first["description"]
    assert "Unavailable file (link unavailable)" in first["description"]
    assert "javascript:" not in first["description"]
    assert second["description"] == ""
    assert [(i["title"], i["done"], i["spawned_task_id"]) for i in first["checklist"]] == [
        ("Build: Implement", True, None), ("Build: Test", False, None), ("Review: Approve", False, None),
    ]
    for task in db.query(models.Task).all():
        assert task.assignee_user_id is None and task.task_type_id is None and task.color is None
    for model in (models.TaskType, models.CustomFieldDef, models.CustomFieldValue, models.Automation, models.TaskAttachment, models.TaskRecurrence):
        assert db.query(model).count() == 0


def test_replace_removes_old_content_and_automations_preserving_hub(ctx):
    models, db = ctx["models"], ctx["db"]
    board_id, old_stages, old_tasks = seed_existing(ctx)
    preview = upload(ctx, preview=True, board_id=board_id).json()
    assert preview["target_board"] == {"id": board_id, "name": "Keep this name", "stage_count": 2, "task_count": 2, "automation_count": 2}
    assert db.query(models.Automation).count() == 2
    response = upload(ctx, board_id=board_id)
    assert response.status_code == 200, response.text
    assert response.json()["board_id"] == board_id
    assert response.json()["replaced"] is True
    db.expire_all()
    board = db.get(models.Board, board_id)
    assert (board.name, board.color, board.position, board.owner_user_id) == ("Keep this name", "#ef4444", 7, ctx["user"].id)
    assert db.query(models.BoardMembership).filter_by(board_id=board_id).count() == 1
    assert not old_stages.intersection(s.id for s in board.stages)
    assert all(db.get(models.Task, task_id) is None for task_id in old_tasks)
    assert db.query(models.Task).join(models.Stage).filter(models.Stage.board_id == board_id).count() == 3
    for model in (models.Automation, models.TaskAttachment, models.TaskRecurrence, models.CustomFieldValue):
        assert db.query(model).count() == 0
    assert db.query(models.TaskType).one().spawn_stage_id is None
    assert db.query(models.CustomFieldDef).one().name == "Existing field"
    assert db.query(models.SavedFilter).one().name == "Keep filter"
    assert db.query(models.CalendarFeed).one().stages == []
    assert db.query(models.Notification).one().task_id is None
    assert db.query(models.Task).filter_by(title="Unaffected task").count() == 1
    assert list(db.execute(text("PRAGMA foreign_key_check"))) == []


def test_invalid_replacement_and_missing_confirmation_preserve_existing_content(ctx):
    models, db = ctx["models"], ctx["db"]
    board_id, _, old_tasks = seed_existing(ctx)
    assert upload(ctx, board_id=board_id, confirm=False).status_code == 400
    broken = export_data()
    broken["cards"][0]["idList"] = "does-not-exist"
    response = upload(ctx, broken, board_id=board_id)
    assert response.status_code == 400
    assert "missing" in response.json()["detail"]
    db.expire_all()
    assert all(db.get(models.Task, task_id) is not None for task_id in old_tasks)
    assert db.query(models.Automation).count() == 2


@pytest.mark.parametrize("replace", [False, True])
def test_database_failure_rolls_back_whole_import(ctx, monkeypatch, replace):
    routes = importlib.import_module("routes.boards")
    original = routes.import_trello_content
    board_id = seed_existing(ctx)[0] if replace else None
    def fail_after_writes(*args):
        original(*args)
        raise RuntimeError("Simulated failure after all writes")
    monkeypatch.setattr(routes, "import_trello_content", fail_after_writes)
    ctx["client"] = TestClient(ctx["main"].app, raise_server_exceptions=False, cookies=ctx["client"].cookies)
    assert upload(ctx, board_id=board_id).status_code == 500
    models, db = ctx["models"], ctx["db"]
    db.expire_all()
    assert db.query(models.Board).filter_by(name="Imported Hub").count() == 0
    if replace:
        assert [s.name for s in db.get(models.Board, board_id).stages] == ["Old stage", "Old second stage"]
        assert db.query(models.Automation).count() == 2
        assert db.query(models.Task).filter_by(title="Old parent").count() == 1
        assert db.query(models.TaskAttachment).count() == 1
    else:
        assert db.query(models.BoardMembership).count() == 0


@pytest.mark.parametrize("role", ["viewer", "editor", None])
def test_preview_and_replacement_require_owner_access(ctx, role):
    board_id = seed_existing(ctx)[0]
    models, db, main = ctx["models"], ctx["db"], ctx["main"]
    user = models.User(email="other@example.invalid", display_name="Other", password_hash="unused", is_active=True)
    db.add(user)
    db.flush()
    if role:
        main.ensure_board_membership(db.get(models.Board, board_id), user, role, db)
    db.commit()
    token, csrf = main.create_user_session(user, db)
    ctx["client"].cookies.set("questline_session", token)
    ctx["client"].cookies.set("questline_csrf", csrf)
    ctx["headers"]["X-CSRF-Token"] = csrf
    assert upload(ctx, board_id=board_id, preview=True).status_code == 403
    assert upload(ctx, board_id=board_id).status_code == 403
    assert db.query(models.Automation).count() == 2


def test_import_respects_csrf_and_bearer_auth(ctx):
    # A valid session needs its CSRF header for both preview and import.
    csrf = ctx["headers"].pop("X-CSRF-Token")
    assert upload(ctx, preview=True).status_code == 403
    assert upload(ctx).status_code == 403
    ctx["headers"]["X-CSRF-Token"] = csrf
    token = ctx["client"].post("/api/tokens", json={"name": "Importer"}, headers=ctx["headers"]).json()["raw_token"]
    ctx["client"].cookies.clear()
    ctx["headers"] = {"Authorization": f"Bearer {token}"}
    assert upload(ctx, preview=True).status_code == 200
    assert upload(ctx).status_code == 201
    ctx["headers"] = {"Authorization": "Bearer invalid"}
    # Invalid credentials do not bypass the application's existing CSRF middleware.
    assert upload(ctx).status_code == 403


@pytest.mark.parametrize("change", [
    lambda d: d.pop("lists"),
    lambda d: d.update(cards={}),
    lambda d: d["lists"].append(copy.deepcopy(d["lists"][0])),
    lambda d: d["cards"].append(copy.deepcopy(d["cards"][0])),
    lambda d: d["cards"][0].update(pos="invalid"),
    lambda d: d["cards"][0].update(due="not-a-date"),
    lambda d: d["cards"][0].update(name="x" * 201),
    lambda d: d["cards"][0].update(closed="false"),
    lambda d: d["cards"][1].update(desc="x" * 10_000),
    lambda d: d["cards"][1].update(idChecklists=["missing"]),
    lambda d: d["checklists"][0]["checkItems"][0].update(state="invalid"),
])
def test_malformed_exports_are_rejected_before_writes(ctx, change):
    data = export_data()
    change(data)
    response = upload(ctx, data)
    assert response.status_code == 400, response.text
    assert ctx["db"].query(ctx["models"].Board).count() == 0


@pytest.mark.parametrize("content", [b"not json", b"[]", b"{}", b"\xff", b'{"name":"n","lists":[],"cards":[],"n":NaN}', b"[" * 2000 + b"]" * 2000])
def test_invalid_json_is_rejected(ctx, content):
    assert upload(ctx, content=content).status_code == 400


def test_upload_size_limits_apply_to_preview_import_and_chunked_requests(ctx):
    small = json.dumps(export_data()).encode()
    exact = small + b" " * (10 * 1024 * 1024 - len(small))
    assert upload(ctx, content=exact, preview=True).status_code == 200
    for preview in (True, False):
        assert upload(ctx, content=exact + b" ", preview=preview).status_code == 413
        response = upload(ctx, content=exact + b" " * (128 * 1024), preview=preview)
        assert response.status_code == 413
        assert response.headers["x-content-type-options"] == "nosniff"
        chunked = ctx["client"].post(
            "/api/boards/import-trello" + ("/preview" if preview else ""),
            content=iter([b"x" * 1024 * 1024] * 11),
            headers={**ctx["headers"], "Content-Type": "multipart/form-data; boundary=test"},
        )
        assert chunked.status_code == 413
    assert ctx["db"].query(ctx["models"].Board).count() == 0


def test_empty_board_and_utf8_bom_are_supported(ctx):
    content = b"\xef\xbb\xbf" + json.dumps({"name": "H\u00fcb", "lists": [], "cards": []}, ensure_ascii=False).encode()
    response = upload(ctx, content=content)
    assert response.status_code == 201, response.text
    assert response.json()["stage_count"] == 0
    assert ctx["db"].get(ctx["models"].Board, response.json()["board_id"]).name == "H\u00fcb"
