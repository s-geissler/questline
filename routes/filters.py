"""Saved filter routes."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import _authorize_board_request, _board_id_for_saved_filter
from filters_logic import _validated_filter_definition, saved_filter_to_dict
from routes._deps import get_db

router = APIRouter(prefix="/api/filters", tags=["filters"])

MAX_NAME_LENGTH = 120
MAX_FILTER_JSON_LENGTH = 20000


class SavedFilterCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    board_id: int
    definition: dict


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    definition: Optional[dict] = None


def _validate_filter_definition_size(definition: Optional[dict]):
    if definition is None:
        return
    if len(json.dumps(definition, separators=(",", ":"))) > MAX_FILTER_JSON_LENGTH:
        raise HTTPException(status_code=400, detail="Filter definition is too large")


@router.get("")
def get_saved_filters(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    filters = (
        db.query(models.SavedFilter)
        .filter(models.SavedFilter.board_id == board_id)
        .order_by(models.SavedFilter.name)
        .all()
    )
    return [saved_filter_to_dict(saved_filter) for saved_filter in filters]


@router.post("")
def create_saved_filter(data: SavedFilterCreate, db: Session = Depends(get_db), request: Request = None):
    current_user = _authorize_board_request(request, db, data.board_id, "editor")
    _validate_filter_definition_size(data.definition)
    definition = _validated_filter_definition(data.definition, data.board_id, db, current_user)
    saved_filter = models.SavedFilter(
        name=data.name,
        board_id=data.board_id,
        definition=json.dumps(definition),
    )
    db.add(saved_filter)
    db.commit()
    db.refresh(saved_filter)
    return saved_filter_to_dict(saved_filter)


@router.put("/{filter_id}")
def update_saved_filter(filter_id: int, data: SavedFilterUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_saved_filter(filter_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    else:
        current_user = None
    saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == filter_id).first()
    if not saved_filter:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    if data.name is not None:
        saved_filter.name = data.name
    if "definition" in data.model_fields_set:
        _validate_filter_definition_size(data.definition)
        saved_filter.definition = json.dumps(
            _validated_filter_definition(data.definition, saved_filter.board_id, db, current_user)
        )
    db.commit()
    db.refresh(saved_filter)
    return saved_filter_to_dict(saved_filter)


@router.delete("/{filter_id}")
def delete_saved_filter(filter_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_saved_filter(filter_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == filter_id).first()
    if not saved_filter:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    db.query(models.Stage).filter(models.Stage.filter_id == filter_id).update({"filter_id": None})
    db.delete(saved_filter)
    db.commit()
    return {"ok": True}
