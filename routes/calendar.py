"""Authenticated subscription management and URL-authenticated calendar reads."""
from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, PositiveInt, field_validator
from sqlalchemy.orm import Session, selectinload

import models
from authz import _utcnow, get_accessible_boards, require_board_access, require_current_user
from routes._deps import get_db
from services.audit import _audit_log
from services.calendar import (
    authenticate_calendar_feed,
    calendar_feed_to_dict,
    generate_calendar_token,
    get_calendar_stages,
    public_base_url,
    render_calendar,
    subscription_url,
    validate_calendar_stages,
)

router = APIRouter(prefix="/api/calendar-feeds", tags=["calendar"])
feed_router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalendarFeedCreate(BaseModel):
    name: str = Field(default="Thunderbird", max_length=80)
    board_id: Optional[int] = Field(default=None, gt=0)
    assigned_only: bool = False
    stage_ids: Optional[list[PositiveInt]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("Feed name is required")
        return value.strip()


class CalendarFeedStagesUpdate(BaseModel):
    stage_ids: Optional[list[PositiveInt]] = Field(...)


def _board_names(user: models.User, db: Session) -> dict:
    return {board.id: board.name for board in get_accessible_boards(user, db)}


def _owned_feed(feed_id: str, user: models.User, db: Session) -> models.CalendarFeed:
    feed = db.query(models.CalendarFeed).filter(
        models.CalendarFeed.id == feed_id,
        models.CalendarFeed.user_id == user.id,
        models.CalendarFeed.revoked_at.is_(None),
    ).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Calendar feed not found")
    return feed


@router.get("")
def list_calendar_feeds(request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    response.headers["Cache-Control"] = "no-store"
    names = _board_names(user, db)
    feeds = db.query(models.CalendarFeed).filter(
        models.CalendarFeed.user_id == user.id,
        models.CalendarFeed.revoked_at.is_(None),
    ).options(selectinload(models.CalendarFeed.stages)).order_by(models.CalendarFeed.created_at.desc()).all()
    return [calendar_feed_to_dict(feed, names) for feed in feeds]


@router.get("/stages")
def list_calendar_stages(request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    response.headers["Cache-Control"] = "no-store"
    return [
        {"id": stage.id, "name": stage.name, "board_id": stage.board_id, "board_name": stage.board.name}
        for stage in get_calendar_stages(user, db)
    ]


@router.post("", status_code=201)
def create_calendar_feed(
    data: CalendarFeedCreate, request: Request, response: Response, db: Session = Depends(get_db)
):
    user = require_current_user(request, db)
    if data.board_id is not None:
        if not db.get(models.Board, data.board_id):
            raise HTTPException(status_code=404, detail="Board not found")
        require_board_access(data.board_id, user, db, "viewer")
    stages = validate_calendar_stages(data.stage_ids, data.board_id, user, db)
    # Validate configuration before persisting a credential.
    public_base_url(request)
    raw, digest, last_four = generate_calendar_token()
    feed = models.CalendarFeed(
        user_id=user.id, board_id=data.board_id, name=data.name,
        assigned_only=data.assigned_only, token_hash=digest, last_four=last_four,
        all_stages=data.stage_ids is None, stages=stages,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    _audit_log("calendar_feed_created", request=request, actor_user_id=user.id,
               board_id=feed.board_id, details={"feed_id": feed.id})
    response.headers["Cache-Control"] = "no-store"
    return {
        **calendar_feed_to_dict(feed, _board_names(user, db)),
        "subscription_url": subscription_url(feed, raw, request),
    }


@router.patch("/{feed_id}")
def update_calendar_feed_stages(
    feed_id: str, data: CalendarFeedStagesUpdate, request: Request, response: Response,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    feed = _owned_feed(feed_id, user, db)
    if feed.board_id is not None:
        require_board_access(feed.board_id, user, db, "viewer")
    feed.stages = validate_calendar_stages(data.stage_ids, feed.board_id, user, db)
    feed.all_stages = data.stage_ids is None
    db.commit()
    _audit_log("calendar_feed_updated", request=request, actor_user_id=user.id,
               board_id=feed.board_id, details={"feed_id": feed.id})
    response.headers["Cache-Control"] = "no-store"
    return calendar_feed_to_dict(feed, _board_names(user, db))


@router.post("/{feed_id}/rotate")
def rotate_calendar_feed(feed_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    feed = _owned_feed(feed_id, user, db)
    if feed.board_id is not None:
        require_board_access(feed.board_id, user, db, "viewer")
    public_base_url(request)
    raw, feed.token_hash, feed.last_four = generate_calendar_token()
    db.commit()
    _audit_log("calendar_feed_rotated", request=request, actor_user_id=user.id,
               board_id=feed.board_id, details={"feed_id": feed.id})
    response.headers["Cache-Control"] = "no-store"
    return {
        **calendar_feed_to_dict(feed, _board_names(user, db)),
        "subscription_url": subscription_url(feed, raw, request),
    }


@router.delete("/{feed_id}")
def revoke_calendar_feed(feed_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    feed = _owned_feed(feed_id, user, db)
    feed.revoked_at = _utcnow()
    db.commit()
    _audit_log("calendar_feed_revoked", request=request, actor_user_id=user.id,
               board_id=feed.board_id, details={"feed_id": feed.id})
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@feed_router.api_route("/{feed_id}.ics", methods=["GET", "HEAD"], response_class=Response)
def get_calendar_feed(feed_id: str, request: Request, db: Session = Depends(get_db)):
    # Feed credentials never enter general session/bearer authentication.
    feed = authenticate_calendar_feed(feed_id, request.query_params.get("token"), db)
    content = render_calendar(feed, db, public_base_url(request))
    etag = f'"{hashlib.sha256(content).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(candidate.strip().removeprefix("W/") in {etag, "*"} for candidate in candidates):
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(len(content))
    return Response(
        content=b"" if request.method == "HEAD" else content,
        media_type="text/calendar", headers=headers,
    )
