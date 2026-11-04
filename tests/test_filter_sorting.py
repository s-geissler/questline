from datetime import datetime
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def sort_env(app_env):
    main, db, models = (app_env[key] for key in ("main", "db", "models"))
    user = models.User(email="sort@example.com", display_name="Sorter", password_hash="unused")
    db.add(user)
    db.flush()
    board = models.Board(name="Sorting", owner_user_id=user.id)
    db.add(board)
    db.flush()
    db.add(models.BoardMembership(board_id=board.id, user_id=user.id, role="owner"))
    source = models.Stage(name="Inbox", board_id=board.id)
    log = models.Stage(name="Log", board_id=board.id, is_log=True)
    task_type = models.TaskType(name="Issue", board_id=board.id)
    db.add_all([source, log, task_type])
    db.flush()
    priority = models.CustomFieldDef(name="Priority", task_type_id=task_type.id, field_type="dropdown",
                                     options=json.dumps(["High", {"label": "Medium"}, {"label": "Low"}]))
    db.add(priority)
    # Deliberately store the old shape, without rewriting it through the new parser.
    legacy_definition = {"op": "and", "rules": []}
    saved = models.SavedFilter(name="Old filter", board_id=board.id, definition=json.dumps(legacy_definition))
    db.add(saved)
    db.flush()
    log.filter_id = saved.id
    db.commit()
    token, csrf = main.create_user_session(user, db)
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set("questline_session", token)
    client.cookies.set("questline_csrf", csrf)
    client.headers.update({"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf})

    def task(title, priority_value=None, **values):
        row = models.Task(title=title, stage_id=source.id, task_type_id=task_type.id,
                          created_at=datetime(2026, 11, 1), position=db.query(models.Task).count(), **values)
        db.add(row)
        db.flush()
        if priority_value is not None:
            db.add(models.CustomFieldValue(task_id=row.id, field_def_id=priority.id, value=priority_value))
        db.commit()
        return row

    def set_sort(sort_rules, **definition):
        response = client.put(f"/api/filters/{saved.id}", json={"definition": {
            **legacy_definition, **definition, "sort_rules": sort_rules,
        }})
        assert response.status_code == 200, response.text
        return response.json()

    def log_tasks():
        response = client.get(f"/api/stages?board_id={board.id}")
        assert response.status_code == 200, response.text
        return next(stage for stage in response.json() if stage["id"] == log.id)["tasks"]

    return {**app_env, "user": user, "board": board, "source": source, "log": log,
            "type": task_type, "priority": priority, "saved": saved, "client": client,
            "task": task, "set_sort": set_sort, "log_tasks": log_tasks}


def test_legacy_filters_keep_order_and_source_positions_until_sorting_is_added(sort_env):
    ctx = sort_env
    a = ctx["task"]("A", "High", due_date="2026-11-05")
    b = ctx["task"]("B", "Low", due_date="2026-11-04")
    c = ctx["task"]("C", "High", due_date="2026-11-04")
    original_json = ctx["saved"].definition
    assert [task["id"] for task in ctx["log_tasks"]()] == [c.id, b.id, a.id]
    assert ctx["client"].get(f"/api/filters?board_id={ctx['board'].id}").json()[0]["definition"]["sort_rules"] == []
    ctx["db"].refresh(ctx["saved"])
    assert ctx["saved"].definition == original_json  # Reading performs no migration/write.
    url = f"/api/filters/{ctx['saved'].id}"
    ctx["client"].put(url, json={"name": "Rename only"}).raise_for_status()
    assert [task["id"] for task in ctx["log_tasks"]()] == [c.id, b.id, a.id]
    ctx["set_sort"]([{"field": "title", "direction": "asc"}])
    assert [task["id"] for task in ctx["log_tasks"]()] == [a.id, b.id, c.id]
    # An older client can update conditions without unknowingly clearing sorting.
    response = ctx["client"].put(url, json={"definition": {"op": "and", "rules": []}})
    assert response.json()["definition"]["sort_rules"] == [{"field": "title", "direction": "asc"}]
    ctx["set_sort"]([])
    assert [task["id"] for task in ctx["log_tasks"]()] == [c.id, b.id, a.id]
    response = ctx["client"].get(f"/api/stages?board_id={ctx['board'].id}").json()
    source_tasks = next(stage for stage in response if stage["id"] == ctx["source"].id)["tasks"]
    assert [(task["id"], task["position"]) for task in source_tasks] == [(a.id, 0), (b.id, 1), (c.id, 2)]


@pytest.mark.parametrize("direction,expected", [
    ("asc", ["Earlier", "High newer", "High older", "Medium", "Low", "Unknown", "Empty", "Undated"]),
    ("desc", ["Earlier", "Low", "Medium", "High newer", "High older", "Unknown", "Empty", "Undated"]),
])
def test_multiple_rules_dropdown_order_missing_values_and_stable_ties(sort_env, direction, expected):
    ctx = sort_env
    for title, priority in [("Empty", None), ("Unknown", "Deleted option"), ("Low", "Low"),
                            ("High older", "High"), ("High newer", "High"), ("Medium", "Medium")]:
        ctx["task"](title, priority, due_date="2026-11-05")
    ctx["task"]("Earlier", "Low", due_date="2026-11-04")
    ctx["task"]("Undated", "High")
    ctx["set_sort"]([{"field": "due_date", "direction": "asc"},
                     {"field": f"custom:{ctx['priority'].id}", "direction": direction}])
    assert [task["title"] for task in ctx["log_tasks"]()] == expected


@pytest.mark.parametrize("field_type,values,expected", [
    ("number", ["10", "2", "-1", "1.5", "NaN", "not a number", "Infinity"], ["-1", "1.5", "2", "10", "Infinity", "not a number", "NaN"]),
    ("text", ["zebra", "Apple", "banana"], ["Apple", "banana", "zebra"]),
    ("date", ["2026-11-12", "2026-11-02", "2026-11-05", "2026-02-30"], ["2026-11-02", "2026-11-05", "2026-11-12", "2026-02-30"]),
])
def test_custom_field_sorting_uses_the_field_type(sort_env, field_type, values, expected):
    ctx = sort_env
    ctx["priority"].field_type = field_type
    ctx["db"].commit()
    for value in values:
        ctx["task"](value, value)
    ctx["set_sort"]([{"field": f"custom:{ctx['priority'].id}", "direction": "asc"}])
    assert [task["title"] for task in ctx["log_tasks"]()] == expected


def test_due_date_sort_honors_optional_times_and_keeps_empty_dates_last_when_descending(sort_env):
    ctx = sort_env
    ctx["task"]("Undated")
    ctx["task"]("All day", due_date="2026-11-04")
    ctx["task"]("Later instant", due_date="2026-11-04", due_time="14:00", due_timezone="UTC")
    ctx["task"]("Earlier instant", due_date="2026-11-04", due_time="14:30", due_timezone="Europe/Berlin")
    ctx["task"]("Next day", due_date="2026-11-05")
    ctx["set_sort"]([{"field": "due_date", "direction": "asc"}])
    assert [task["title"] for task in ctx["log_tasks"]()] == ["All day", "Earlier instant", "Later instant", "Next day", "Undated"]
    ctx["set_sort"]([{"field": "due_date", "direction": "desc"}])
    assert [task["title"] for task in ctx["log_tasks"]()] == ["Next day", "Later instant", "Earlier instant", "All day", "Undated"]


@pytest.mark.parametrize("rules", [None, {}, [None], [{"field": "title"}],
    [{"field": "title", "direction": "sideways"}], [{"field": {}, "direction": "asc"}],
    [{"field": "title", "direction": []}], [{"field": "custom:nope", "direction": "asc"}],
    [{"field": "unknown", "direction": "asc"}], [{"field": "custom:99999", "direction": "asc"}],
    [{"field": "custom:9223372036854775808", "direction": "asc"}],
    [{"field": "custom:" + "9" * 5000, "direction": "asc"}],
    [{"field": "title", "direction": "asc"}] * 2,
    [{"field": "title", "direction": "asc"}] * 11,
])
def test_invalid_sort_rules_are_rejected_without_changing_the_filter(sort_env, rules):
    ctx = sort_env
    before = ctx["saved"].definition
    response = ctx["client"].put(f"/api/filters/{ctx['saved'].id}", json={
        "name": "Must not change", "definition": {"sort_rules": rules},
    })
    assert response.status_code == 400, response.text
    ctx["db"].refresh(ctx["saved"])
    assert ctx["saved"].name == "Old filter"
    assert ctx["saved"].definition == before


def test_custom_sort_field_must_belong_to_this_hub_and_selected_type(sort_env):
    ctx = sort_env
    other = ctx["models"].Board(name="Private")
    ctx["db"].add(other)
    ctx["db"].flush()
    task_type = ctx["models"].TaskType(name="Private type", board_id=other.id)
    ctx["db"].add(task_type)
    ctx["db"].flush()
    field = ctx["models"].CustomFieldDef(name="Secret", task_type_id=task_type.id)
    ctx["db"].add(field)
    local_type = ctx["models"].TaskType(name="Other local type", board_id=ctx["board"].id)
    ctx["db"].add(local_type)
    ctx["db"].commit()
    for definition in [
        {"sort_rules": [{"field": f"custom:{field.id}", "direction": "asc"}]},
        {"selected_task_type_id": local_type.id, "sort_rules": [{"field": f"custom:{ctx['priority'].id}", "direction": "asc"}]},
    ]:
        response = ctx["client"].post("/api/filters", json={"board_id": ctx["board"].id, "name": "Invalid", "definition": definition})
        assert response.status_code == 400, response.text


def test_deleted_custom_field_and_malformed_legacy_sorts_do_not_break_logs(sort_env):
    ctx = sort_env
    ctx["task"]("First", "High")
    ctx["task"]("Second", "Low")
    ctx["set_sort"]([{"field": f"custom:{ctx['priority'].id}", "direction": "asc"}])
    ctx["db"].delete(ctx["priority"])
    ctx["db"].commit()
    assert [task["title"] for task in ctx["log_tasks"]()] == ["Second", "First"]
    ctx["db"].refresh(ctx["saved"])
    ctx["saved"].definition = json.dumps({"sort_rules": [None, {"field": "title", "direction": []}]})
    ctx["db"].commit()
    assert [task["title"] for task in ctx["log_tasks"]()] == ["Second", "First"]


def test_sorted_log_still_applies_conditions_and_viewer_cannot_change_sorting(sort_env):
    ctx = sort_env
    ctx["task"]("Z open", "Low")
    ctx["task"]("A done", "High", done=True)
    ctx["task"]("B open", "High")
    ctx["set_sort"]([{"field": "title", "direction": "asc"}], rules=[{"field": "done", "operator": "eq", "value": False}])
    assert [task["title"] for task in ctx["log_tasks"]()] == ["B open", "Z open"]
    membership = ctx["db"].query(ctx["models"].BoardMembership).filter_by(user_id=ctx["user"].id).one()
    membership.role = "viewer"
    ctx["board"].owner_user_id = None
    ctx["db"].commit()
    response = ctx["client"].put(f"/api/filters/{ctx['saved'].id}", json={"definition": {"sort_rules": []}})
    assert response.status_code == 403, response.text
    assert [task["title"] for task in ctx["log_tasks"]()] == ["B open", "Z open"]
