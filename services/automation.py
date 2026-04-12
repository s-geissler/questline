"""Automation rule engine - evaluates triggers and applies actions."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

import models


def apply_automation(task: models.Task, automation: models.Automation, db: Session):
    if automation.action_type == "move_to_stage" and automation.action_stage_id:
        target_stage = db.query(models.Stage).filter(models.Stage.id == automation.action_stage_id).first()
        if target_stage and target_stage.is_log:
            return
        new_pos = db.query(models.Task).filter(models.Task.stage_id == automation.action_stage_id).count()
        task.stage_id = automation.action_stage_id
        task.position = new_pos
    elif automation.action_type == "set_done":
        task.done = True
    elif automation.action_type == "set_task_type":
        task.task_type_id = automation.action_task_type_id
    elif automation.action_type == "set_color":
        task.color = automation.action_color or None
    elif automation.action_type == "set_due_in_days" and automation.action_days_offset is not None:
        task.due_date = (date.today() + timedelta(days=automation.action_days_offset)).isoformat()


def run_automations(task: models.Task, event_type: str, db: Session):
    board_id = task.stage.board_id if task.stage else None
    query = db.query(models.Automation).filter(
        models.Automation.enabled == True,
        models.Automation.trigger_type == event_type,
    )
    if board_id is not None:
        query = query.filter(models.Automation.board_id == board_id)
    for automation in query.all():
        if automation.trigger_stage_id and task.stage_id != automation.trigger_stage_id:
            continue
        apply_automation(task, automation, db)
