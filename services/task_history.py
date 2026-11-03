"""Task activity records, written in the same transaction as each change."""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


EVENT_MESSAGES = {
    "task_created": "Task created",
    "title_updated": "Title updated",
    "description_updated": "Description updated",
    "stage_changed": "Stage changed",
    "task_completed": "Task completed",
    "task_reopened": "Task reopened",
    "assignees_updated": "Assignees updated",
    "deadline_updated": "Deadline updated",
    "deadline_removed": "Deadline removed",
    "checklist_item_added": "Checklist item added",
    "checklist_item_renamed": "Checklist item renamed",
    "checklist_item_completed": "Checklist item completed",
    "checklist_item_reopened": "Checklist item reopened",
    "checklist_item_removed": "Checklist item removed",
}


def record_task_event(
    task: models.Task, event_type: str, db: Session, actor: models.User | None = None,
    *, subject: str | None = None,
) -> models.TaskHistoryEvent:
    event = models.TaskHistoryEvent(
        task=task,
        event_type=event_type,
        actor_user_id=actor.id if actor else None,
        actor_name=actor.display_name if actor else "Automation",
        subject=subject,
    )
    db.add(event)
    return event


def task_history_snapshot(task: models.Task) -> dict:
    assignee_ids = {user.id for user in task.assignees}
    if task.assignee_user_id is not None:
        assignee_ids.add(task.assignee_user_id)
    return {
        "title": task.title,
        "description": task.description or "",
        "stage": task.stage_id,
        "done": bool(task.done),
        "assignees": assignee_ids,
        "deadline": (task.due_date or None, task.due_time or None, task.due_timezone or None),
    }


def record_task_changes(task: models.Task, previous: dict, db: Session, actor: models.User | None = None) -> None:
    current = task_history_snapshot(task)
    for field, event_type in (
        ("title", "title_updated"),
        ("description", "description_updated"),
        ("stage", "stage_changed"),
        ("assignees", "assignees_updated"),
    ):
        if current[field] != previous[field]:
            record_task_event(task, event_type, db, actor)
    if current["done"] != previous["done"]:
        record_task_event(task, "task_completed" if current["done"] else "task_reopened", db, actor)
    if current["deadline"] != previous["deadline"]:
        record_task_event(task, "deadline_updated" if task.due_date else "deadline_removed", db, actor)


def checklist_history_snapshot(item: models.ChecklistItem) -> tuple[str, bool]:
    return item.title, bool(item.done)


def record_checklist_changes(
    item: models.ChecklistItem, previous: tuple[str, bool], db: Session, actor: models.User | None = None,
) -> None:
    title, done = previous
    if item.title != title:
        record_task_event(item.task, "checklist_item_renamed", db, actor, subject=item.title)
    if bool(item.done) != done:
        event_type = "checklist_item_completed" if item.done else "checklist_item_reopened"
        record_task_event(item.task, event_type, db, actor, subject=item.title)


def history_event_to_dict(event: models.TaskHistoryEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "message": EVENT_MESSAGES[event.event_type],
        "actor_user_id": event.actor_user_id,
        "actor_name": event.actor_name,
        "subject": event.subject,
        "created_at": event.created_at.isoformat(timespec="microseconds") + "Z",
    }
