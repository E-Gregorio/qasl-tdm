"""RESERVE / RELEASE / RESET / EXPIRE: el corazon de QASL-TDM.

Este modulo es la razon de ser del proyecto. Generar datos lo hace cualquiera;
lo que rompe una suite de automatizacion es que dos ejecuciones tomen el mismo
registro al mismo tiempo.

Sobre la atomicidad de RESERVE
------------------------------
En PostgreSQL se usa ``SELECT ... FOR UPDATE SKIP LOCKED``: cada worker toma
una fila distinta sin esperar a los demas. Es la forma correcta y la que
usaria un entorno real.

SQLite no tiene ``SKIP LOCKED``, asi que se usa un ``UPDATE`` condicional con
reintentos: se marca la fila solo si sigue en AVAILABLE y se verifica el
``rowcount``. Si otro worker gano la carrera, el rowcount es 0 y se reintenta
con el siguiente candidato. Es correcto en ambos motores, solo que en SQLite
escala peor porque la escritura bloquea toda la base.

Sobre el vencimiento
--------------------
Una reserva vencida NO vuelve a AVAILABLE: pasa a DIRTY. Si un test murio a
mitad de camino, no sabemos que le hizo al dato. Devolverlo al pool sin
revisarlo es como se contaminan los ambientes de QA.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import DEFAULT_TTL_SECONDS, RESERVE_MAX_RETRIES
from app.database import IS_POSTGRES
from app.models.db import PoolRecord, utcnow
from app.models.enums import AuditAction, DataStatus, ReleaseOutcome
from app.services import audit_service
from app.services.generator_service import GeneratorService


class ReservationError(Exception):
    """Error de negocio en el ciclo de reserva."""


class PoolExhaustedError(ReservationError):
    """No hay registros disponibles para el escenario pedido."""


class NotReservedError(ReservationError):
    """El registro no esta reservado por quien intenta liberarlo."""


def _aware(value: datetime | None) -> datetime | None:
    """SQLite devuelve datetimes sin zona; los normaliza a UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ReservationService:
    def __init__(self, generator: GeneratorService | None = None) -> None:
        self._generator = generator or GeneratorService()

    # -- RESERVE ----------------------------------------------------------
    def reserve(
        self,
        db: Session,
        scenario: str,
        reserved_by: str,
        ttl_seconds: int | None = None,
    ) -> PoolRecord:
        """Toma un registro disponible del escenario y lo marca como reservado."""
        ttl = ttl_seconds or DEFAULT_TTL_SECONDS
        now = utcnow()
        expires_at = now + timedelta(seconds=ttl)

        # Antes de repartir, se limpian las reservas vencidas. Sin esto, un
        # pool chico se agota con reservas fantasma de tests que murieron.
        self.expire_stale(db, commit=False)

        record = (
            self._reserve_postgres(db, scenario, reserved_by, now, expires_at)
            if IS_POSTGRES
            else self._reserve_generic(db, scenario, reserved_by, now, expires_at)
        )

        if record is None:
            db.rollback()
            raise PoolExhaustedError(
                f"No hay registros AVAILABLE para el escenario '{scenario}'. "
                f"Ejecuta un seed o un refresh del pool."
            )

        audit_service.record(
            db,
            record.id,
            AuditAction.RESERVE,
            actor=reserved_by,
            detail=f"ttl={ttl}s expira={expires_at.isoformat()}",
        )
        db.commit()
        db.refresh(record)
        return record

    def _reserve_postgres(
        self,
        db: Session,
        scenario: str,
        reserved_by: str,
        now: datetime,
        expires_at: datetime,
    ) -> PoolRecord | None:
        stmt = (
            select(PoolRecord)
            .where(
                PoolRecord.scenario == scenario,
                PoolRecord.status == DataStatus.AVAILABLE.value,
            )
            .order_by(PoolRecord.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        record = db.execute(stmt).scalar_one_or_none()
        if record is None:
            return None

        record.status = DataStatus.RESERVED.value
        record.reserved_by = reserved_by
        record.reserved_at = now
        record.expires_at = expires_at
        record.updated_at = now
        return record

    def _reserve_generic(
        self,
        db: Session,
        scenario: str,
        reserved_by: str,
        now: datetime,
        expires_at: datetime,
    ) -> PoolRecord | None:
        for _ in range(RESERVE_MAX_RETRIES):
            candidate_id = db.execute(
                select(PoolRecord.id)
                .where(
                    PoolRecord.scenario == scenario,
                    PoolRecord.status == DataStatus.AVAILABLE.value,
                )
                .order_by(PoolRecord.id)
                .limit(1)
            ).scalar_one_or_none()

            if candidate_id is None:
                return None

            # La condicion sobre status dentro del UPDATE es lo que hace
            # atomica la operacion: si otro worker ya la tomo, rowcount es 0.
            result = db.execute(
                update(PoolRecord)
                .where(
                    PoolRecord.id == candidate_id,
                    PoolRecord.status == DataStatus.AVAILABLE.value,
                )
                .values(
                    status=DataStatus.RESERVED.value,
                    reserved_by=reserved_by,
                    reserved_at=now,
                    expires_at=expires_at,
                    updated_at=now,
                )
            )

            if result.rowcount == 1:
                return db.get(PoolRecord, candidate_id)

            db.rollback()

        return None

    # -- RELEASE ----------------------------------------------------------
    def release(
        self,
        db: Session,
        data_id: str,
        reserved_by: str,
        outcome: ReleaseOutcome = ReleaseOutcome.CLEAN,
    ) -> PoolRecord:
        """Libera un registro reservado.

        CLEAN lo devuelve al pool. DIRTY lo deja fuera de circulacion hasta
        que se le haga RESET, porque el test lo modifico.
        """
        record = db.get(PoolRecord, data_id)
        if record is None:
            raise NotReservedError(f"El registro '{data_id}' no existe")

        if record.status != DataStatus.RESERVED.value:
            raise NotReservedError(
                f"El registro '{data_id}' no esta reservado (status={record.status})"
            )

        if record.reserved_by != reserved_by:
            raise NotReservedError(
                f"El registro '{data_id}' esta reservado por '{record.reserved_by}', "
                f"no por '{reserved_by}'"
            )

        record.status = (
            DataStatus.AVAILABLE.value
            if outcome is ReleaseOutcome.CLEAN
            else DataStatus.DIRTY.value
        )
        record.reserved_by = None
        record.reserved_at = None
        record.expires_at = None
        record.updated_at = utcnow()

        audit_service.record(
            db, record.id, AuditAction.RELEASE, actor=reserved_by, detail=outcome.value
        )
        db.commit()
        db.refresh(record)
        return record

    # -- RESET ------------------------------------------------------------
    def reset(self, db: Session, data_id: str, actor: str = "system") -> PoolRecord:
        """Restaura la condicion de negocio del registro y lo devuelve al pool.

        La identidad del cliente no cambia: si cambiara, un test que guardo
        el CBU para verificar despues dejaria de encontrarlo.
        """
        record = db.get(PoolRecord, data_id)
        if record is None:
            raise NotReservedError(f"El registro '{data_id}' no existe")

        valores = self._generator.volatile_values(record.scenario)
        for campo, valor in valores.items():
            setattr(record, campo, valor)

        record.status = DataStatus.AVAILABLE.value
        record.reserved_by = None
        record.reserved_at = None
        record.expires_at = None
        record.updated_at = utcnow()

        audit_service.record(db, record.id, AuditAction.RESET, actor=actor)
        db.commit()
        db.refresh(record)
        return record

    def reset_dirty(self, db: Session, actor: str = "system") -> int:
        """Aplica RESET a todos los registros DIRTY. Devuelve cuantos toco."""
        ids = list(
            db.execute(
                select(PoolRecord.id).where(PoolRecord.status == DataStatus.DIRTY.value)
            ).scalars()
        )
        for data_id in ids:
            self.reset(db, data_id, actor=actor)
        return len(ids)

    # -- EXPIRE -----------------------------------------------------------
    def expire_stale(self, db: Session, commit: bool = True) -> int:
        """Pasa a DIRTY las reservas vencidas. Devuelve cuantas expiro."""
        now = utcnow()

        vencidos = list(
            db.execute(
                select(PoolRecord.id).where(
                    PoolRecord.status == DataStatus.RESERVED.value,
                    PoolRecord.expires_at.is_not(None),
                    PoolRecord.expires_at < now,
                )
            ).scalars()
        )

        if not vencidos:
            return 0

        db.execute(
            update(PoolRecord)
            .where(PoolRecord.id.in_(vencidos))
            .values(
                status=DataStatus.DIRTY.value,
                reserved_by=None,
                reserved_at=None,
                expires_at=None,
                updated_at=now,
            )
        )

        for data_id in vencidos:
            audit_service.record(
                db,
                data_id,
                AuditAction.EXPIRE,
                detail="reserva vencida, marcado DIRTY",
            )

        if commit:
            db.commit()

        return len(vencidos)
