"""Notification routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import models
from authz import require_current_user
from routes._deps import get_db
from services.notifications import generate_due_notifications_for_user, notification_to_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def get_notifications(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    generate_due_notifications_for_user(user, db)
    notifications = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .limit(20)
        .all()
    )
    unread_count = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.read_at.is_(None),
        )
        .count()
    )
    return {
        "items": [notification_to_dict(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    notification = (
        db.query(models.Notification)
        .filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == user.id,
        )
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.read_at.is_(None),
    ).update({"read_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return {"ok": True}
