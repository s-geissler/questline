"""Business logic for task and checklist operations."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

import models
from services.task_history import (
    checklist_history_snapshot, record_checklist_changes,
    record_task_changes, record_task_event, task_history_snapshot,
)


def backfill_task_assignees(engine) -> None:
    """Copy legacy assignments without changing task IDs or timestamps."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT OR IGNORE INTO task_assignees (task_id, user_id)
            SELECT tasks.id, tasks.assignee_user_id FROM tasks
            JOIN users ON users.id = tasks.assignee_user_id
            WHERE tasks.assignee_user_id IS NOT NULL
        """))


def task_assignees(task: models.Task) -> list[models.User]:
    # Also read the legacy column for older callers that create tasks directly.
    users = {user.id: user for user in task.assignees}
    if task.assignee_user_id is not None and task.assignee:
        users[task.assignee.id] = task.assignee
    return [users[user_id] for user_id in sorted(users)]


def set_task_assignees(task: models.Task, users: list[models.User]) -> None:
    users = sorted({user.id: user for user in users}.values(), key=lambda user: user.id)
    if {user.id for user in task_assignees(task)} != {user.id for user in users}:
        task.updated_at = datetime.now(UTC).replace(tzinfo=None)
    task.assignees = users
    # Keep the singular API/column usable by existing integrations.
    task.assignee = users[0] if users else None
    task.assignee_user_id = users[0].id if users else None


def task_assignment_to_dict(task: models.Task) -> dict:
    assignees = [
        {"id": user.id, "display_name": user.display_name, "email": user.email}
        for user in task_assignees(task)
    ]
    return {
        "assignees": assignees,
        "assignee_user_ids": [user["id"] for user in assignees],
        "assignee": assignees[0] if assignees else None,
        "assignee_user_id": assignees[0]["id"] if assignees else None,
    }


def task_assigned_to(user_id: int):
    return or_(
        and_(models.Task.assignee_user_id.is_not(None), models.Task.assignee_user_id == user_id),
        models.Task.assignees.any(models.User.id == user_id),
    )


def task_has_assignees():
    return or_(models.Task.assignee_user_id.is_not(None), models.Task.assignees.any())


def normalize_due_date(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Due date must be a valid date in YYYY-MM-DD format") from None
    if parsed.isoformat() != value:
        raise ValueError("Due date must be a valid date in YYYY-MM-DD format")
    return value


def normalize_due_time(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Due time must be a valid time in HH:MM format")
    return value


def normalize_due_timezone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Due timezone must be a valid IANA timezone, such as Europe/Berlin") from None
    return value


def deadline_datetime(due_date: str | None, due_time: str | None, due_timezone: str | None) -> datetime | None:
    """Resolve a timed deadline to UTC; date-only deadlines have no instant.

    Like iCalendar, use the first occurrence of an ambiguous local time and the
    pre-transition offset for a missing time (moving it forward across the gap).
    Keep the local time and zone so recurrence retains wall time across DST.
    """
    due_time = normalize_due_time(due_time)
    if due_time is None:
        return None
    due_date = normalize_due_date(due_date)
    due_timezone = normalize_due_timezone(due_timezone)
    if due_date is None:
        raise ValueError("A due time requires a due date")
    if due_timezone is None:
        raise ValueError("A due time requires a timezone")
    local = datetime.combine(date.fromisoformat(due_date), time.fromisoformat(due_time), ZoneInfo(due_timezone))
    try:
        return local.astimezone(UTC)
    except OverflowError:
        raise ValueError("Timed deadline is outside the supported date range") from None


def task_deadline_to_dict(task: models.Task) -> dict:
    try:
        due_at = deadline_datetime(task.due_date, task.due_time, task.due_timezone)
    except ValueError:
        due_at = None  # Keep malformed legacy rows readable.
    return {
        "due_date": task.due_date,
        "due_time": task.due_time,
        "due_timezone": task.due_timezone,
        "due_at": due_at.isoformat().replace("+00:00", "Z") if due_at else None,
    }


def collect_descendant_task_ids(root_task_ids: list[int], db: Session) -> set[int]:
    all_ids = set(root_task_ids)
    frontier = set(root_task_ids)

    while frontier:
        child_ids = {
            task_id
            for (task_id,) in db.query(models.ChecklistItem.spawned_task_id)
            .filter(
                models.ChecklistItem.task_id.in_(frontier),
                models.ChecklistItem.spawned_task_id.is_not(None),
            )
            .all()
        }
        child_ids -= all_ids
        if not child_ids:
            break
        all_ids.update(child_ids)
        frontier = child_ids

    return all_ids


def _create_checklist_item_internal(task: models.Task, title: str, db: Session, actor=None) -> models.ChecklistItem:
    item = models.ChecklistItem(task_id=task.id, title=title)
    db.add(item)
    record_task_event(task, "checklist_item_added", db, actor, subject=title)
    db.flush()

    if task.task_type and task.task_type.is_epic:
        target_stage_id = task.task_type.spawn_stage_id or task.stage_id
        target_stage = db.query(models.Stage).filter(models.Stage.id == target_stage_id).first()
        if target_stage and target_stage.is_log:
            raise HTTPException(status_code=400, detail="Cannot spawn tasks into a log stage")
        new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage_id).count()
        spawned = models.Task(
            title=title,
            stage_id=target_stage_id,
            position=new_pos,
            color=task.task_type.color,
            parent_task_id=task.id,
        )
        db.add(spawned)
        record_task_event(spawned, "task_created", db, actor)
        db.flush()
        item.spawned_task_id = spawned.id
    return item


def _sync_spawned_task_title_from_checklist_item(item: models.ChecklistItem, db: Session, actor=None):
    if not item.spawned_task_id:
        return
    spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
    if spawned:
        previous = task_history_snapshot(spawned)
        spawned.title = item.title
        record_task_changes(spawned, previous, db, actor)


def _sync_checklist_item_title_from_spawned_task(task: models.Task, db: Session, actor=None):
    linked_item = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id == task.id)
        .first()
    )
    if linked_item:
        previous = checklist_history_snapshot(linked_item)
        linked_item.title = task.title
        record_checklist_changes(linked_item, previous, db, actor)


def delete_tasks_by_ids(task_ids: set[int], db: Session, actor=None):
    if not task_ids:
        return 0

    linked_items = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id.in_(task_ids))
        .all()
    )
    for item in linked_items:
        if item.task_id not in task_ids:
            record_task_event(item.task, "checklist_item_removed", db, actor, subject=item.title)
        db.delete(item)

    tasks = db.query(models.Task).filter(models.Task.id.in_(task_ids)).all()
    for task in tasks:
        db.delete(task)
    db.commit()
    return len(tasks)
