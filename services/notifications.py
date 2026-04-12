"""Notification creation, due-date alert generation, and serialisers."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

import models


def notification_to_dict(notification: models.Notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body or "",
        "link_url": notification.link_url,
        "board_id": notification.board_id,
        "task_id": notification.task_id,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


def recurrence_to_dict(recurrence: Optional[models.TaskRecurrence]) -> Optional[dict]:
    if not recurrence:
        return None
    return {
        "enabled": recurrence.enabled,
        "mode": recurrence.mode,
        "frequency": recurrence.frequency,
        "interval": recurrence.interval,
        "next_run_on": recurrence.next_run_on,
        "spawn_stage_id": recurrence.spawn_stage_id,
    }


def create_notification(
    user_id: int,
    notification_type: str,
    title: str,
    body: Optional[str],
    db: Session,
    *,
    link_url: Optional[str] = None,
    board_id: Optional[int] = None,
    task_id: Optional[int] = None,
    dedupe_key: Optional[str] = None,
):
    if dedupe_key:
        existing = (
            db.query(models.Notification)
            .filter(models.Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing:
            return existing
    notification = models.Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body or "",
        link_url=link_url,
        board_id=board_id,
        task_id=task_id,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    db.flush()
    return notification


def generate_due_notifications_for_user(user: models.User, db: Session):
    today = date.today().isoformat()
    query = (
        db.query(models.Task)
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.Task.assignee_user_id == user.id,
            models.Task.done == False,
            models.Task.due_date.is_not(None),
            models.Task.due_date != "",
        )
    )
    if user.role != "admin":
        query = query.join(
            models.BoardMembership,
            models.BoardMembership.board_id == models.Stage.board_id,
        ).filter(models.BoardMembership.user_id == user.id)
    tasks = query.all()
    created = False
    for task in tasks:
        if not task.stage or not task.stage.board:
            continue
        notification_type = None
        if task.due_date == today:
            notification_type = "task_due_today"
        elif task.due_date < today:
            notification_type = "task_overdue"
        if not notification_type:
            continue
        dedupe_key = f"{notification_type}:task:{task.id}:user:{user.id}:date:{today}"
        title = "Task due today" if notification_type == "task_due_today" else "Task overdue"
        body = task.title
        create_notification(
            user.id,
            notification_type,
            title,
            body,
            db,
            link_url=f"/board/{task.stage.board_id}?task_id={task.id}",
            board_id=task.stage.board_id,
            task_id=task.id,
            dedupe_key=dedupe_key,
        )
        created = True
    if created:
        db.commit()
