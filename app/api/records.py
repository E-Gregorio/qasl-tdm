"""Endpoints de alta, consulta y enmascaramiento individual."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, tdm_service
from app.models.enums import DataStatus
from app.models.schemas import AuditEntry, DataRecord, DataRecordCreate
from app.services import audit_service

router = APIRouter(prefix="/tdm/records", tags=["Records"])


@router.post("", response_model=DataRecord, status_code=status.HTTP_201_CREATED)
def create_record(
    payload: DataRecordCreate,
    mask: bool = Query(default=True, description="Enmascara al crear"),
    db: Session = Depends(get_db),
) -> DataRecord:
    """CREATE. Da de alta un registro puntual en el pool."""
    if tdm_service.get(db, payload.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El registro '{payload.id}' ya existe",
        )

    datos = payload.model_dump()
    datos["estado_cuenta"] = payload.estado_cuenta.value
    registro = tdm_service.create(db, datos, mask=mask)
    return DataRecord.model_validate(registro)


@router.get("", response_model=list[DataRecord])
def list_records(
    scenario: str | None = None,
    record_status: DataStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[DataRecord]:
    """Consulta del pool por condicion de negocio."""
    registros = tdm_service.list(db, scenario, record_status, limit, offset)
    return [DataRecord.model_validate(r) for r in registros]


@router.get("/{data_id}", response_model=DataRecord)
def get_record(data_id: str, db: Session = Depends(get_db)) -> DataRecord:
    """EXTRACT. Recupera un registro por identificador."""
    registro = tdm_service.get(db, data_id)
    if registro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registro '{data_id}' no encontrado",
        )
    return DataRecord.model_validate(registro)


@router.get("/{data_id}/audit", response_model=list[AuditEntry])
def get_audit(
    data_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[AuditEntry]:
    """Bitacora del registro: quien lo toco, cuando y para que."""
    return [AuditEntry.model_validate(e) for e in audit_service.history(db, data_id, limit)]


@router.post("/{data_id}/mask", response_model=DataRecord)
def mask_record(data_id: str, db: Session = Depends(get_db)) -> DataRecord:
    """MASK. Idempotente: si ya estaba enmascarado, no hace nada."""
    registro = tdm_service.mask(db, data_id)
    if registro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registro '{data_id}' no encontrado",
        )
    return DataRecord.model_validate(registro)
