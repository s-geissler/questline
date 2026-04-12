"""Automation routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    _authorize_board_request,
    _board_id_for_automation,
    _require_stage_in_board,
    _require_task_type_in_board,
)
from routes._deps import get_db

router = APIRouter(prefix="/api/automations", tags=["automations"])

MAX_NAME_LENGTH = 120


class AutomationCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    trigger_type: str
    trigger_stage_id: Optional[int] = None
    action_type: str
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = Field(default=None, max_length=7)
    action_days_offset: Optional[int] = None
    board_id: int


class AutomationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    enabled: Optional[bool] = None
    trigger_stage_id: Optional[int] = None
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = Field(default=None, max_length=7)
    action_days_offset: Optional[int] = None


def _validated_optional_hex_color(value: Optional[str], detail: str) -> Optional[str]:
    color = (value or "").strip()
    if not color:
        return None
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise HTTPException(status_code=400, detail=detail)
    if any(ch not in "0123456789abcdefABCDEF" for ch in color[1:]):
        raise HTTPException(status_code=400, detail=detail)
    return color


def automation_to_dict(a: models.Automation) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "trigger_type": a.trigger_type,
        "trigger_stage_id": a.trigger_stage_id,
        "action_type": a.action_type,
        "action_stage_id": a.action_stage_id,
        "action_task_type_id": a.action_task_type_id,
        "action_color": a.action_color,
        "action_days_offset": a.action_days_offset,
        "enabled": a.enabled,
    }


@router.get("")
def get_automations(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    autos = db.query(models.Automation).filter(models.Automation.board_id == board_id).all()
    return [automation_to_dict(a) for a in autos]


@router.post("")
def create_automation(data: AutomationCreate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, data.board_id, "editor")
    if data.trigger_stage_id is not None:
        _require_stage_in_board(data.trigger_stage_id, data.board_id, db)
    if data.action_stage_id is not None:
        _require_stage_in_board(data.action_stage_id, data.board_id, db)
    if data.action_task_type_id is not None:
        _require_task_type_in_board(data.action_task_type_id, data.board_id, db)
    auto = models.Automation(
        name=data.name,
        trigger_type=data.trigger_type,
        trigger_stage_id=data.trigger_stage_id or None,
        action_type=data.action_type,
        action_stage_id=data.action_stage_id or None,
        action_task_type_id=data.action_task_type_id or None,
        action_color=_validated_optional_hex_color(data.action_color, "Automation color must be a valid hex color"),
        action_days_offset=data.action_days_offset,
        board_id=data.board_id,
    )
    db.add(auto)
    db.commit()
    db.refresh(auto)
    return automation_to_dict(auto)


@router.put("/{auto_id}")
def update_automation(auto_id: int, data: AutomationUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_automation(auto_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    auto = db.query(models.Automation).filter(models.Automation.id == auto_id).first()
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    if data.name is not None:
        auto.name = data.name
    if data.enabled is not None:
        auto.enabled = data.enabled
    if "trigger_stage_id" in data.model_fields_set:
        if data.trigger_stage_id is not None:
            _require_stage_in_board(data.trigger_stage_id, auto.board_id, db)
        auto.trigger_stage_id = data.trigger_stage_id or None
    if "action_stage_id" in data.model_fields_set:
        if data.action_stage_id is not None:
            _require_stage_in_board(data.action_stage_id, auto.board_id, db)
        auto.action_stage_id = data.action_stage_id or None
    if "action_task_type_id" in data.model_fields_set:
        if data.action_task_type_id is not None:
            _require_task_type_in_board(data.action_task_type_id, auto.board_id, db)
        auto.action_task_type_id = data.action_task_type_id or None
    if "action_color" in data.model_fields_set:
        auto.action_color = _validated_optional_hex_color(data.action_color, "Automation color must be a valid hex color")
    if "action_days_offset" in data.model_fields_set:
        auto.action_days_offset = data.action_days_offset
    db.commit()
    db.refresh(auto)
    return automation_to_dict(auto)


@router.delete("/{auto_id}")
def delete_automation(auto_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_automation(auto_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    auto = db.query(models.Automation).filter(models.Automation.id == auto_id).first()
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    db.delete(auto)
    db.commit()
    return {"ok": True}
