"""Bitacora del ciclo de vida del dato."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import AuditLog
from app.models.enums import AuditAction


def record(
    db: Session,
    data_id: str,
    action: AuditAction,
    actor: str = "system",
    detail: str | None = None,
    flush: bool = False,
) -> None:
    """Agrega una entrada a la bitacora. No hace commit: lo hace el llamador."""
    db.add(
        AuditLog(
            data_id=data_id,
            action=action.value,
            actor=actor,
            detail=detail,
        )
    )
    if flush:
        db.flush()


def history(db: Session, data_id: str, limit: int = 100) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.data_id == data_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())
