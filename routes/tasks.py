"""Task, recurrence, and checklist routes."""
from __future__ import annotations

import json
from typing import List as PyList, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    _authorize_board_request,
    _board_id_for_stage,
    _board_id_for_task,
    _require_task_in_board,
    _require_task_type_in_board,
    require_board_access,
)
from routes._deps import get_db
from services.automation import run_automations
from services.notifications import create_notification, recurrence_to_dict
from services.recurrence import _advance_recurrence_date, _parse_iso_date
from services.tasks import (
    _create_checklist_item_internal,
    _sync_checklist_item_title_from_spawned_task,
    _sync_spawned_task_title_from_checklist_item,
    collect_descendant_task_ids,
    delete_tasks_by_ids,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_NAME_LENGTH = 120
MAX_TASK_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10000
MAX_OPTION_COUNT = 100
RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly"}
RECURRENCE_MODES = {"create_new", "reuse_existing"}


class TaskCreate(BaseModel):
    title: str = Field(max_length=MAX_TASK_TITLE_LENGTH)
    stage_id: int
    task_type_id: Optional[int] = None
    due_date: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=MAX_TASK_TITLE_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    due_date: Optional[str] = None
    task_type_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    color: Optional[str] = Field(default=None, max_length=7)
    show_description_on_card: Optional[bool] = None
    show_checklist_on_card: Optional[bool] = None
    done: Optional[bool] = None
    custom_fields: Optional[dict] = None


class TaskRecurrenceUpdate(BaseModel):
    enabled: bool = True
    mode: str = "create_new"
    frequency: str
    interval: int = 1
    next_run_on: str
    spawn_stage_id: int


class TaskMove(BaseModel):
    stage_id: int
    position: int


class ReorderTasks(BaseModel):
    stage_id: int
    ids: PyList[int]


class ChecklistItemCreate(BaseModel):
    title: str = Field(max_length=MAX_TASK_TITLE_LENGTH)


class ChecklistItemUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=MAX_TASK_TITLE_LENGTH)
    done: Optional[bool] = None


def _validated_optional_hex_color(value: Optional[str], detail: str) -> Optional[str]:
    color = (value or "").strip()
    if not color:
        return None
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise HTTPException(status_code=400, detail=detail)
    if any(ch not in "0123456789abcdefABCDEF" for ch in color[1:]):
        raise HTTPException(status_code=400, detail=detail)
    return color


def normalize_field_options(options) -> list[dict]:
    if len(options or []) > MAX_OPTION_COUNT:
        raise HTTPException(status_code=400, detail="Too many custom field options")
    normalized = []
    for option in options or []:
        if isinstance(option, str):
            label = option.strip()[:MAX_NAME_LENGTH]
            if label:
                normalized.append({"label": label, "color": None})
            continue
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()[:MAX_NAME_LENGTH]
            if label:
                normalized.append(
                    {
                        "label": label,
                        "color": _validated_optional_hex_color(
                            option.get("color"),
                            "Custom field option color must be a valid hex color",
                        ),
                    }
                )
    return normalized


def field_to_dict(f: models.CustomFieldDef) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "field_type": f.field_type,
        "color": f.color,
        "show_on_card": f.show_on_card,
        "options": normalize_field_options(json.loads(f.options) if f.options else []),
    }


def task_to_dict(task: models.Task) -> dict:
    custom_values = {str(cfv.field_def_id): cfv.value for cfv in task.custom_field_values}
    checklist = [
        {
            "id": item.id,
            "title": item.title,
            "done": item.done,
            "spawned_task_id": item.spawned_task_id,
        }
        for item in task.checklist_items
    ]
    task_type = None
    if task.task_type:
        task_type = {
            "id": task.task_type.id,
            "name": task.task_type.name,
            "color": task.task_type.color,
            "is_epic": task.task_type.is_epic,
            "show_description_on_card": task.task_type.show_description_on_card,
            "show_checklist_on_card": task.task_type.show_checklist_on_card,
            "custom_fields": [field_to_dict(f) for f in task.task_type.custom_fields],
        }
    display_color = task.color or (task.task_type.color if task.task_type else None)
    effective_show_description_on_card = (
        task.show_description_on_card
        if task.show_description_on_card is not None
        else (task.task_type.show_description_on_card if task.task_type else False)
    )
    effective_show_checklist_on_card = (
        task.show_checklist_on_card
        if task.show_checklist_on_card is not None
        else (task.task_type.show_checklist_on_card if task.task_type else False)
    )
    parent_task = None
    if task.parent_task:
        parent_task = {
            "id": task.parent_task.id,
            "title": task.parent_task.title,
            "board_id": task.parent_task.stage.board_id if task.parent_task.stage else None,
        }
    assignee = None
    if task.assignee:
        assignee = {
            "id": task.assignee.id,
            "display_name": task.assignee.display_name,
            "email": task.assignee.email,
        }
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "due_date": task.due_date,
        "board_id": task.stage.board_id if task.stage else None,
        "board_name": task.stage.board.name if task.stage and task.stage.board else None,
        "stage_name": task.stage.name if task.stage else None,
        "parent_task": parent_task,
        "assignee": assignee,
        "assignee_user_id": task.assignee_user_id,
        "show_description_on_card": task.show_description_on_card,
        "effective_show_description_on_card": effective_show_description_on_card,
        "show_checklist_on_card": task.show_checklist_on_card,
        "effective_show_checklist_on_card": effective_show_checklist_on_card,
        "stage_id": task.stage_id,
        "task_type": task_type,
        "task_type_id": task.task_type_id,
        "color": display_color,
        "position": task.position,
        "done": task.done,
        "custom_field_values": custom_values,
        "checklist": checklist,
        "recurrence": recurrence_to_dict(task.recurrence),
    }


def _validate_custom_fields_for_task(
    custom_fields: dict,
    effective_task_type_id: Optional[int],
    board_id: int,
    db: Session,
):
    if not custom_fields:
        return
    if effective_task_type_id is None:
        raise HTTPException(status_code=400, detail="Custom fields require a task type")
    for field_def_id_str in custom_fields.keys():
        field_def_id = int(field_def_id_str)
        field_def = db.query(models.CustomFieldDef).filter(models.CustomFieldDef.id == field_def_id).first()
        if not field_def:
            raise HTTPException(status_code=404, detail="Custom field not found")
        if field_def.task_type_id != effective_task_type_id:
            raise HTTPException(status_code=400, detail="Custom field does not belong to the selected task type")
        if not field_def.task_type or field_def.task_type.board_id != board_id:
            raise HTTPException(status_code=400, detail="Custom field belongs to a different board")


def _validate_assignee_for_task(board_id: int, assignee_user_id: Optional[int], db: Session):
    if assignee_user_id is None:
        return None
    assignee = db.query(models.User).filter(models.User.id == assignee_user_id).first()
    if not assignee or not assignee.is_active:
        raise HTTPException(status_code=400, detail="Assignee must be an active user")
    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == assignee_user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=400, detail="Assignee must be a board member")
    return assignee


def _validate_task_recurrence_input(task: models.Task, data: TaskRecurrenceUpdate, db: Session) -> models.Stage:
    if data.mode not in RECURRENCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid recurrence mode")
    if data.frequency not in RECURRENCE_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid recurrence frequency")
    if data.interval < 1:
        raise HTTPException(status_code=400, detail="Recurrence interval must be at least 1")
    _parse_iso_date(data.next_run_on, "Recurrence next run date must be YYYY-MM-DD")
    spawn_stage = db.query(models.Stage).filter(models.Stage.id == data.spawn_stage_id).first()
    if not spawn_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if spawn_stage.board_id != task.stage.board_id:
        raise HTTPException(status_code=400, detail="Recurrence stage belongs to a different board")
    if spawn_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot recur into a log stage")
    return spawn_stage


@router.post("")
def create_task(data: TaskCreate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(data.stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot add tasks to a log stage")
    if data.task_type_id is not None:
        _require_task_type_in_board(data.task_type_id, stage.board_id, db)
    pos = db.query(models.Task).filter(models.Task.stage_id == data.stage_id).count()
    task = models.Task(
        title=data.title,
        stage_id=data.stage_id,
        task_type_id=data.task_type_id,
        due_date=data.due_date,
        position=pos,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    run_automations(task, "task_created", db)
    db.commit()
    db.refresh(task)
    return task_to_dict(task)


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "viewer")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_dict(task)


@router.put("/reorder")
def reorder_tasks(data: ReorderTasks, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(data.stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    target_stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not target_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if target_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot move tasks into a log stage")
    moved_tasks = []
    for i, task_id in enumerate(data.ids):
        task = _require_task_in_board(task_id, target_stage.board_id, db)
        previous_stage_id = task.stage_id
        task.stage_id = data.stage_id
        task.position = i
        if previous_stage_id != data.stage_id:
            moved_tasks.append(task)
    db.commit()
    for task in moved_tasks:
        run_automations(task, "task_moved_to_stage", db)
    if moved_tasks:
        db.commit()
    return {"ok": True}


@router.put("/{task_id}")
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), request: Request = None):
    current_user = None
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if "task_type_id" in data.model_fields_set and data.task_type_id is not None:
        _require_task_type_in_board(data.task_type_id, task.stage.board_id, db)
    if "assignee_user_id" in data.model_fields_set:
        _validate_assignee_for_task(task.stage.board_id, data.assignee_user_id, db)
    effective_task_type_id = data.task_type_id if "task_type_id" in data.model_fields_set else task.task_type_id
    _validate_custom_fields_for_task(data.custom_fields, effective_task_type_id, task.stage.board_id, db)
    prev_done = task.done
    prev_assignee_user_id = task.assignee_user_id
    if data.title is not None:
        task.title = data.title
        _sync_checklist_item_title_from_spawned_task(task, db)
    if data.description is not None:
        task.description = data.description
    if "due_date" in data.model_fields_set:
        task.due_date = data.due_date or None
    if "task_type_id" in data.model_fields_set:
        task.task_type_id = data.task_type_id
    if "assignee_user_id" in data.model_fields_set:
        task.assignee_user_id = data.assignee_user_id
    if "color" in data.model_fields_set:
        task.color = _validated_optional_hex_color(data.color, "Task color must be a valid hex color")
    if "show_description_on_card" in data.model_fields_set:
        task.show_description_on_card = data.show_description_on_card
    if "show_checklist_on_card" in data.model_fields_set:
        task.show_checklist_on_card = data.show_checklist_on_card
    if data.done is not None:
        task.done = data.done
    if data.custom_fields:
        for field_def_id_str, value in data.custom_fields.items():
            field_def_id = int(field_def_id_str)
            existing = (
                db.query(models.CustomFieldValue)
                .filter(
                    models.CustomFieldValue.task_id == task_id,
                    models.CustomFieldValue.field_def_id == field_def_id,
                )
                .first()
            )
            if existing:
                existing.value = value
            else:
                db.add(models.CustomFieldValue(task_id=task_id, field_def_id=field_def_id, value=value))
    db.commit()
    if data.done is not None:
        ref_item = (
            db.query(models.ChecklistItem)
            .filter(models.ChecklistItem.spawned_task_id == task_id)
            .first()
        )
        if ref_item:
            ref_item.done = data.done
        for checklist_item in task.checklist_items:
            checklist_item.done = data.done
        spawned_children = (
            db.query(models.Task)
            .join(models.ChecklistItem, models.ChecklistItem.spawned_task_id == models.Task.id)
            .filter(models.ChecklistItem.task_id == task_id)
            .all()
        )
        children_newly_done = []
        for child in spawned_children:
            was_done = child.done
            child.done = data.done
            if data.done and not was_done:
                children_newly_done.append(child)
        db.commit()
        for child in children_newly_done:
            run_automations(child, "task_done", db)
        if children_newly_done:
            db.commit()
    if data.done is True and not prev_done:
        run_automations(task, "task_done", db)
        db.commit()
    if (
        "assignee_user_id" in data.model_fields_set
        and task.assignee_user_id
        and task.assignee_user_id != prev_assignee_user_id
        and current_user
        and current_user.id != task.assignee_user_id
        and task.stage
    ):
        create_notification(
            task.assignee_user_id,
            "task_assigned",
            "Assigned to an objective",
            f"{current_user.display_name} assigned you to {task.title}",
            db,
            link_url=f"/board/{task.stage.board_id}?task_id={task.id}",
            board_id=task.stage.board_id,
            task_id=task.id,
        )
        db.commit()
    db.refresh(task)
    return task_to_dict(task)


@router.put("/{task_id}/move")
def move_task(task_id: int, data: TaskMove, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    target_stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not target_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if not task.stage or task.stage.board_id != target_stage.board_id:
        raise HTTPException(status_code=400, detail="Cannot move tasks across boards")
    if target_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot move tasks into a log stage")
    previous_stage_id = task.stage_id
    task.stage_id = data.stage_id
    task.position = data.position
    db.commit()
    if previous_stage_id != data.stage_id:
        run_automations(task, "task_moved_to_stage", db)
        db.commit()
    db.refresh(task)
    return task_to_dict(task)


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    delete_tasks_by_ids(collect_descendant_task_ids([task_id], db), db)
    return {"ok": True}


@router.put("/{task_id}/recurrence")
def upsert_task_recurrence(task_id: int, data: TaskRecurrenceUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.stage:
        raise HTTPException(status_code=400, detail="Task has no stage")
    _validate_task_recurrence_input(task, data, db)
    recurrence = task.recurrence
    if recurrence is None:
        recurrence = models.TaskRecurrence(task_id=task.id)
        db.add(recurrence)
    recurrence.enabled = data.enabled
    recurrence.mode = data.mode
    recurrence.frequency = data.frequency
    recurrence.interval = data.interval
    recurrence.next_run_on = data.next_run_on
    recurrence.spawn_stage_id = data.spawn_stage_id
    db.commit()
    db.refresh(task)
    return recurrence_to_dict(task.recurrence)


@router.delete("/{task_id}/recurrence")
def delete_task_recurrence(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    recurrence = db.query(models.TaskRecurrence).filter(models.TaskRecurrence.task_id == task_id).first()
    if not recurrence:
        raise HTTPException(status_code=404, detail="Task recurrence not found")
    db.delete(recurrence)
    db.commit()
    return {"ok": True}


@router.post("/{task_id}/checklist")
def add_checklist_item(task_id: int, data: ChecklistItemCreate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    item = _create_checklist_item_internal(task, data.title, db)
    db.commit()
    if item.spawned_task_id:
        spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
        if spawned:
            run_automations(spawned, "task_created", db)
            db.commit()
    db.refresh(item)
    return {"id": item.id, "title": item.title, "done": item.done, "spawned_task_id": item.spawned_task_id}


@router.put("/{task_id}/checklist/{item_id}")
def update_checklist_item(
    task_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    item = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.id == item_id, models.ChecklistItem.task_id == task_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    was_complete = bool(item.task.checklist_items) and all(ci.done for ci in item.task.checklist_items)
    if data.title is not None:
        item.title = data.title
        _sync_spawned_task_title_from_checklist_item(item, db)
    if data.done is not None:
        item.done = data.done
        if item.spawned_task_id:
            spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
            if spawned:
                prev_done = spawned.done
                spawned.done = data.done
                db.commit()
                if data.done and not prev_done:
                    run_automations(spawned, "task_done", db)
    is_complete = bool(item.task.checklist_items) and all(ci.done for ci in item.task.checklist_items)
    if is_complete and not was_complete:
        run_automations(item.task, "checklist_completed", db)
    db.commit()
    return {"id": item.id, "title": item.title, "done": item.done, "spawned_task_id": item.spawned_task_id}


@router.delete("/{task_id}/checklist/{item_id}")
def delete_checklist_item(task_id: int, item_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    item = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.id == item_id, models.ChecklistItem.task_id == task_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    spawned_task_id = item.spawned_task_id
    db.delete(item)
    db.commit()
    if spawned_task_id is not None:
        delete_tasks_by_ids(collect_descendant_task_ids([spawned_task_id], db), db)
    return {"ok": True}
