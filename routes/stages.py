"""Stage routes."""
from __future__ import annotations

import json
from typing import List as PyList, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from authz import _authorize_board_request, _board_id_for_stage, _require_stage_in_board
from filters_logic import get_stage_tasks, stage_to_dict
from routes._deps import get_db
from services.notifications import recurrence_to_dict
from services.tasks import collect_descendant_task_ids, delete_tasks_by_ids

router = APIRouter(prefix="/api/stages", tags=["stages"])

MAX_NAME_LENGTH = 120


class StageCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    board_id: int
    row: int = 0
    position: Optional[int] = None


class StageUpdate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)


class StageConfigUpdate(BaseModel):
    is_log: Optional[bool] = None
    filter_id: Optional[int] = None


class ReorderStages(BaseModel):
    ids: Optional[PyList[int]] = None
    stages: Optional[PyList[dict]] = None


def _validate_stage_grid(board_id: int, placements: PyList[dict], db: Session):
    top_row_positions = {
        int(placement["position"])
        for placement in placements
        if int(placement["row"]) == 0
    }
    for placement in placements:
        row = int(placement["row"])
        position = int(placement["position"])
        if row == 1 and position not in top_row_positions:
            raise HTTPException(status_code=400, detail="Second row stages require a top row stage above them")


def normalize_field_options(options) -> list[dict]:
    normalized = []
    for option in options or []:
        if isinstance(option, dict):
            value = str(option.get("value", "")).strip()
            color = str(option.get("color", "")).strip() or None
        else:
            value = str(option).strip()
            color = None
        if not value:
            continue
        normalized.append({"value": value, "color": color})
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


def _task_to_dict(task: models.Task) -> dict:
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


@router.get("")
def get_stages(board_id: int, request: Request = None, db: Session = Depends(get_db)):
    current_user = _authorize_board_request(request, db, board_id, "viewer")
    stages = (
        db.query(models.Stage)
        .filter(models.Stage.board_id == board_id)
        .order_by(models.Stage.row, models.Stage.position)
        .all()
    )
    result = []
    for stage in stages:
        tasks = get_stage_tasks(stage, db, current_user)
        result.append({**stage_to_dict(stage), "tasks": [_task_to_dict(t) for t in tasks]})
    return result


@router.post("")
def create_stage(request: Request = None, data: StageCreate = None, db: Session = Depends(get_db)):
    _authorize_board_request(request, db, data.board_id, "editor")
    row = max(0, data.row)
    row_query = db.query(models.Stage).filter(models.Stage.board_id == data.board_id, models.Stage.row == row)
    if data.position is None:
        max_position = row_query.with_entities(func.max(models.Stage.position)).scalar()
        pos = 0 if max_position is None else max_position + 1
    else:
        pos = max(0, data.position)
    existing_placements = [
        {"id": stage.id, "row": stage.row or 0, "position": stage.position}
        for stage in db.query(models.Stage).filter(models.Stage.board_id == data.board_id).all()
    ]
    planned_placements = []
    for placement in sorted(existing_placements, key=lambda item: (item["row"], item["position"], item["id"])):
        same_row = placement["row"] == row
        next_position = placement["position"]
        if same_row and next_position >= pos:
            next_position += 1
        planned_placements.append({**placement, "position": next_position})
    planned_placements.append({"id": -1, "row": row, "position": pos})
    _validate_stage_grid(data.board_id, planned_placements, db)
    if data.position is not None:
        row_query.filter(models.Stage.position >= pos).update(
            {"position": models.Stage.position + 1},
            synchronize_session=False,
        )
    stage = models.Stage(name=data.name, board_id=data.board_id, row=row, position=pos)
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return {**stage_to_dict(stage), "tasks": []}


@router.put("/reorder")
def reorder_stages(request: Request = None, data: ReorderStages = None, db: Session = Depends(get_db)):
    placements = []
    if data.stages:
        for index, stage_data in enumerate(data.stages):
            stage_id = stage_data.get("id")
            if not isinstance(stage_id, int):
                raise HTTPException(status_code=400, detail="Invalid stage reorder payload")
            placements.append(
                {
                    "id": stage_id,
                    "row": max(0, int(stage_data.get("row", 0))),
                    "position": max(0, int(stage_data.get("position", index))),
                }
            )
    elif data.ids:
        placements = [{"id": stage_id, "row": 0, "position": i} for i, stage_id in enumerate(data.ids)]

    if placements:
        board_id = _board_id_for_stage(placements[0]["id"], db)
        if board_id is not None:
            _authorize_board_request(request, db, board_id, "editor")
            for placement in placements:
                _require_stage_in_board(placement["id"], board_id, db)
            _validate_stage_grid(board_id, placements, db)
    for placement in placements:
        db.query(models.Stage).filter(models.Stage.id == placement["id"]).update(
            {"row": placement["row"], "position": placement["position"]}
        )
    db.commit()
    return {"ok": True}


@router.put("/{stage_id}")
def update_stage(stage_id: int, request: Request = None, data: StageUpdate = None, db: Session = Depends(get_db)):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    stage.name = data.name
    db.commit()
    return {"id": stage.id, "name": stage.name}


@router.put("/{stage_id}/config")
def update_stage_config(
    stage_id: int,
    request: Request = None,
    data: StageConfigUpdate = None,
    db: Session = Depends(get_db),
):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if "is_log" in data.model_fields_set:
        if data.is_log and not stage.is_log and stage.tasks:
            raise HTTPException(status_code=400, detail="Cannot convert a non-empty stage into a log")
        stage.is_log = bool(data.is_log)
    if "filter_id" in data.model_fields_set:
        if data.filter_id is not None:
            saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == data.filter_id).first()
            if not saved_filter or saved_filter.board_id != stage.board_id:
                raise HTTPException(status_code=400, detail="Invalid saved filter")
        stage.filter_id = data.filter_id
    if not stage.is_log:
        stage.filter_id = None
    db.commit()
    db.refresh(stage)
    return stage_to_dict(stage)


@router.delete("/{stage_id}")
def delete_stage(stage_id: int, request: Request = None, db: Session = Depends(get_db)):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    task_ids = [t.id for t in stage.tasks]
    if task_ids:
        delete_tasks_by_ids(collect_descendant_task_ids(task_ids, db), db)
        db.refresh(stage)
    db.delete(stage)
    db.commit()
    return {"ok": True}


@router.post("/{stage_id}/clear-completed")
def clear_completed_stage_tasks(stage_id: int, request: Request = None, db: Session = Depends(get_db)):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot clear tasks from a log stage")
    completed_task_ids = [
        task.id
        for task in db.query(models.Task)
        .filter(models.Task.stage_id == stage_id, models.Task.done == True)
        .all()
    ]
    task_ids_to_delete = collect_descendant_task_ids(completed_task_ids, db)
    deleted_count = delete_tasks_by_ids(task_ids_to_delete, db)
    return {"ok": True, "deleted": deleted_count}
