from datetime import UTC, date, datetime
import importlib

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import text


@pytest.fixture()
def deadline_env(app_env):
    main, db, models = (app_env[key] for key in ("main", "db", "models"))
    user = models.User(email="deadlines@example.com", display_name="Owner", password_hash="unused")
    db.add(user)
    db.flush()
    board = models.Board(name="Deadlines", owner_user_id=user.id)
    db.add(board)
    db.flush()
    db.add(models.BoardMembership(board_id=board.id, user_id=user.id, role="owner"))
    stage = models.Stage(name="Inbox", board_id=board.id)
    db.add(stage)
    db.commit()
    token, csrf = main.create_user_session(user, db)
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set("questline_session", token)
    client.cookies.set("questline_csrf", csrf)
    client.headers.update({"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf})

    def create(**values):
        response = client.post("/api/tasks", json={"title": "Deadline", "stage_id": stage.id, **values})
        assert response.status_code == 200, response.text
        return response.json()

    return {**app_env, "user": user, "board": board, "stage": stage, "client": client, "create": create}


def test_optional_time_round_trip_and_partial_updates(deadline_env):
    ctx = deadline_env
    client = ctx["client"]
    task = ctx["create"](due_date="2026-11-03")
    assert (task["due_time"], task["due_timezone"], task["due_at"]) == (None, None, None)
    url = f"/api/tasks/{task['id']}"
    timed = client.put(url, json={"due_time": "14:30", "due_timezone": "Europe/Berlin"}).json()
    assert timed["due_date"] == "2026-11-03"
    assert timed["due_at"] == "2026-11-03T13:30:00Z"
    assert client.get(url).json()["due_time"] == "14:30"
    stage_task = client.get(f"/api/stages?board_id={ctx['board'].id}").json()[0]["tasks"][0]
    assert stage_task["due_at"] == timed["due_at"]
    assert ctx["main"].task_to_dict(ctx["db"].get(ctx["models"].Task, task["id"]))["due_at"] == timed["due_at"]

    # Old clients and calendar dragging only send the date; retain time and zone.
    moved = client.put(url, json={"due_date": "2026-07-03"}).json()
    assert moved["due_time"] == "14:30"
    assert moved["due_timezone"] == "Europe/Berlin"
    assert moved["due_at"] == "2026-07-03T12:30:00Z"
    assert client.put(url, json={"title": "Renamed"}).json()["due_at"] == moved["due_at"]

    cleared_time = client.put(url, json={"due_time": None}).json()
    assert cleared_time["due_date"] == moved["due_date"]
    assert (cleared_time["due_time"], cleared_time["due_timezone"], cleared_time["due_at"]) == (None, None, None)
    client.put(url, json={"due_time": "00:00", "due_timezone": "UTC"}).raise_for_status()
    cleared_date = client.put(url, json={"due_date": None}).json()
    assert all(cleared_date[field] is None for field in ("due_date", "due_time", "due_timezone", "due_at"))


@pytest.mark.parametrize("values", [
    {"due_time": "25:00", "due_timezone": "UTC"},
    {"due_time": "12:60", "due_timezone": "UTC"},
    {"due_time": "9:30", "due_timezone": "UTC"},
    {"due_time": "12:30:00", "due_timezone": "UTC"},
    {"due_time": "14:30", "due_timezone": "Not/AZone"},
    {"due_time": "14:30", "due_timezone": "../Europe/Berlin"},
    {"due_time": "14:30"},
    {"due_date": None, "due_time": "14:30", "due_timezone": "UTC"},
])
def test_invalid_times_rejected_without_mutating_task(deadline_env, values):
    ctx = deadline_env
    task = ctx["create"](due_date="2026-11-03")
    body = {"due_date": "2026-11-03", **values}
    created = ctx["client"].post("/api/tasks", json={"title": "Invalid", "stage_id": ctx["stage"].id, **body})
    updated = ctx["client"].put(f"/api/tasks/{task['id']}", json={"title": "Must not change", **body})
    assert created.status_code == updated.status_code == 422
    saved = ctx["client"].get(f"/api/tasks/{task['id']}").json()
    assert saved["title"] == "Deadline"
    assert saved["due_date"] == "2026-11-03"
    assert saved["due_time"] is None


@pytest.mark.parametrize("day,time,zone,expected", [
    ("2026-01-03", "14:30", "Europe/Berlin", "2026-01-03T13:30:00Z"),
    ("2026-07-03", "14:30", "Europe/Berlin", "2026-07-03T12:30:00Z"),
    ("2026-11-03", "00:00", "Asia/Kolkata", "2026-11-02T18:30:00Z"),
    ("2026-10-25", "02:30", "Europe/Berlin", "2026-10-25T00:30:00Z"),
    ("2026-03-29", "02:30", "Europe/Berlin", "2026-03-29T01:30:00Z"),
])
def test_deadline_timezone_and_dst_resolution(deadline_env, day, time, zone, expected):
    task = deadline_env["create"](due_date=day, due_time=time, due_timezone=zone)
    assert task["due_at"] == expected
    assert task["due_time"] == time


def test_feed_switches_between_all_day_and_timed_without_changing_uid(deadline_env):
    ctx = deadline_env
    client = ctx["client"]
    task = ctx["create"](due_date="2026-11-03")
    response = client.post("/api/calendar-feeds", json={"name": "Mixed deadlines"})
    assert response.status_code == 201, response.text
    url = response.json()["subscription_url"]
    all_day = client.get(url)
    event = Calendar.from_ical(all_day.content).walk("VEVENT")[0]
    uid = str(event["UID"])
    assert event["DTSTART"].dt == date(2026, 11, 3)
    assert event["DTEND"].dt == date(2026, 11, 4)

    client.put(f"/api/tasks/{task['id']}", json={"due_time": "14:30", "due_timezone": "Europe/Berlin"}).raise_for_status()
    timed = client.get(url, headers={"If-None-Match": all_day.headers["ETag"]})
    assert timed.status_code == 200
    event = Calendar.from_ical(timed.content).walk("VEVENT")[0]
    assert str(event["UID"]) == uid
    assert event["DTSTART"].dt == datetime(2026, 11, 3, 13, 30, tzinfo=UTC)
    assert "DTEND" not in event  # A deadline has an instant, without an invented duration.
    assert str(event["TRANSP"]) == "TRANSPARENT"
    assert client.get(url, headers={"If-None-Match": timed.headers["ETag"]}).status_code == 304

    client.put(f"/api/tasks/{task['id']}", json={"due_time": None}).raise_for_status()
    restored = Calendar.from_ical(client.get(url).content).walk("VEVENT")[0]
    assert str(restored["UID"]) == uid
    assert restored["DTSTART"].params["VALUE"] == "DATE"
    assert restored["DTEND"].dt == date(2026, 11, 4)


@pytest.mark.parametrize("mode", ["create_new", "reuse_existing"])
def test_recurrence_and_due_date_automation_preserve_wall_time(deadline_env, mode):
    ctx = deadline_env
    task = ctx["create"](due_date="2026-10-24", due_time="14:30", due_timezone="Europe/Berlin")
    response = ctx["client"].put(f"/api/tasks/{task['id']}/recurrence", json={
        "enabled": True, "mode": mode, "frequency": "daily", "interval": 1,
        "next_run_on": "2026-10-26", "spawn_stage_id": ctx["stage"].id,
    })
    assert response.status_code == 200, response.text
    assert ctx["main"].process_due_recurrences(ctx["db"], today=date(2026, 10, 26)) == 1
    row = ctx["db"].query(ctx["models"].Task).filter_by(due_date="2026-10-26").one()
    saved = ctx["client"].get(f"/api/tasks/{row.id}").json()
    assert saved["due_time"] == "14:30"
    assert saved["due_timezone"] == "Europe/Berlin"
    assert saved["due_at"] == "2026-10-26T13:30:00Z"
    ctx["main"].apply_automation(row, ctx["models"].Automation(action_type="set_due_in_days", action_days_offset=2), ctx["db"])
    ctx["db"].commit()
    assert row.due_time == "14:30"
    assert row.due_timezone == "Europe/Berlin"


def test_time_migration_preserves_existing_rows_and_is_idempotent(deadline_env):
    ctx = deadline_env
    dated = ctx["create"](title="Existing date", due_date="2026-11-03")
    undated = ctx["create"](title="No deadline")
    engine = ctx["database"].engine
    with engine.begin() as conn:
        before = conn.execute(text("SELECT id, title, due_date, calendar_uid, updated_at FROM tasks ORDER BY id")).fetchall()
        conn.execute(text("ALTER TABLE tasks DROP COLUMN due_time"))
        conn.execute(text("ALTER TABLE tasks DROP COLUMN due_timezone"))
    for _ in range(2):
        ctx["main"]._run_column_migrations()
        ctx["db"].expire_all()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id, title, due_date, calendar_uid, updated_at FROM tasks ORDER BY id")).fetchall() == before
        assert ctx["client"].get(f"/api/tasks/{dated['id']}").json()["due_time"] is None
        assert ctx["client"].get(f"/api/tasks/{undated['id']}").json()["due_date"] is None
    upgraded = ctx["client"].put(f"/api/tasks/{dated['id']}", json={"due_time": "14:30", "due_timezone": "UTC"})
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["due_at"] == "2026-11-03T14:30:00Z"


def test_timed_notifications_use_deadline_instant_and_timezone(deadline_env, monkeypatch):
    ctx = deadline_env
    notifications = importlib.import_module("services.notifications")

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 3, 0, 15, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(notifications, "datetime", FixedDatetime)
    # It is still November 2 in this deadline's timezone, though UTC is November 3.
    overdue = ctx["create"](title="Past time", due_date="2026-11-02", due_time="16:00", due_timezone="America/Los_Angeles")
    upcoming = ctx["create"](title="Later today", due_date="2026-11-02", due_time="18:00", due_timezone="America/Los_Angeles")
    for task in (overdue, upcoming):
        ctx["db"].get(ctx["models"].Task, task["id"]).assignee_user_id = ctx["user"].id
    ctx["db"].commit()
    for _ in range(2):
        notifications.generate_due_notifications_for_user(ctx["user"], ctx["db"])
    rows = ctx["db"].query(ctx["models"].Notification).all()
    assert {(row.task_id, row.type) for row in rows} == {
        (overdue["id"], "task_overdue"), (upcoming["id"], "task_due_today"),
    }
    assert len(rows) == 2
