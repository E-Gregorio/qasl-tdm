"""Alta y consulta individual de registros."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import PoolRecord, utcnow
from app.models.enums import AuditAction, DataStatus
from app.services import audit_service
from app.services.masking_service import MaskingService


class TDMService:
    def __init__(self, masking: MaskingService | None = None) -> None:
        self._masking = masking or MaskingService()

    def create(self, db: Session, datos: dict, mask: bool = True, actor: str = "system") -> PoolRecord:
        if mask:
            datos = {**datos, **self._masking.mask_fields(datos)}

        registro = PoolRecord(**datos)
        registro.status = DataStatus.AVAILABLE.value
        registro.is_masked = mask

        db.add(registro)
        audit_service.record(db, registro.id, AuditAction.CREATE, actor=actor)
        db.commit()
        db.refresh(registro)
        return registro

    def get(self, db: Session, data_id: str) -> PoolRecord | None:
        return db.get(PoolRecord, data_id)

    def list(
        self,
        db: Session,
        scenario: str | None = None,
        status: DataStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PoolRecord]:
        stmt = select(PoolRecord)
        if scenario:
            stmt = stmt.where(PoolRecord.scenario == scenario)
        if status:
            stmt = stmt.where(PoolRecord.status == status.value)

        stmt = stmt.order_by(PoolRecord.id).limit(limit).offset(offset)
        return list(db.execute(stmt).scalars())

    def mask(self, db: Session, data_id: str, actor: str = "system") -> PoolRecord | None:
        """Enmascara un registro existente. Es idempotente."""
        registro = db.get(PoolRecord, data_id)
        if registro is None:
            return None

        if registro.is_masked:
            # Ya esta enmascarado: no se vuelve a enmascarar. Ese era el bug
            # de la version anterior, que producia ****6789 -> ********6789.
            return registro

        campos = self._masking.mask_fields(
            {
                "dni": registro.dni,
                "cuit": registro.cuit,
                "nombre": registro.nombre,
                "cuenta": registro.cuenta,
                "tarjeta": registro.tarjeta,
            }
        )
        for campo, valor in campos.items():
            setattr(registro, campo, valor)

        registro.is_masked = True
        registro.updated_at = utcnow()

        audit_service.record(db, registro.id, AuditAction.MASK, actor=actor)
        db.commit()
        db.refresh(registro)
        return registro

    def mask_all(self, db: Session, actor: str = "system") -> int:
        """Enmascara todo lo que este sin enmascarar. Devuelve cuantos toco."""
        pendientes = list(
            db.execute(
                select(PoolRecord.id).where(PoolRecord.is_masked.is_(False))
            ).scalars()
        )
        for data_id in pendientes:
            self.mask(db, data_id, actor=actor)
        return len(pendientes)
