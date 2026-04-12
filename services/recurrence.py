"""Background worker and helpers for recurring task scheduling."""
from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal
import models
from services.automation import run_automations
from services.settings import (
    RECURRENCE_MIN_INTERVAL_SECONDS,
    get_instance_settings,
)
from services.tasks import _create_checklist_item_internal

log = logging.getLogger(__name__)

recurrence_worker_stop_event = threading.Event()


def _parse_iso_date(value: str, detail: str = "Invalid date") -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=detail)


def _advance_recurrence_date(current: date, frequency: str, interval: int) -> date:
    if frequency == "daily":
        return current + timedelta(days=interval)
    if frequency == "weekly":
        return current + timedelta(weeks=interval)
    if frequency == "monthly":
        month_index = current.month - 1 + interval
        year = current.year + month_index // 12
        month = month_index % 12 + 1
        month_lengths = [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ]
        day = min(current.day, month_lengths[month - 1])
        return date(year, month, day)
    raise HTTPException(status_code=400, detail="Invalid recurrence frequency")


def _resolve_recurrence_stage(
    source_task: models.Task,
    recurrence: models.TaskRecurrence,
    db: Session,
) -> Optional[models.Stage]:
    target_stage = db.query(models.Stage).filter(models.Stage.id == recurrence.spawn_stage_id).first()
    if not target_stage or target_stage.is_log or target_stage.board_id != source_task.stage.board_id:
        recurrence.enabled = False
        db.commit()
        log.warning(
            "disabled_recurrence task_id=%s recurrence_stage_id=%s",
            source_task.id,
            recurrence.spawn_stage_id,
        )
        return None
    return target_stage


def _clone_task_from_recurrence(
    source_task: models.Task,
    recurrence: models.TaskRecurrence,
    db: Session,
) -> Optional[models.Task]:
    target_stage = _resolve_recurrence_stage(source_task, recurrence, db)
    if target_stage is None:
        return None

    occurrence_date = _parse_iso_date(recurrence.next_run_on, "Invalid recurrence next run date")
    new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage.id).count()
    cloned_task = models.Task(
        title=source_task.title,
        description=source_task.description,
        due_date=occurrence_date.isoformat(),
        stage_id=target_stage.id,
        task_type_id=source_task.task_type_id,
        assignee_user_id=source_task.assignee_user_id,
        position=new_pos,
        color=source_task.color,
        show_description_on_card=source_task.show_description_on_card,
        show_checklist_on_card=source_task.show_checklist_on_card,
        done=False,
    )
    db.add(cloned_task)
    db.flush()

    for cfv in source_task.custom_field_values:
        db.add(
            models.CustomFieldValue(
                task_id=cloned_task.id,
                field_def_id=cfv.field_def_id,
                value=cfv.value,
            )
        )

    source_checklist_titles = [item.title for item in source_task.checklist_items]
    for title in source_checklist_titles:
        _create_checklist_item_internal(cloned_task, title, db)

    recurrence.next_run_on = _advance_recurrence_date(
        occurrence_date,
        recurrence.frequency,
        recurrence.interval,
    ).isoformat()
    db.commit()
    db.refresh(cloned_task)
    run_automations(cloned_task, "task_created", db)
    db.commit()
    return cloned_task


def _reuse_task_from_recurrence(
    source_task: models.Task,
    recurrence: models.TaskRecurrence,
    db: Session,
) -> Optional[models.Task]:
    target_stage = _resolve_recurrence_stage(source_task, recurrence, db)
    if target_stage is None:
        return None

    occurrence_date = _parse_iso_date(recurrence.next_run_on, "Invalid recurrence next run date")
    new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage.id).count()
    source_task.stage_id = target_stage.id
    source_task.position = new_pos
    source_task.done = False
    source_task.due_date = occurrence_date.isoformat()
    for checklist_item in source_task.checklist_items:
        checklist_item.done = False
    recurrence.next_run_on = _advance_recurrence_date(
        occurrence_date,
        recurrence.frequency,
        recurrence.interval,
    ).isoformat()
    db.commit()
    db.refresh(source_task)
    return source_task


def process_due_recurrences(db: Session, today: Optional[date] = None) -> int:
    today = today or date.today()
    due_recurrences = (
        db.query(models.TaskRecurrence)
        .join(models.Task, models.TaskRecurrence.task_id == models.Task.id)
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.TaskRecurrence.enabled == True,
            models.TaskRecurrence.next_run_on <= today.isoformat(),
        )
        .order_by(models.TaskRecurrence.next_run_on.asc(), models.TaskRecurrence.id.asc())
        .all()
    )
    created_count = 0
    for recurrence in due_recurrences:
        if not recurrence.task or not recurrence.task.stage:
            continue
        if recurrence.mode == "reuse_existing":
            processed_task = _reuse_task_from_recurrence(recurrence.task, recurrence, db)
        else:
            processed_task = _clone_task_from_recurrence(recurrence.task, recurrence, db)
        if processed_task is not None:
            created_count += 1
    return created_count


def recurrence_worker_loop() -> None:
    while not recurrence_worker_stop_event.is_set():
        db = SessionLocal()
        interval_seconds = RECURRENCE_MIN_INTERVAL_SECONDS
        try:
            interval_seconds = get_instance_settings(db)["recurrence_worker_interval_seconds"]
            process_due_recurrences(db)
        except Exception:
            log.exception("recurrence_worker_failed")
        finally:
            db.close()
        recurrence_worker_stop_event.wait(max(RECURRENCE_MIN_INTERVAL_SECONDS, interval_seconds))
