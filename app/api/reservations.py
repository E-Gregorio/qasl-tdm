"""Endpoints de RESERVE, RELEASE y RESET."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, reservation_service
from app.models.schemas import DataRecord, ReleaseRequest, ReserveRequest
from app.services.reservation_service import (
    NotReservedError,
    PoolExhaustedError,
)

router = APIRouter(prefix="/tdm", tags=["Reservations"])


@router.post("/reserve", response_model=DataRecord)
def reserve(payload: ReserveRequest, db: Session = Depends(get_db)) -> DataRecord:
    """RESERVE. Entrega un registro del escenario y lo saca de circulacion.

    La operacion es atomica: dos workers que piden el mismo escenario al
    mismo tiempo reciben registros distintos.
    """
    try:
        registro = reservation_service.reserve(
            db, payload.scenario, payload.reserved_by, payload.ttl_seconds
        )
    except PoolExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return DataRecord.model_validate(registro)


@router.post("/release", response_model=DataRecord)
def release(payload: ReleaseRequest, db: Session = Depends(get_db)) -> DataRecord:
    """RELEASE. Devuelve el registro al pool (CLEAN) o lo marca sucio (DIRTY)."""
    try:
        registro = reservation_service.release(
            db, payload.data_id, payload.reserved_by, payload.outcome
        )
    except NotReservedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return DataRecord.model_validate(registro)


@router.post("/reset/{data_id}", response_model=DataRecord)
def reset(data_id: str, db: Session = Depends(get_db)) -> DataRecord:
    """RESET. Restaura la condicion de negocio y devuelve el registro al pool."""
    try:
        registro = reservation_service.reset(db, data_id)
    except NotReservedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return DataRecord.model_validate(registro)


@router.post("/expire")
def expire(db: Session = Depends(get_db)) -> dict:
    """Fuerza la expiracion de reservas vencidas. Lo llama un job periodico."""
    return {"expired": reservation_service.expire_stale(db)}
