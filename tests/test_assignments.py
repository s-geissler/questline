from datetime import date
import importlib

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import text


@pytest.fixture()
def assignment_env(app_env):
    main, db, models = (app_env[key] for key in ("main", "db", "models"))
    users = [models.User(email=f"person{index}@example.com", display_name=name,
                         password_hash="unused", is_active=True)
             for index, name in enumerate(("Alice Adams", "Bob Brown", "Carol Cruz", "Outsider"))]
    db.add_all(users)
    db.flush()
    board = models.Board(name="Assignments", owner_user_id=users[0].id)
    db.add(board)
    db.flush()
    db.add_all([models.BoardMembership(board_id=board.id, user_id=user.id, role=role)
                for user, role in zip(users, ("owner", "editor", "viewer"))])
    stage = models.Stage(name="Inbox", board_id=board.id)
    db.add(stage)
    db.flush()
    task = models.Task(title="Shared work", stage_id=stage.id, due_date=date.today().isoformat())
    db.add(task)
    db.commit()

    def client_for(user):
        token, csrf = main.create_user_session(user, db)
        client = TestClient(main.app, base_url="https://testserver")
        client.cookies.set("questline_session", token)
        client.cookies.set("questline_csrf", csrf)
        client.headers.update({"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf})
        return client

    return {**app_env, "users": users, "board": board, "stage": stage, "task": task,
            "client_for": client_for, "client": client_for(users[0]), "url": f"/api/tasks/{task.id}"}


def test_multiple_assignees_round_trip_replace_clear_and_legacy_api(assignment_env):
    ctx = assignment_env
    client, url = ctx["client"], ctx["url"]
    alice, bob, carol, _ = ctx["users"]
    response = client.put(url, json={"assignee_user_ids": [carol.id, bob.id, bob.id]})
    assert response.status_code == 200, response.text
    expected = [bob.id, carol.id]
    assert response.json()["assignee_user_ids"] == expected
    assert [user["display_name"] for user in response.json()["assignees"]] == ["Bob Brown", "Carol Cruz"]
    assert response.json()["assignee_user_id"] == bob.id
    assert client.get(url).json()["assignee_user_ids"] == expected
    assert client.put(url, json={"description": "Keep assignments"}).json()["assignee_user_ids"] == expected
    stages = client.get(f"/api/stages?board_id={ctx['board'].id}").json()
    assert stages[0]["tasks"][0]["assignee_user_ids"] == expected
    ctx["db"].expire_all()
    assert ctx["main"].task_to_dict(ctx["task"])["assignee_user_ids"] == expected
    assert client.put(url, json={"assignee_user_ids": [alice.id, carol.id]}).json()["assignee_user_ids"] == [alice.id, carol.id]
    legacy = client.put(url, json={"assignee_user_id": bob.id}).json()
    assert legacy["assignee_user_ids"] == [bob.id]
    assert legacy["assignee"]["id"] == bob.id
    assert client.put(url, json={"assignee_user_id": None}).json()["assignees"] == []
    client.put(url, json={"assignee_user_ids": expected}).raise_for_status()
    cleared = client.put(url, json={"assignee_user_ids": []}).json()
    assert cleared["assignee"] is None and cleared["assignee_user_id"] is None
    assert cleared["assignees"] == cleared["assignee_user_ids"] == []


@pytest.mark.parametrize("invalid", ["outsider", "inactive", "missing", "null", "both"])
def test_invalid_assignment_list_is_rejected_without_partial_updates(assignment_env, invalid):
    ctx = assignment_env
    _, bob, carol, outsider = ctx["users"]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [bob.id]}).raise_for_status()
    values = {"assignee_user_ids": [bob.id, carol.id]}
    if invalid == "outsider":
        values["assignee_user_ids"].append(outsider.id)
    elif invalid == "inactive":
        carol.is_active = False
        ctx["db"].commit()
    elif invalid == "missing":
        values["assignee_user_ids"].append(99999)
    elif invalid == "null":
        values["assignee_user_ids"] = None
    else:
        values["assignee_user_id"] = bob.id
    response = ctx["client"].put(ctx["url"], json={"title": "Must not change", **values})
    assert response.status_code in {400, 422}, response.text
    saved = ctx["client"].get(ctx["url"]).json()
    assert saved["title"] == "Shared work"
    assert saved["assignee_user_ids"] == [bob.id]


def test_only_editors_can_change_assignments_and_former_members_can_be_removed(assignment_env):
    ctx = assignment_env
    _, bob, carol, outsider = ctx["users"]
    for user, status in ((carol, 403), (outsider, 403)):
        response = ctx["client_for"](user).put(ctx["url"], json={"assignee_user_ids": [bob.id]})
        assert response.status_code == status, response.text
    assert ctx["client_for"](bob).put(ctx["url"], json={"assignee_user_ids": [bob.id, carol.id]}).status_code == 200
    bob.is_active = False
    ctx["db"].query(ctx["models"].BoardMembership).filter_by(board_id=ctx["board"].id, user_id=carol.id).delete()
    ctx["db"].commit()
    # Removing one former assignee must not require revalidating another retained one.
    assert ctx["client"].put(ctx["url"], json={"assignee_user_ids": [carol.id]}).json()["assignee_user_ids"] == [carol.id]
    assert ctx["client"].put(ctx["url"], json={"assignee_user_ids": []}).json()["assignee_user_ids"] == []
    assert ctx["client"].put(ctx["url"], json={"assignee_user_ids": [carol.id]}).status_code == 400


def test_notifications_reach_all_new_assignees_and_due_reminders_are_per_user(assignment_env):
    ctx = assignment_env
    alice, bob, carol, _ = ctx["users"]
    for ids in ([alice.id, bob.id], [alice.id, bob.id, carol.id], [carol.id, bob.id, alice.id]):
        ctx["client"].put(ctx["url"], json={"assignee_user_ids": ids}).raise_for_status()
    ctx["db"].expire_all()
    rows = ctx["db"].query(ctx["models"].Notification).filter_by(type="task_assigned").all()
    assert sorted(row.user_id for row in rows) == [bob.id, carol.id]
    notifications = importlib.import_module("services.notifications")
    for user in (alice, bob, carol):
        for _ in range(2):
            notifications.generate_due_notifications_for_user(user, ctx["db"])
    due_rows = ctx["db"].query(ctx["models"].Notification).filter_by(type="task_due_today").all()
    assert sorted(row.user_id for row in due_rows) == [alice.id, bob.id, carol.id]


def test_calendar_filter_matches_a_secondary_assignee_once(assignment_env):
    ctx = assignment_env
    _, bob, carol, _ = ctx["users"]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [bob.id, carol.id]}).raise_for_status()
    client = ctx["client_for"](carol)
    response = client.post("/api/calendar-feeds", json={"name": "My tasks", "assigned_only": True})
    assert response.status_code == 201, response.text
    url = response.json()["subscription_url"]
    events = Calendar.from_ical(client.get(url).content).walk("VEVENT")
    assert [str(event["SUMMARY"]) for event in events] == ["Shared work"]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [bob.id]}).raise_for_status()
    assert Calendar.from_ical(client.get(url).content).walk("VEVENT") == []


@pytest.mark.parametrize("operator,value,expected", [
    ("eq", "__me__", ["Shared work"]), ("neq", "__me__", ["Unassigned"]),
    ("empty", None, ["Unassigned"]), ("not_empty", None, ["Shared work"]),
    ("eq", "specific", ["Shared work"]),
])
def test_saved_filters_match_any_assignee_in_sql_and_python(assignment_env, operator, value, expected):
    ctx = assignment_env
    _, bob, carol, _ = ctx["users"]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [bob.id, carol.id]}).raise_for_status()
    ctx["db"].add(ctx["models"].Task(title="Unassigned", stage_id=ctx["stage"].id))
    ctx["db"].commit()
    logic = importlib.import_module("filters_logic")
    rule = {"field": "assignee_user_id", "operator": operator,
            "value": str(carol.id) if value == "specific" else value}
    definition = {"rules": [rule]}
    tasks = ctx["db"].query(ctx["models"].Task)
    sql_result = logic._prefilter_log_query(tasks, definition, carol).all()
    python_result = [task for task in tasks.all() if logic._task_matches_filter(task, definition, carol)]
    assert sorted(task.title for task in sql_result) == expected
    assert sorted(task.title for task in python_result) == expected


def test_recurrence_copies_every_assignee(assignment_env):
    ctx = assignment_env
    _, bob, carol, _ = ctx["users"]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [bob.id, carol.id]}).raise_for_status()
    ctx["db"].expire_all()
    recurrence = ctx["models"].TaskRecurrence(task_id=ctx["task"].id, mode="create_new", frequency="daily",
                                              interval=1, next_run_on="2026-11-04", spawn_stage_id=ctx["stage"].id)
    ctx["db"].add(recurrence)
    ctx["db"].commit()
    cloned = ctx["main"]._clone_task_from_recurrence(ctx["task"], recurrence, ctx["db"])
    payload = ctx["main"].task_to_dict(cloned)
    assert payload["assignee_user_ids"] == [bob.id, carol.id]
    assert payload["assignee_user_id"] == bob.id


def test_legacy_assignment_migration_is_additive_idempotent_and_clear_stays_cleared(assignment_env):
    ctx = assignment_env
    _, bob, _, _ = ctx["users"]
    task = ctx["task"]
    task.assignee_user_id = bob.id
    ctx["db"].commit()
    engine = ctx["database"].engine
    with engine.begin() as conn:
        before = conn.execute(text("SELECT id, title, calendar_uid, updated_at, assignee_user_id FROM tasks")).fetchall()
        conn.execute(text("DROP TABLE task_assignees"))
    ctx["models"].Base.metadata.create_all(bind=engine)
    tasks = importlib.import_module("services.tasks")
    for _ in range(2):
        tasks.backfill_task_assignees(engine)
        ctx["db"].expire_all()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id, title, calendar_uid, updated_at, assignee_user_id FROM tasks")).fetchall() == before
            assert conn.execute(text("SELECT task_id, user_id FROM task_assignees")).fetchall() == [(task.id, bob.id)]
        assert ctx["client"].get(ctx["url"]).json()["assignee_user_ids"] == [bob.id]
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": []}).raise_for_status()
    tasks.backfill_task_assignees(engine)
    assert ctx["client"].get(ctx["url"]).json()["assignee_user_ids"] == []


def test_task_deletion_cleans_up_all_assignment_rows(assignment_env):
    ctx = assignment_env
    ctx["client"].put(ctx["url"], json={"assignee_user_ids": [user.id for user in ctx["users"][:3]]}).raise_for_status()
    assert ctx["client"].delete(ctx["url"]).status_code == 200
    assert ctx["db"].execute(text("SELECT * FROM task_assignees")).fetchall() == []
