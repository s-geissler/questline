"""Task type and custom field routes."""
from __future__ import annotations

import json
from typing import List as PyList, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    _authorize_board_request,
    _board_id_for_task_type,
    _require_task_type_in_board,
    require_board_access,
)
from routes._deps import get_db

router = APIRouter(prefix="/api/task-types", tags=["task_types"])

MAX_NAME_LENGTH = 120
MAX_OPTION_COUNT = 100


class TaskTypeCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    is_epic: bool = False
    board_id: int
    color: Optional[str] = Field(default=None, max_length=7)
    show_description_on_card: bool = False
    show_checklist_on_card: bool = False


class TaskTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    is_epic: Optional[bool] = None
    spawn_stage_id: Optional[int] = None
    color: Optional[str] = Field(default=None, max_length=7)
    show_description_on_card: Optional[bool] = None
    show_checklist_on_card: Optional[bool] = None


class CustomFieldCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    field_type: str = "text"
    show_on_card: bool = False
    options: Optional[PyList[Union[str, dict]]] = None
    color: Optional[str] = Field(default=None, max_length=7)


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


def task_type_to_dict(tt: models.TaskType) -> dict:
    return {
        "id": tt.id,
        "name": tt.name,
        "color": tt.color,
        "is_epic": tt.is_epic,
        "show_description_on_card": tt.show_description_on_card,
        "show_checklist_on_card": tt.show_checklist_on_card,
        "spawn_stage_id": tt.spawn_stage_id,
        "custom_fields": [field_to_dict(f) for f in tt.custom_fields],
    }


@router.get("")
def get_task_types(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    types = db.query(models.TaskType).filter(models.TaskType.board_id == board_id).all()
    return [task_type_to_dict(tt) for tt in types]


@router.post("")
def create_task_type(data: TaskTypeCreate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, data.board_id, "editor")
    tt = models.TaskType(
        name=data.name,
        is_epic=data.is_epic,
        board_id=data.board_id,
        color=_validated_optional_hex_color(data.color, "Task type color must be a valid hex color"),
        show_description_on_card=data.show_description_on_card,
        show_checklist_on_card=data.show_checklist_on_card,
    )
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return task_type_to_dict(tt)


@router.put("/{type_id}")
def update_task_type(type_id: int, data: TaskTypeUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    else:
        current_user = None
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    if data.name is not None:
        tt.name = data.name
    if data.is_epic is not None:
        tt.is_epic = data.is_epic
    if "spawn_stage_id" in data.model_fields_set:
        if data.spawn_stage_id is not None:
            target_stage = db.query(models.Stage).filter(models.Stage.id == data.spawn_stage_id).first()
            if not target_stage:
                raise HTTPException(status_code=404, detail="Stage not found")
            if target_stage.is_log:
                raise HTTPException(status_code=400, detail="Cannot spawn tasks into a log stage")
            if request is not None and current_user is not None:
                require_board_access(target_stage.board_id, current_user, db, "editor")
        tt.spawn_stage_id = data.spawn_stage_id
    if "color" in data.model_fields_set:
        tt.color = _validated_optional_hex_color(data.color, "Task type color must be a valid hex color")
    if "show_description_on_card" in data.model_fields_set:
        tt.show_description_on_card = data.show_description_on_card
    if "show_checklist_on_card" in data.model_fields_set:
        tt.show_checklist_on_card = data.show_checklist_on_card
    db.commit()
    db.refresh(tt)
    return task_type_to_dict(tt)


@router.delete("/{type_id}")
def delete_task_type(type_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    db.delete(tt)
    db.commit()
    return {"ok": True}


@router.post("/{type_id}/fields")
def add_custom_field(type_id: int, data: CustomFieldCreate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    field = models.CustomFieldDef(
        task_type_id=type_id,
        name=data.name,
        field_type=data.field_type,
        show_on_card=data.show_on_card,
        options=json.dumps(normalize_field_options(data.options)) if data.options else None,
        color=_validated_optional_hex_color(data.color, "Custom field color must be a valid hex color"),
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field_to_dict(field)


@router.put("/{type_id}/fields/{field_id}")
def update_custom_field(
    type_id: int,
    field_id: int,
    data: CustomFieldCreate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    field = (
        db.query(models.CustomFieldDef)
        .filter(
            models.CustomFieldDef.id == field_id,
            models.CustomFieldDef.task_type_id == type_id,
        )
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    field.show_on_card = data.show_on_card
    if "options" in data.model_fields_set:
        field.options = json.dumps(normalize_field_options(data.options)) if data.options else None
    if "color" in data.model_fields_set:
        field.color = _validated_optional_hex_color(data.color, "Custom field color must be a valid hex color")
    db.commit()
    return field_to_dict(field)


@router.delete("/{type_id}/fields/{field_id}")
def delete_custom_field(type_id: int, field_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    field = (
        db.query(models.CustomFieldDef)
        .filter(
            models.CustomFieldDef.id == field_id,
            models.CustomFieldDef.task_type_id == type_id,
        )
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    db.delete(field)
    db.commit()
    return {"ok": True}
