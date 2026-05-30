"""
Persistent notification store.

Every time the daemon fires a desktop notification it also POSTs here
so the in-app notification center has a complete history.

  POST   /api/notifications/          — create a notification
  GET    /api/notifications/          — list (newest first, filterable)
  GET    /api/notifications/unread-count — count of unread notifications
  POST   /api/notifications/{id}/read — mark one as read
  POST   /api/notifications/read-all  — mark all as read
  DELETE /api/notifications/{id}      — delete one
  DELETE /api/notifications/          — clear all read
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from ..database import Base, get_db

router = APIRouter()


# ── model ─────────────────────────────────────────────────────────────────────
# Also add this class to backend/papis/models.py alongside Package, Project etc.
# so Alembic detects it during --autogenerate.

class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(Integer,  primary_key=True, index=True)
    title      = Column(String,   nullable=False)
    body       = Column(Text,     nullable=True)
    kind       = Column(String,   default="info")   # info | warning | error | success
    package    = Column(String,   nullable=True)     # related package name
    source     = Column(String,   nullable=True)     # related package source
    is_read    = Column(Boolean,  default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ── schemas ───────────────────────────────────────────────────────────────────

class NotificationIn(BaseModel):
    title  : str
    body   : Optional[str] = None
    kind   : str           = "info"
    package: Optional[str] = None
    source : Optional[str] = None


class NotificationOut(BaseModel):
    id        : int
    title     : str
    body      : Optional[str]
    kind      : str
    package   : Optional[str]
    source    : Optional[str]
    is_read   : bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=NotificationOut, status_code=201)
def create_notification(body: NotificationIn, db: Session = Depends(get_db)):
    n = Notification(**body.model_dump())
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


@router.get("/", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.is_read == False).count()
    return {"count": count}


@router.post("/{notif_id}/read", status_code=204)
def mark_read(notif_id: int, db: Session = Depends(get_db)):
    n = db.query(Notification).get(notif_id)
    if not n:
        raise HTTPException(404)
    n.is_read = True
    db.commit()


@router.post("/read-all", status_code=204)
def mark_all_read(db: Session = Depends(get_db)):
    db.query(Notification).filter(
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()


@router.delete("/{notif_id}", status_code=204)
def delete_notification(notif_id: int, db: Session = Depends(get_db)):
    n = db.query(Notification).get(notif_id)
    if not n:
        raise HTTPException(404)
    db.delete(n)
    db.commit()


@router.delete("/", status_code=204)
def clear_read(db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.is_read == True).delete()
    db.commit()