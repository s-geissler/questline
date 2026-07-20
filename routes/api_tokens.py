"""API token routes (self-service).

Any authenticated user — human or otherwise — can mint, list, and revoke
their own bearer tokens via these endpoints. The raw token value is
returned exactly once at creation time. Subsequent listings show only
the `qgl_` prefix and the last four characters.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    API_TOKEN_PREFIX,
    _utcnow,
    api_token_to_dict,
    generate_api_token,
    require_current_user,
)
from routes._deps import get_db
from services.audit import _audit_log

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

MAX_TOKEN_NAME_LENGTH = 80


class TokenCreate(BaseModel):
    name: str = Field(max_length=MAX_TOKEN_NAME_LENGTH)


def _list_active_tokens_for_user(db: Session, user_id: int):
    return (
        db.query(models.ApiToken)
        .filter(
            models.ApiToken.user_id == user_id,
            models.ApiToken.revoked_at.is_(None),
        )
        .order_by(models.ApiToken.created_at.desc())
        .all()
    )


@router.post("")
def create_token(
    data: TokenCreate, request: Request, db: Session = Depends(get_db)
):
    user = require_current_user(request, db)
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Token name is required")
    raw, digest, last_four = generate_api_token()
    token = models.ApiToken(
        user_id=user.id,
        name=name,
        token_hash=digest,
        last_four=last_four,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    _audit_log(
        "api_token_created",
        request=request,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"token_id": token.id, "name": name, "prefix": API_TOKEN_PREFIX},
    )
    return {
        **api_token_to_dict(token),
        "raw_token": raw,
    }


@router.get("")
def list_tokens(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    return [api_token_to_dict(t) for t in _list_active_tokens_for_user(db, user.id)]


@router.delete("/{token_id}")
def revoke_token(token_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    token = (
        db.query(models.ApiToken)
        .filter(
            models.ApiToken.id == token_id,
            models.ApiToken.user_id == user.id,
        )
        .first()
    )
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.revoked_at is not None:
        raise HTTPException(status_code=400, detail="Token already revoked")
    token.revoked_at = _utcnow()
    db.commit()
    _audit_log(
        "api_token_revoked",
        request=request,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"token_id": token.id, "name": token.name},
    )
    return {"ok": True}
