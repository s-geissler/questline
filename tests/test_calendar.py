from __future__ import annotations

import importlib
import logging
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import text


def write_headers(client):
    return {"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": client.cookies.get("questline_csrf", "")}


def events(response):
    assert response.status_code == 200, response.text
    return Calendar.from_ical(response.content).walk("VEVENT")


@pytest.fixture()
def calendar_env(app_env):
    main, db, models = app_env["main"], app_env["db"], app_env["models"]
    digest = main.hash_password("supersecret")
    alice = models.User(email="alice@example.com", display_name="Alice", password_hash=digest, is_active=True)
    bob = models.User(email="bob@example.com", display_name="Bob", password_hash=digest, is_active=True)
    db.add_all([alice, bob])
    db.flush()
    team = models.Board(name="Team", owner_user_id=alice.id)
    second = models.Board(name="Second", owner_user_id=alice.id)
    private = models.Board(name="Private", owner_user_id=bob.id)
    db.add_all([team, second, private])
    db.flush()
    db.add_all([
        models.BoardMembership(board_id=team.id, user_id=alice.id, role="editor"),
        models.BoardMembership(board_id=second.id, user_id=alice.id, role="viewer"),
        models.BoardMembership(board_id=private.id, user_id=bob.id, role="owner"),
    ])
    stages = [models.Stage(name="Backlog", board_id=board.id) for board in (team, second, private)]
    db.add_all(stages)
    db.commit()

    def login(user):
        client = TestClient(main.app, base_url="https://testserver")
        result = client.post("/api/auth/login", json={"email": user.email, "password": "supersecret"},
                             headers={"X-Requested-With": "XMLHttpRequest"})
        assert result.status_code == 200, result.text
        return client

    client = login(alice)

    def task(title="Ship release", stage=None, **values):
        values.setdefault("due_date", "2026-10-14")
        row = models.Task(title=title, stage_id=(stage or stages[0]).id, **values)
        db.add(row)
        db.commit()
        return row

    def feed(**values):
        result = client.post("/api/calendar-feeds", json={"name": "Thunderbird", **values}, headers=write_headers(client))
        assert result.status_code == 201, result.text
        return result.json()

    return {**app_env, "alice": alice, "bob": bob, "team": team, "second": second, "private": private,
            "stages": stages, "client": client, "reader": TestClient(main.app, base_url="https://testserver"),
            "login": login, "task": task, "feed": feed}


def test_calendar_serializes_date_only_deadlines_and_escapes_text(calendar_env, caplog):
    ctx = calendar_env
    title = "Review Würzburg, 東京; " + "é" * 100
    description = "Notes, with semicolons; and a backslash \\\nBEGIN:VEVENT\nSUMMARY:Injected\nEND:VEVENT"
    task = ctx["task"](title, description=description, updated_at=datetime(2020, 1, 1))
    ctx["task"]("No deadline", due_date=None)
    ctx["task"]("Completed", done=True)
    bad = ctx["task"]("Malformed", due_date="2026-02-30")
    ctx["task"]("Private", stage=ctx["stages"][2])
    log_stage = ctx["models"].Stage(name="Log view", board_id=ctx["team"].id, is_log=True)
    ctx["db"].add(log_stage)
    ctx["db"].commit()
    ctx["task"]("Invalid legacy log task", stage=log_stage)
    url = ctx["feed"]()["subscription_url"]
    response = ctx["reader"].get(url)
    parsed = events(response)
    assert len(parsed) == 1
    event = parsed[0]
    assert str(event["SUMMARY"]) == title
    assert str(event["DESCRIPTION"]) == description
    assert event["DTSTART"].dt == date(2026, 10, 14)
    assert event["DTEND"].dt == date(2026, 10, 15)
    assert event["DTSTART"].params["VALUE"] == "DATE"
    assert str(event["TRANSP"]) == "TRANSPARENT"
    assert str(event["UID"]) == f"{task.calendar_uid}@questline"
    assert str(event["URL"]) == f"https://testserver/board/{ctx['team'].id}?task_id={task.id}"
    assert "text/calendar" in response.headers["content-type"]
    assert all(len(line) <= 75 for line in response.content.split(b"\r\n"))
    assert f"task_id={bad.id}" in caplog.text
    assert "2026-02-30" not in caplog.text
    assert "Injected" not in caplog.text


@pytest.mark.parametrize("single_hub,assigned_only,expected", [
    (False, False, {"Assigned", "Unassigned", "Second hub"}),
    (False, True, {"Assigned", "Second hub"}),
    (True, False, {"Assigned", "Unassigned"}),
    (True, True, {"Assigned"}),
])
def test_feed_scope_and_assignment_filter(calendar_env, single_hub, assigned_only, expected):
    ctx = calendar_env
    ctx["task"]("Assigned", assignee_user_id=ctx["alice"].id)
    ctx["task"]("Unassigned")
    ctx["task"]("Second hub", stage=ctx["stages"][1], assignee_user_id=ctx["alice"].id)
    ctx["task"]("Private", stage=ctx["stages"][2], assignee_user_id=ctx["alice"].id)
    feed = ctx["feed"](board_id=ctx["team"].id if single_hub else None, assigned_only=assigned_only)
    assert {str(event["SUMMARY"]) for event in events(ctx["reader"].get(feed["subscription_url"]))} == expected


def test_feed_management_keeps_secrets_out_of_lists_database_and_audit_logs(calendar_env, caplog):
    ctx = calendar_env
    caplog.set_level(logging.INFO)
    created = ctx["feed"](board_id=ctx["team"].id)
    raw = parse_qs(urlsplit(created["subscription_url"]).query)["token"][0]
    row = ctx["db"].get(ctx["models"].CalendarFeed, created["id"])
    assert raw.startswith("qlcal_")
    assert row.token_hash != raw
    assert created["last_four"] == raw[-4:]
    listed = ctx["client"].get("/api/calendar-feeds")
    assert listed.headers["cache-control"] == "no-store"
    assert len(listed.json()) == 1
    assert "subscription_url" not in listed.json()[0]
    assert "token_hash" not in listed.text
    assert raw not in listed.text
    assert raw not in caplog.text
    outsider = ctx["login"](ctx["bob"])
    assert outsider.get("/api/calendar-feeds").json() == []
    assert outsider.delete(f"/api/calendar-feeds/{created['id']}", headers=write_headers(outsider)).status_code == 404
    assert outsider.post(f"/api/calendar-feeds/{created['id']}/rotate", headers=write_headers(outsider)).status_code == 404


def test_feed_rotation_and_revocation_invalidate_old_urls_before_cache_checks(calendar_env):
    ctx = calendar_env
    created = ctx["feed"]()
    old_url = created["subscription_url"]
    etag = ctx["reader"].get(old_url).headers["etag"]
    rotated = ctx["client"].post(f"/api/calendar-feeds/{created['id']}/rotate", headers=write_headers(ctx["client"]))
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    new_url = rotated.json()["subscription_url"]
    assert new_url != old_url
    assert ctx["reader"].get(old_url, headers={"If-None-Match": etag}).status_code == 404
    assert ctx["reader"].get(new_url).status_code == 200
    revoked = ctx["client"].delete(f"/api/calendar-feeds/{created['id']}", headers=write_headers(ctx["client"]))
    assert revoked.status_code == 200
    assert ctx["reader"].head(new_url, headers={"If-None-Match": "*"}).status_code == 404
    assert ctx["client"].get("/api/calendar-feeds").json() == []


def test_feed_requires_its_own_secret_and_cannot_authenticate_the_general_api(calendar_env):
    ctx = calendar_env
    ctx["task"]()
    feed = ctx["feed"]()
    url = feed["subscription_url"]
    path = urlsplit(url).path
    raw = parse_qs(urlsplit(url).query)["token"][0]
    assert ctx["client"].get(path).status_code == 404  # A session does not replace the feed secret.
    assert ctx["reader"].get(f"{path}?token=incorrect").status_code == 404
    assert ctx["reader"].get(path, headers={"Authorization": f"Bearer {raw}"}).status_code == 404
    api_result = ctx["reader"].get("/api/boards", headers={"Authorization": f"Bearer {raw}"})
    assert api_result.status_code == 401
    assert ctx["reader"].put(url, content="BEGIN:VCALENDAR").status_code == 405
    outsider = ctx["login"](ctx["bob"])
    assert {str(event["SUMMARY"]) for event in events(outsider.get(url))} == {"Ship release"}


def test_current_permissions_are_rechecked_for_aggregate_and_single_hub_feeds(calendar_env):
    ctx = calendar_env
    ctx["task"]("Team")
    ctx["task"]("Second", stage=ctx["stages"][1])
    aggregate = ctx["feed"]()["subscription_url"]
    scoped = ctx["feed"](board_id=ctx["team"].id)["subscription_url"]
    old_etag = ctx["reader"].get(aggregate).headers["etag"]
    membership = ctx["db"].query(ctx["models"].BoardMembership).filter_by(
        board_id=ctx["team"].id, user_id=ctx["alice"].id
    ).one()
    ctx["db"].delete(membership)
    ctx["db"].commit()
    refreshed = ctx["reader"].get(aggregate, headers={"If-None-Match": old_etag})
    assert {str(event["SUMMARY"]) for event in events(refreshed)} == {"Second"}
    assert refreshed.headers["etag"] != old_etag
    denied = ctx["reader"].get(scoped, headers={"If-None-Match": "*"})
    assert denied.status_code == 404
    assert denied.headers["cache-control"] == "no-store"
    listed = ctx["client"].get("/api/calendar-feeds").json()
    assert next(feed for feed in listed if feed["board_id"] is not None)["available"] is False


@pytest.mark.parametrize("action", ["deactivate", "delete_user", "delete_board"])
def test_feed_stops_working_when_its_owner_or_hub_is_unavailable(calendar_env, action):
    ctx = calendar_env
    url = ctx["feed"](board_id=ctx["team"].id)["subscription_url"]
    if action == "deactivate":
        ctx["alice"].is_active = False
    elif action == "delete_user":
        ctx["team"].owner_user_id = None
        ctx["second"].owner_user_id = None
        ctx["db"].delete(ctx["alice"])
    else:
        ctx["db"].delete(ctx["team"])
    ctx["db"].commit()
    assert ctx["reader"].get(url, headers={"If-None-Match": "*"}).status_code == 404


def test_admin_feeds_follow_admin_access_and_role_changes(calendar_env):
    ctx = calendar_env
    ctx["task"]("Private", stage=ctx["stages"][2])
    ctx["alice"].role = "admin"
    ctx["db"].commit()
    url = ctx["feed"]()["subscription_url"]
    assert len(events(ctx["reader"].get(url))) == 1
    ctx["alice"].role = "user"
    ctx["db"].commit()
    assert events(ctx["reader"].get(url)) == []


def test_conditional_get_and_head_have_stable_etags_and_valid_empty_calendars(calendar_env):
    ctx = calendar_env
    url = ctx["feed"]()["subscription_url"]
    first = ctx["reader"].get(url)
    second = ctx["reader"].get(url)
    assert events(first) == []
    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"
    head = ctx["reader"].head(url)
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(first.content))
    assert head.headers["etag"] == first.headers["etag"]
    for value in (first.headers["etag"], f'"other", W/{first.headers["etag"]}', "*"):
        response = ctx["reader"].get(url, headers={"If-None-Match": value})
        assert response.status_code == 304
        assert response.content == b""
    assert ctx["reader"].get(url, headers={"If-None-Match": '"other"'}).status_code == 200


def test_deadline_edits_keep_event_identity_and_update_modification_time(calendar_env):
    ctx = calendar_env
    task = ctx["task"](updated_at=datetime(2020, 1, 1))
    url = ctx["feed"]()["subscription_url"]
    before = ctx["reader"].get(url)
    original = events(before)[0]
    update = ctx["client"].put(f"/api/tasks/{task.id}", headers=write_headers(ctx["client"]),
                               json={"title": "Renamed", "description": "Updated notes", "due_date": "2026-10-20"})
    assert update.status_code == 200, update.text
    refreshed = ctx["reader"].get(url, headers={"If-None-Match": before.headers["etag"]})
    event = events(refreshed)[0]
    assert event["UID"] == original["UID"]
    assert event["DTSTART"].dt == date(2026, 10, 20)
    assert str(event["SUMMARY"]) == "Renamed"
    assert str(event["DESCRIPTION"]) == "Updated notes"
    assert event["LAST-MODIFIED"].dt > original["LAST-MODIFIED"].dt


@pytest.mark.parametrize("action", ["complete", "clear_deadline", "delete"])
def test_tasks_disappear_on_refresh_and_recreated_ids_have_new_uids(calendar_env, action):
    ctx = calendar_env
    task = ctx["task"]()
    task_id = task.id
    url = ctx["feed"]()["subscription_url"]
    before = ctx["reader"].get(url)
    uid = str(events(before)[0]["UID"])
    if action == "delete":
        result = ctx["client"].delete(f"/api/tasks/{task_id}", headers=write_headers(ctx["client"]))
    else:
        result = ctx["client"].put(f"/api/tasks/{task_id}", headers=write_headers(ctx["client"]),
                                   json={"done": True} if action == "complete" else {"due_date": None})
    assert result.status_code == 200
    assert events(ctx["reader"].get(url, headers={"If-None-Match": before.headers["etag"]})) == []
    if action == "delete":
        ctx["db"].expunge(task)
        replacement = ctx["task"]("Replacement")
        assert replacement.id == task_id  # SQLite can reuse its highest deleted ID.
        assert str(events(ctx["reader"].get(url))[0]["UID"]) != uid


@pytest.mark.parametrize("mode", ["create_new", "reuse_existing"])
def test_recurrence_exports_only_materialized_deadlines_with_correct_identity(calendar_env, mode):
    ctx = calendar_env
    task = ctx["task"](due_date="2026-10-13", updated_at=datetime(2020, 1, 1))
    original_uid = task.calendar_uid
    ctx["main"].upsert_task_recurrence(task.id, ctx["main"].TaskRecurrenceUpdate(
        enabled=True, mode=mode, frequency="daily", interval=1,
        next_run_on="2026-10-14", spawn_stage_id=ctx["stages"][0].id,
    ), ctx["db"])
    url = ctx["feed"]()["subscription_url"]
    assert len(events(ctx["reader"].get(url))) == 1
    assert ctx["main"].process_due_recurrences(ctx["db"], today=date(2026, 10, 14)) == 1
    parsed = events(ctx["reader"].get(url))
    assert len(parsed) == (2 if mode == "create_new" else 1)
    assert all("RRULE" not in event for event in parsed)
    new = next(event for event in parsed if event["DTSTART"].dt == date(2026, 10, 14))
    assert (str(new["UID"]) == f"{original_uid}@questline") == (mode == "reuse_existing")
    assert all(event["DTSTART"].dt <= date(2026, 10, 14) for event in parsed)


def test_automation_and_linked_checklist_edits_update_calendar_metadata(calendar_env):
    ctx = calendar_env
    models, db, main = ctx["models"], ctx["db"], ctx["main"]
    task = ctx["task"](updated_at=datetime(2020, 1, 1))
    uid = task.calendar_uid
    main.apply_automation(task, models.Automation(action_type="set_due_in_days", action_days_offset=3), db)
    db.commit()
    assert task.calendar_uid == uid
    assert task.updated_at > datetime(2020, 1, 1)
    parent = ctx["task"]("Quest", due_date=None)
    item = models.ChecklistItem(task_id=parent.id, title="Linked", spawned_task_id=task.id)
    db.add(item)
    db.commit()
    url = ctx["feed"]()["subscription_url"]
    result = ctx["client"].put(f"/api/tasks/{parent.id}/checklist/{item.id}",
                               json={"title": "Checklist rename"}, headers=write_headers(ctx["client"]))
    assert result.status_code == 200, result.text
    event = events(ctx["reader"].get(url))[0]
    assert str(event["SUMMARY"]) == "Checklist rename"
    assert str(event["UID"]) == f"{uid}@questline"


@pytest.mark.parametrize("value", ["not-a-date", "2026-02-30", "20261014", "2026-10-14T12:00:00"])
def test_task_create_and_update_reject_invalid_deadlines(calendar_env, value):
    ctx = calendar_env
    task = ctx["task"]()
    headers = write_headers(ctx["client"])
    created = ctx["client"].post("/api/tasks", json={"title": "Invalid", "stage_id": task.stage_id, "due_date": value}, headers=headers)
    updated = ctx["client"].put(f"/api/tasks/{task.id}", json={"due_date": value}, headers=headers)
    assert created.status_code == 422
    assert updated.status_code == 422
    ctx["db"].refresh(task)
    assert task.due_date == "2026-10-14"


def test_feed_creation_requires_auth_csrf_and_current_hub_access(calendar_env):
    ctx = calendar_env
    assert ctx["reader"].get("/api/calendar-feeds").status_code == 401
    assert ctx["client"].post("/api/calendar-feeds", json={}).status_code == 403
    assert ctx["client"].post("/api/calendar-feeds", json={"board_id": ctx["private"].id}, headers=write_headers(ctx["client"])).status_code == 403
    assert ctx["client"].post("/api/calendar-feeds", json={"board_id": 999}, headers=write_headers(ctx["client"])).status_code == 404
    assert ctx["client"].post("/api/calendar-feeds", json={"name": "  "}, headers=write_headers(ctx["client"])).status_code == 422
    # Viewer access is sufficient for a read-only subscription.
    url = ctx["feed"](board_id=ctx["second"].id)["subscription_url"]
    assert ctx["reader"].get(url).status_code == 200


def test_public_base_url_controls_subscription_and_task_links(calendar_env, monkeypatch):
    ctx = calendar_env
    monkeypatch.setenv("QUESTLINE_PUBLIC_BASE_URL", "https://questline.example/questline/")
    ctx["task"]()
    feed = ctx["feed"]()
    assert feed["subscription_url"].startswith("https://questline.example/questline/calendar/")
    parsed_url = urlsplit(feed["subscription_url"])
    local_url = parsed_url.path.removeprefix("/questline") + "?" + parsed_url.query
    event = events(ctx["reader"].get(local_url, headers={"Host": "untrusted.example"}))[0]
    assert str(event["URL"]).startswith("https://questline.example/questline/board/")


@pytest.mark.parametrize("url", ["ftp://example.com", "https://user:password@example.com", "https://example.com?token=secret", "https://example.com#fragment", "http://example.com", "https://[invalid"])
def test_public_base_url_rejects_invalid_production_configuration(app_env, monkeypatch, url):
    monkeypatch.setenv("QUESTLINE_ENV", "production")
    monkeypatch.setenv("QUESTLINE_PUBLIC_BASE_URL", url)
    with pytest.raises(RuntimeError):
        importlib.import_module("services.calendar").validate_public_base_url()


def test_legacy_database_calendar_backfill_is_idempotent(app_env):
    main, db, models = app_env["main"], app_env["db"], app_env["models"]
    board = models.Board(name="Legacy")
    db.add(board)
    db.flush()
    stage = models.Stage(name="Backlog", board_id=board.id)
    db.add(stage)
    db.flush()
    task = models.Task(title="Legacy", stage_id=stage.id, created_at=datetime(2020, 1, 1))
    db.add(task)
    db.commit()
    task_id = task.id
    with app_env["database"].engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_tasks_calendar_uid"))
        conn.execute(text("ALTER TABLE tasks DROP COLUMN calendar_uid"))
        conn.execute(text("ALTER TABLE tasks DROP COLUMN updated_at"))
    calendar = importlib.import_module("services.calendar")
    for _ in range(2):
        main._run_column_migrations()
        calendar.backfill_calendar_metadata(app_env["database"].engine)
        main._run_index_migrations()
        db.expire_all()
        row = db.get(models.Task, task_id)
        assert row.updated_at == datetime(2020, 1, 1)
        if _ == 0:
            uid = row.calendar_uid
        else:
            assert row.calendar_uid == uid
    new = models.Task(title="New", stage_id=stage.id)
    db.add(new)
    db.commit()
    assert new.calendar_uid and new.calendar_uid != uid


@pytest.mark.parametrize("key", ["token", "%74oken"])
def test_calendar_access_logs_redact_entire_query_strings(app_env, key):
    calendar = importlib.import_module("services.calendar")
    calendar.configure_calendar_access_logging()
    target = f"/calendar/feed.ics?{key}=secret&other=secret"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %s',
                               ("127.0.0.1", "GET", target, "1.1", 200), None)
    assert logging.getLogger("uvicorn.access").filter(record)
    assert "secret" not in record.getMessage()
    assert "/calendar/feed.ics?[redacted]" in record.getMessage()


def test_calendar_stage_choices_include_only_accessible_normal_stages(calendar_env):
    ctx = calendar_env
    ctx["task"]("Do not return objectives")
    log_stage = ctx["models"].Stage(name="Log", board_id=ctx["team"].id, is_log=True)
    ctx["db"].add(log_stage)
    ctx["db"].commit()
    assert ctx["reader"].get("/api/calendar-feeds/stages").status_code == 401
    response = ctx["client"].get("/api/calendar-feeds/stages")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert {item["id"] for item in response.json()} == {stage.id for stage in ctx["stages"][:2]}
    assert all(set(item) == {"id", "name", "board_id", "board_name"} for item in response.json())
    assert "Do not return objectives" not in response.text
    ctx["alice"].role = "admin"
    ctx["db"].commit()
    assert {item["id"] for item in ctx["client"].get("/api/calendar-feeds/stages").json()} == {
        stage.id for stage in ctx["stages"]
    }


@pytest.mark.parametrize("single_hub,assigned_only", [(True, False), (True, True), (False, False), (False, True)])
def test_stage_selection_composes_with_hub_and_assignee_filters(calendar_env, single_hub, assigned_only):
    ctx = calendar_env
    other = ctx["models"].Stage(name="Later", board_id=ctx["team"].id)
    ctx["db"].add(other)
    ctx["db"].commit()
    ctx["task"]("Assigned", assignee_user_id=ctx["alice"].id)
    ctx["task"]("Unassigned")
    ctx["task"]("Excluded", stage=other, assignee_user_id=ctx["alice"].id)
    ctx["task"]("Second hub", stage=ctx["stages"][1], assignee_user_id=ctx["alice"].id)
    selected = [ctx["stages"][0].id] + ([] if single_hub else [ctx["stages"][1].id])
    feed = ctx["feed"](board_id=ctx["team"].id if single_hub else None,
                       assigned_only=assigned_only, stage_ids=selected)
    assert feed["stage_ids"] == sorted(selected)
    expected = {"Assigned"}
    if not assigned_only:
        expected.add("Unassigned")
    if not single_hub:
        expected.add("Second hub")
    assert {str(event["SUMMARY"]) for event in events(ctx["reader"].get(feed["subscription_url"]))} == expected


def test_stage_selection_validation_rejects_empty_invalid_private_and_out_of_scope_stages(calendar_env):
    ctx = calendar_env
    log_stage = ctx["models"].Stage(name="Log", board_id=ctx["team"].id, is_log=True)
    ctx["db"].add(log_stage)
    ctx["db"].commit()
    feed = ctx["feed"](board_id=ctx["team"].id, stage_ids=[ctx["stages"][0].id])
    headers = write_headers(ctx["client"])
    for selection in ([], [9999], [0], [-1], [ctx["stages"][2].id], [ctx["stages"][1].id], [log_stage.id]):
        created = ctx["client"].post("/api/calendar-feeds", headers=headers,
                                     json={"board_id": ctx["team"].id, "stage_ids": selection})
        updated = ctx["client"].patch(f"/api/calendar-feeds/{feed['id']}", headers=headers,
                                     json={"stage_ids": selection})
        assert created.status_code == updated.status_code == 422
    listed = ctx["client"].get("/api/calendar-feeds").json()
    assert len(listed) == 1
    assert listed[0]["stage_ids"] == [ctx["stages"][0].id]


def test_editing_stage_selection_keeps_url_and_event_identity(calendar_env):
    ctx = calendar_env
    first = ctx["task"]("First")
    ctx["task"]("Second", stage=ctx["stages"][1])
    feed = ctx["feed"]()
    url = feed["subscription_url"]
    before = ctx["reader"].get(url)
    headers = write_headers(ctx["client"])
    path = f"/api/calendar-feeds/{feed['id']}"
    assert ctx["reader"].patch(path, json={"stage_ids": None}, headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 403
    assert ctx["client"].patch(path, json={"stage_ids": None}).status_code == 403
    assert ctx["client"].patch(path, json={}, headers=headers).status_code == 422
    outsider = ctx["login"](ctx["bob"])
    assert outsider.patch(path, json={"stage_ids": None}, headers=write_headers(outsider)).status_code == 404
    changed = ctx["client"].patch(path, json={"stage_ids": [first.stage_id, first.stage_id]}, headers=headers)
    assert changed.status_code == 200
    assert changed.headers["cache-control"] == "no-store"
    assert changed.json()["stage_ids"] == [first.stage_id]
    assert "subscription_url" not in changed.json()
    after = ctx["reader"].get(url, headers={"If-None-Match": before.headers["etag"]})
    event = events(after)[0]
    assert str(event["SUMMARY"]) == "First"
    assert str(event["UID"]) == f"{first.calendar_uid}@questline"
    assert after.headers["etag"] != before.headers["etag"]
    restored = ctx["client"].patch(path, json={"stage_ids": None}, headers=headers)
    assert restored.json()["stage_ids"] is None
    assert len(events(ctx["reader"].get(url))) == 2


def test_task_moves_and_new_stages_follow_the_saved_selection(calendar_env):
    ctx = calendar_env
    task = ctx["task"]()
    all_url = ctx["feed"]()["subscription_url"]
    selected_url = ctx["feed"](stage_ids=[task.stage_id])["subscription_url"]
    new_stage = ctx["models"].Stage(name="New", board_id=ctx["team"].id)
    ctx["db"].add(new_stage)
    ctx["db"].commit()
    ctx["task"]("New stage task", stage=new_stage)
    assert len(events(ctx["reader"].get(all_url))) == 2
    assert len(events(ctx["reader"].get(selected_url))) == 1
    task.stage_id = new_stage.id
    ctx["db"].commit()
    assert events(ctx["reader"].get(selected_url)) == []
    task.stage_id = ctx["stages"][0].id
    ctx["db"].commit()
    assert str(events(ctx["reader"].get(selected_url))[0]["UID"]) == f"{task.calendar_uid}@questline"


def test_deleted_selected_stage_does_not_turn_into_all_stages_or_include_a_reused_id(calendar_env):
    ctx = calendar_env
    stage = ctx["models"].Stage(name="Temporary", board_id=ctx["team"].id)
    ctx["db"].add(stage)
    ctx["db"].commit()
    stage_id = stage.id
    ctx["task"]("Temporary", stage=stage)
    feed = ctx["feed"](stage_ids=[stage_id])
    deleted = ctx["client"].delete(f"/api/stages/{stage_id}", headers=write_headers(ctx["client"]))
    assert deleted.status_code == 200
    ctx["db"].expunge(stage)
    replacement = ctx["models"].Stage(name="Replacement", board_id=ctx["team"].id)
    ctx["db"].add(replacement)
    ctx["db"].commit()
    assert replacement.id == stage_id
    ctx["task"]("Replacement", stage=replacement)
    listed = ctx["client"].get("/api/calendar-feeds").json()[0]
    assert listed["stage_ids"] == []
    assert events(ctx["reader"].get(feed["subscription_url"])) == []


def test_stage_selection_rechecks_access_and_hides_unavailable_stage_names(calendar_env):
    ctx = calendar_env
    ctx["stages"][0].name = "Restricted stage"
    ctx["db"].commit()
    ctx["task"]("Team")
    ctx["task"]("Second", stage=ctx["stages"][1])
    selected = [stage.id for stage in ctx["stages"][:2]]
    feed = ctx["feed"](stage_ids=selected)
    membership = ctx["db"].query(ctx["models"].BoardMembership).filter_by(
        board_id=ctx["team"].id, user_id=ctx["alice"].id
    ).one()
    ctx["db"].delete(membership)
    ctx["db"].commit()
    assert {str(event["SUMMARY"]) for event in events(ctx["reader"].get(feed["subscription_url"]))} == {"Second"}
    listed = ctx["client"].get("/api/calendar-feeds")
    assert listed.json()[0]["stage_ids"] == selected
    assert "Restricted stage" not in listed.text
    denied = ctx["client"].patch(f"/api/calendar-feeds/{feed['id']}", json={"stage_ids": selected},
                                  headers=write_headers(ctx["client"]))
    assert denied.status_code == 422


def test_existing_feed_migration_defaults_to_all_stages(calendar_env):
    ctx = calendar_env
    ctx["task"]()
    feed = ctx["feed"]()
    with ctx["database"].engine.begin() as conn:
        conn.execute(text("ALTER TABLE calendar_feeds DROP COLUMN all_stages"))
    for _ in range(2):
        ctx["main"]._run_column_migrations()
        listed = ctx["client"].get("/api/calendar-feeds").json()[0]
        assert listed["stage_ids"] is None
        assert len(events(ctx["reader"].get(feed["subscription_url"]))) == 1
