from datetime import date
import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def history_env(app_env):
    main, db, models = (app_env[key] for key in ("main", "db", "models"))
    users = [models.User(email=f"history-{index}@example.invalid", display_name=name,
                         password_hash="unused", is_active=True)
             for index, name in enumerate(("Alice", "Bob", "Viewer", "Outsider"))]
    db.add_all(users)
    db.flush()
    board = models.Board(name="History", owner_user_id=users[0].id)
    db.add(board)
    db.flush()
    stages = [models.Stage(name=name, board_id=board.id) for name in ("Inbox", "Next")]
    db.add_all(stages)
    db.add_all([models.BoardMembership(board_id=board.id, user_id=user.id, role=role)
                for user, role in zip(users, ("owner", "editor", "viewer"))])
    db.commit()

    def client_for(user):
        token, csrf = main.create_user_session(user, db)
        client = TestClient(main.app, base_url="https://testserver")
        client.cookies.set("questline_session", token)
        client.cookies.set("questline_csrf", csrf)
        client.headers.update({"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf})
        return client

    client = client_for(users[0])
    response = client.post("/api/tasks", json={"title": "Review release", "stage_id": stages[0].id})
    response.raise_for_status()
    task_id = response.json()["id"]
    url = f"/api/tasks/{task_id}"

    def events():
        response = client.get(f"{url}/history", params={"limit": 100})
        response.raise_for_status()
        return list(reversed(response.json()["items"]))

    return {**app_env, "users": users, "board": board, "stages": stages, "client": client,
            "client_for": client_for, "task_id": task_id, "url": url, "events": events}


def test_critical_events_have_actor_timestamp_and_no_value_diffs(history_env):
    ctx = history_env
    client, url = ctx["client"], ctx["url"]
    client.put(url, json={"title": "Ship", "description": "Release notes",
                          "assignee_user_ids": [ctx["users"][1].id],
                          "due_date": "2026-12-01", "due_time": "14:30",
                          "due_timezone": "Europe/Berlin"}).raise_for_status()
    client.put(url, json={"done": True}).raise_for_status()
    client.put(url, json={"done": False}).raise_for_status()
    client.put(f"{url}/move", json={"stage_id": ctx["stages"][1].id, "position": 0}).raise_for_status()
    client.put(url, json={"due_date": None}).raise_for_status()
    events = ctx["events"]()
    assert [e["event_type"] for e in events] == [
        "task_created", "title_updated", "description_updated", "assignees_updated",
        "deadline_updated", "task_completed", "task_reopened", "stage_changed", "deadline_removed",
    ]
    assert all(e["actor_name"] == "Alice" and e["actor_user_id"] == ctx["users"][0].id for e in events)
    assert all(e["created_at"].endswith("Z") for e in events)
    assert all(e["subject"] is None for e in events)
    assert "Release notes" not in str(events)


def test_noops_normalized_assignees_deadlines_and_untracked_fields_are_silent(history_env):
    ctx = history_env
    client, url = ctx["client"], ctx["url"]
    ids = [user.id for user in ctx["users"][:2]]
    body = {"title": "Review release", "description": "", "done": False,
            "due_date": "2026-12-01", "due_time": "14:30", "due_timezone": "Europe/Berlin",
            "assignee_user_ids": ids}
    client.put(url, json=body).raise_for_status()
    before = ctx["events"]()
    client.put(url, json={**body, "assignee_user_ids": [ids[1], ids[0], ids[1]]}).raise_for_status()
    client.put(url, json={"due_time": "14:30"}).raise_for_status()
    client.put(f"{url}/move", json={"stage_id": ctx["stages"][0].id, "position": 8}).raise_for_status()
    client.put(url, json={"color": "#ff0000", "show_description_on_card": True}).raise_for_status()
    client.put(url, json={}).raise_for_status()
    assert ctx["events"]() == before
    client.put(url, json={"due_time": None}).raise_for_status()
    assert ctx["events"]()[-1]["event_type"] == "deadline_updated"


def test_checklist_add_rename_complete_reopen_remove_and_noops(history_env):
    ctx = history_env
    client, url = ctx["client"], ctx["url"]
    item = client.post(f"{url}/checklist", json={"title": "Test release"}).json()
    item_url = f"{url}/checklist/{item['id']}"
    client.put(item_url, json={"title": "Run checks", "done": True}).raise_for_status()
    before = ctx["events"]()
    client.put(item_url, json={"title": "Run checks", "done": True}).raise_for_status()
    assert ctx["events"]() == before
    client.put(item_url, json={"done": False}).raise_for_status()
    client.delete(item_url).raise_for_status()
    events = ctx["events"]()[1:]
    assert [e["event_type"] for e in events] == ["checklist_item_added", "checklist_item_renamed",
        "checklist_item_completed", "checklist_item_reopened", "checklist_item_removed"]
    assert events[0]["subject"] == "Test release"
    assert all(e["subject"] == "Run checks" for e in events[1:])
    assert all(e["actor_name"] == "Alice" for e in events)


def test_automations_record_actual_changes_separately_from_the_user(history_env):
    ctx = history_env
    db, models = ctx["db"], ctx["models"]
    db.add(models.Automation(name="Move done", board_id=ctx["board"].id, enabled=True,
                            trigger_type="task_done", action_type="move_to_stage",
                            action_stage_id=ctx["stages"][1].id))
    db.commit()
    ctx["client"].put(ctx["url"], json={"done": True}).raise_for_status()
    events = ctx["events"]()
    assert [(e["event_type"], e["actor_name"]) for e in events] == [
        ("task_created", "Alice"), ("task_completed", "Alice"), ("stage_changed", "Automation")]
    assert events[-1]["actor_user_id"] is None
    task = db.get(models.Task, ctx["task_id"])
    automation = db.query(models.Automation).one()
    ctx["main"].apply_automation(task, automation, db)
    db.commit()
    assert ctx["events"]() == events


def test_bulk_moves_only_record_stage_changes(history_env):
    ctx = history_env
    payload = {"stage_id": ctx["stages"][1].id, "ids": [ctx["task_id"]]}
    ctx["client"].put("/api/tasks/reorder", json=payload).raise_for_status()
    before = ctx["events"]()
    assert before[-1]["event_type"] == "stage_changed"
    ctx["client"].put("/api/tasks/reorder", json=payload).raise_for_status()
    assert ctx["events"]() == before


def test_history_access_and_cursor_pagination(history_env):
    ctx = history_env
    for index in range(5):
        ctx["client"].put(ctx["url"], json={"title": f"Revision {index}"}).raise_for_status()
    viewer = ctx["client_for"](ctx["users"][2])
    history_url = f"{ctx['url']}/history"
    all_ids = []
    before_id = None
    while True:
        page = viewer.get(history_url, params={"limit": 2, **({"before_id": before_id} if before_id else {})}).json()
        all_ids.extend(event["id"] for event in page["items"])
        before_id = page["next_before_id"]
        if before_id is None:
            break
    assert all_ids == sorted({e["id"] for e in ctx["events"]()}, reverse=True)
    assert ctx["client_for"](ctx["users"][3]).get(history_url).status_code == 403
    assert TestClient(ctx["main"].app).get(history_url).status_code == 401
    assert viewer.get("/api/tasks/999999/history").status_code == 404
    assert viewer.get(history_url, params={"limit": 101}).status_code == 422
    assert viewer.get(history_url, params={"before_id": 0}).status_code == 422


def test_failed_writes_and_transaction_rollbacks_leave_no_history(history_env):
    ctx = history_env
    before = ctx["events"]()
    assert ctx["client"].put(ctx["url"], json={"description": "Bad", "due_date": "not a date"}).status_code == 422
    assert ctx["client"].put(ctx["url"], json={"description": "Bad", "assignee_user_ids": [ctx["users"][3].id]}).status_code == 400
    history = importlib.import_module("services.task_history")
    task = ctx["db"].get(ctx["models"].Task, ctx["task_id"])
    previous = history.task_history_snapshot(task)
    task.description = "Rolled back"
    history.record_task_changes(task, previous, ctx["db"], ctx["users"][0])
    ctx["db"].flush()
    ctx["db"].rollback()
    assert ctx["events"]() == before
    assert ctx["client"].get(ctx["url"]).json()["description"] == ""


def test_actor_name_survives_account_rename_and_deletion(history_env):
    ctx = history_env
    editor = ctx["client_for"](ctx["users"][1])
    editor.put(ctx["url"], json={"description": "By Bob"}).raise_for_status()
    ctx["users"][1].display_name = "Robert"
    ctx["db"].commit()
    assert ctx["events"]()[-1]["actor_name"] == "Bob"
    ctx["db"].delete(ctx["users"][1])
    ctx["db"].commit()
    event = ctx["events"]()[-1]
    assert event["actor_user_id"] is None
    assert event["actor_name"] == "Bob"


def test_api_token_changes_are_attributed_to_the_owner(history_env):
    ctx = history_env
    raw, digest, last_four = importlib.import_module("authz").generate_api_token()
    ctx["db"].add(ctx["models"].ApiToken(user_id=ctx["users"][1].id, name="CLI", token_hash=digest,
                                       last_four=last_four))
    ctx["db"].commit()
    client = TestClient(ctx["main"].app)
    client.put(ctx["url"], headers={"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"},
               json={"description": "Via API"}).raise_for_status()
    assert ctx["events"]()[-1]["actor_name"] == "Bob"


def test_linked_objectives_and_parent_checklists_both_receive_actual_changes(history_env):
    ctx = history_env
    db, models, client, url = ctx["db"], ctx["models"], ctx["client"], ctx["url"]
    task_type = models.TaskType(name="Quest", is_epic=True, board_id=ctx["board"].id)
    db.add(task_type)
    db.commit()
    client.put(url, json={"task_type_id": task_type.id}).raise_for_status()
    item = client.post(f"{url}/checklist", json={"title": "Child"}).json()
    child_url = f"/api/tasks/{item['spawned_task_id']}"
    assert client.get(f"{child_url}/history").json()["items"][0]["actor_name"] == "Alice"
    client.put(f"{url}/checklist/{item['id']}", json={"title": "Renamed child"}).raise_for_status()
    assert client.get(f"{child_url}/history").json()["items"][0]["event_type"] == "title_updated"
    client.put(child_url, json={"title": "New title"}).raise_for_status()
    assert ctx["events"]()[-1]["event_type"] == "checklist_item_renamed"
    client.put(url, json={"done": True}).raise_for_status()
    assert [e["event_type"] for e in ctx["events"]()][-2:] == ["task_completed", "checklist_item_completed"]
    child_events = client.get(f"{child_url}/history").json()["items"]
    assert child_events[0]["event_type"] == "task_completed"
    before = ctx["events"]()
    client.put(url, json={"done": True}).raise_for_status()
    assert ctx["events"]() == before
    client.delete(child_url).raise_for_status()
    assert ctx["events"]()[-1]["event_type"] == "checklist_item_removed"


def test_recurrence_reuse_records_changes_as_automation(history_env):
    ctx = history_env
    client, url, db, models = ctx["client"], ctx["url"], ctx["db"], ctx["models"]
    client.post(f"{url}/checklist", json={"title": "Check"}).raise_for_status()
    client.put(url, json={"done": True}).raise_for_status()
    recurrence = models.TaskRecurrence(task_id=ctx["task_id"], frequency="daily", interval=1,
        mode="reuse_existing", next_run_on="2026-11-03", spawn_stage_id=ctx["stages"][1].id)
    db.add(recurrence)
    db.commit()
    ctx["main"].process_due_recurrences(db, today=date(2026, 11, 3))
    events = ctx["events"]()[-4:]
    assert {e["event_type"] for e in events} == {
        "checklist_item_reopened", "stage_changed", "task_reopened", "deadline_updated"}
    assert all(e["actor_name"] == "Automation" for e in events)


def test_history_cascades_on_task_and_board_deletion_and_legacy_rows_are_empty(history_env):
    ctx = history_env
    legacy = ctx["models"].Task(title="Existing", stage_id=ctx["stages"][0].id)
    ctx["db"].add(legacy)
    ctx["db"].commit()
    assert ctx["client"].get(f"/api/tasks/{legacy.id}/history").json()["items"] == []
    ctx["client"].delete(ctx["url"]).raise_for_status()
    assert ctx["db"].query(ctx["models"].TaskHistoryEvent).count() == 0
    ctx["client"].post("/api/tasks", json={"title": "New", "stage_id": ctx["stages"][0].id}).raise_for_status()
    ctx["client"].delete(f"/api/boards/{ctx['board'].id}").raise_for_status()
    assert ctx["db"].query(ctx["models"].TaskHistoryEvent).count() == 0


def test_existing_database_gets_an_empty_history_table_without_changing_tasks(history_env):
    ctx = history_env
    engine = ctx["database"].engine
    with engine.begin() as connection:
        before = connection.execute(text("SELECT id, title, updated_at FROM tasks")).all()
        connection.execute(text("DROP TABLE task_history_events"))
    for _ in range(2):
        ctx["models"].Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, title, updated_at FROM tasks")).all() == before
        assert connection.execute(text("SELECT COUNT(*) FROM task_history_events")).scalar() == 0
