"""Private iCalendar subscriptions and stable task event serialization."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from fastapi import HTTPException, Request
from icalendar import Calendar, Event
from sqlalchemy import or_, text
from sqlalchemy.orm import Session, contains_eager

import models
from authz import get_accessible_boards, require_board_access
from services.tasks import normalize_due_date

log = logging.getLogger("questline.calendar")
TOKEN_PREFIX = "qlcal_"


def generate_calendar_token() -> tuple[str, str, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_calendar_token(raw), raw[-4:]


def hash_calendar_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_public_base_url() -> str:
    configured = os.getenv("QUESTLINE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not configured:
        return ""
    try:
        parsed = urlsplit(configured)
        parsed.port
    except ValueError:
        raise RuntimeError("QUESTLINE_PUBLIC_BASE_URL must be a valid HTTP(S) URL") from None
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(character) < 32 for character in configured)
    ):
        raise RuntimeError("QUESTLINE_PUBLIC_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment")
    if os.getenv("QUESTLINE_ENV", "production").lower() == "production" and parsed.scheme != "https":
        raise RuntimeError("QUESTLINE_PUBLIC_BASE_URL must use HTTPS in production")
    return configured


def public_base_url(request: Request) -> str:
    return validate_public_base_url() or str(request.base_url).rstrip("/")


def subscription_url(feed: models.CalendarFeed, raw: str, request: Request) -> str:
    return f"{public_base_url(request)}/calendar/{feed.id}.ics?{urlencode({'token': raw})}"


def backfill_calendar_metadata(engine) -> None:
    """Backfill old SQLite tables after the startup column migrations."""
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id FROM tasks WHERE calendar_uid IS NULL OR calendar_uid = ''"
        )).fetchall()
        for (task_id,) in rows:
            conn.execute(text(
                "UPDATE tasks SET calendar_uid = :uid WHERE id = :id "
                "AND (calendar_uid IS NULL OR calendar_uid = '')"
            ), {"uid": str(uuid4()), "id": task_id})
        conn.execute(text(
            "UPDATE tasks SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        ))


def authenticate_calendar_feed(feed_id: str, raw: str | None, db: Session) -> models.CalendarFeed:
    unavailable = HTTPException(
        status_code=404, detail="Calendar feed not found", headers={"Cache-Control": "no-store"}
    )
    if not raw or len(raw) > 128 or len(feed_id) != 36:
        raise unavailable
    feed = db.query(models.CalendarFeed).filter(
        models.CalendarFeed.id == feed_id,
        models.CalendarFeed.token_hash == hash_calendar_token(raw),
        models.CalendarFeed.revoked_at.is_(None),
    ).first()
    if not feed or not feed.user or not feed.user.is_active:
        raise unavailable
    if feed.board_id is not None:
        try:
            require_board_access(feed.board_id, feed.user, db, "viewer")
        except HTTPException:
            raise unavailable from None
    return feed


def calendar_feed_to_dict(feed: models.CalendarFeed, accessible_boards: dict) -> dict:
    return {
        "id": feed.id,
        "name": feed.name,
        "board_id": feed.board_id,
        "board_name": accessible_boards.get(feed.board_id),
        "available": feed.board_id is None or feed.board_id in accessible_boards,
        "assigned_only": feed.assigned_only,
        "stage_ids": None if feed.all_stages else sorted(stage.id for stage in feed.stages),
        "stages": [] if feed.all_stages else [
            {"id": stage.id, "name": stage.name, "board_id": stage.board_id,
             "board_name": accessible_boards[stage.board_id]}
            for stage in feed.stages
            if stage.board_id in accessible_boards and not stage.is_log
            and (feed.board_id is None or stage.board_id == feed.board_id)
        ],
        "last_four": feed.last_four,
        "created_at": feed.created_at.isoformat(),
    }


def get_calendar_stages(user: models.User, db: Session, board_id: int | None = None) -> list:
    """Return selectable stages without loading their objectives or log views."""
    board_ids = [board.id for board in get_accessible_boards(user, db)]
    if board_id is not None:
        board_ids = [item for item in board_ids if item == board_id]
    return db.query(models.Stage).join(models.Board).options(
        contains_eager(models.Stage.board)
    ).filter(
        models.Stage.board_id.in_(board_ids),
        or_(models.Stage.is_log.is_(False), models.Stage.is_log.is_(None)),
    ).order_by(
        models.Board.position, models.Board.id, models.Stage.row, models.Stage.position, models.Stage.id,
    ).all()


def validate_calendar_stages(
    stage_ids: list[int] | None, board_id: int | None, user: models.User, db: Session
) -> list:
    if stage_ids is None:
        return []
    choices = {stage.id: stage for stage in get_calendar_stages(user, db, board_id)}
    if not stage_ids or any(stage_id not in choices for stage_id in stage_ids):
        raise HTTPException(status_code=422, detail="Select stages from accessible hubs within this subscription's scope")
    return [choices[stage_id] for stage_id in sorted(set(stage_ids))]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def render_calendar(feed: models.CalendarFeed, db: Session, base_url: str) -> bytes:
    board_ids = [board.id for board in get_accessible_boards(feed.user, db)]
    if feed.board_id is not None:
        board_ids = [board_id for board_id in board_ids if board_id == feed.board_id]
    query = db.query(models.Task).join(models.Stage, models.Task.stage_id == models.Stage.id).options(
        contains_eager(models.Task.stage)
    ).filter(
        models.Stage.board_id.in_(board_ids),
        or_(models.Stage.is_log.is_(False), models.Stage.is_log.is_(None)),
        or_(models.Task.done.is_(False), models.Task.done.is_(None)),
        models.Task.due_date.is_not(None),
        models.Task.due_date != "",
    )
    if feed.assigned_only:
        query = query.filter(models.Task.assignee_user_id == feed.user_id)
    if not feed.all_stages:
        query = query.filter(models.Task.stage_id.in_([stage.id for stage in feed.stages]))

    calendar = Calendar()
    calendar.add("prodid", "-//Questline//Task deadlines//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", feed.name)
    for task in query.order_by(models.Task.calendar_uid).all():
        try:
            normalized = normalize_due_date(task.due_date)
            if not normalized:
                continue
            due = date.fromisoformat(normalized)
        except ValueError:
            # Do not log titles, descriptions, or the invalid value itself.
            log.warning("skipped_invalid_calendar_deadline task_id=%s", task.id)
            continue
        event = Event()
        event.add("uid", f"{task.calendar_uid}@questline")
        modified = _as_utc(task.updated_at or task.created_at or datetime(1970, 1, 1))
        event.add("dtstamp", modified)
        event.add("last-modified", modified)
        if task.created_at:
            event.add("created", _as_utc(task.created_at))
        event.add("dtstart", due)
        if due < date.max:
            event.add("dtend", due + timedelta(days=1))
        event.add("summary", task.title)
        if task.description:
            event.add("description", task.description)
        event.add("url", f"{base_url}/board/{task.stage.board_id}?task_id={task.id}")
        event.add("transp", "TRANSPARENT")
        calendar.add_component(event)
    return calendar.to_ical()


class _CalendarAccessLogFilter(logging.Filter):
    """Uvicorn logs the full request target, including subscription secrets."""

    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            target = record.args[2]
            if isinstance(target, str) and re.search(r"/calendar/[^/?]+\.ics(?:\?|$)", target):
                args = list(record.args)
                args[2] = target.split("?", 1)[0] + ("?[redacted]" if "?" in target else "")
                record.args = tuple(args)
        return True


def configure_calendar_access_logging() -> None:
    logger = logging.getLogger("uvicorn.access")
    name = "questline_calendar_secrets"
    if not any(item.name == name for item in logger.filters):
        logger.addFilter(_CalendarAccessLogFilter(name))
