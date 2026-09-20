"""Pool de datos: SEED, LOAD, REFRESH, STATS y export para JMeter.

Esta es la mitad batch del ciclo. Corre por lotes, en un job, y nadie la
espera. La mitad de runtime (reserve/release) esta en reservation_service y
tiene un orden de magnitud distinto de latencia: por eso viven separadas.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import POOL_MIN_AVAILABLE
from app.models.db import PoolRecord, utcnow
from app.models.enums import AuditAction, DataStatus
from app.models.schemas import PoolStats, RefreshResult, ScenarioStats
from app.services import audit_service
from app.services.generator_service import SCENARIOS, GeneratorService, get_spec
from app.services.masking_service import MaskingService
from app.services.reservation_service import ReservationService

#: Columnas del CSV que consume JMeter con CSV Data Set Config.
CSV_COLUMNS = [
    "id", "scenario", "dni", "cuit", "nombre", "email",
    "cuenta", "tarjeta", "saldo", "moneda", "estado_cuenta", "dias_mora",
]


class PoolService:
    def __init__(
        self,
        generator: GeneratorService | None = None,
        masking: MaskingService | None = None,
        reservations: ReservationService | None = None,
    ) -> None:
        self._generator = generator or GeneratorService()
        self._masking = masking or MaskingService()
        self._reservations = reservations or ReservationService(self._generator)

    # -- SEED -------------------------------------------------------------
    def seed(
        self,
        db: Session,
        scenario: str,
        count: int,
        seed: int | None = None,
        mask: bool = True,
        actor: str = "system",
    ) -> list[PoolRecord]:
        """Genera y carga ``count`` registros nuevos del escenario.

        Se enmascara por defecto. Es deliberado: el camino facil tiene que
        ser el que cumple con PCI-DSS 6.5.5 y con la Com. "A" 7724 del BCRA.
        """
        get_spec(scenario)  # valida el escenario antes de generar nada
        start_index = self._next_index(db, scenario)

        crudos = self._generator.generate(
            scenario, count, seed=seed, start_index=start_index
        )

        registros: list[PoolRecord] = []
        for crudo in crudos:
            registros.append(self._persist(db, crudo, mask=mask, action=AuditAction.SEED, actor=actor))

        db.commit()
        return registros

    # -- LOAD -------------------------------------------------------------
    def load(
        self,
        db: Session,
        registros: list[dict],
        mask: bool = True,
        actor: str = "system",
    ) -> list[PoolRecord]:
        """Carga registros preparados afuera (una extraccion de DB2, un CSV).

        Es el punto de entrada para el flujo real de un banco:
        extraer de produccion -> ENMASCARAR -> cargar en QA.
        """
        cargados = [
            self._persist(db, dict(registro), mask=mask, action=AuditAction.LOAD, actor=actor)
            for registro in registros
        ]
        db.commit()
        return cargados

    # -- REFRESH ----------------------------------------------------------
    def refresh(
        self,
        db: Session,
        min_available: int | None = None,
        reset_dirty: bool = True,
        actor: str = "system",
    ) -> RefreshResult:
        """Mantenimiento periodico del pool.

        1. Expira reservas vencidas (pasan a DIRTY).
        2. Limpia los DIRTY devolviendolos a AVAILABLE.
        3. Repone hasta el minimo por escenario.
        """
        minimo = POOL_MIN_AVAILABLE if min_available is None else min_available

        expirados = self._reservations.expire_stale(db)
        reseteados = self._reservations.reset_dirty(db, actor=actor) if reset_dirty else 0

        generados = 0
        for scenario in SCENARIOS:
            disponibles = db.execute(
                select(func.count())
                .select_from(PoolRecord)
                .where(
                    PoolRecord.scenario == scenario,
                    PoolRecord.status == DataStatus.AVAILABLE.value,
                )
            ).scalar_one()

            faltantes = minimo - disponibles
            if faltantes > 0:
                self.seed(db, scenario, faltantes, actor=actor)
                generados += faltantes

        return RefreshResult(expired=expirados, reset=reseteados, generated=generados)

    # -- STATS ------------------------------------------------------------
    def stats(self, db: Session) -> PoolStats:
        filas = db.execute(
            select(PoolRecord.scenario, PoolRecord.status, func.count())
            .group_by(PoolRecord.scenario, PoolRecord.status)
        ).all()

        acumulado: dict[str, ScenarioStats] = {}
        for scenario, status, cantidad in filas:
            entrada = acumulado.setdefault(scenario, ScenarioStats(scenario=scenario))
            if status == DataStatus.AVAILABLE.value:
                entrada.available = cantidad
            elif status == DataStatus.RESERVED.value:
                entrada.reserved = cantidad
            elif status == DataStatus.DIRTY.value:
                entrada.dirty = cantidad
            elif status == DataStatus.RETIRED.value:
                entrada.retired = cantidad
            entrada.total += cantidad

        escenarios = sorted(acumulado.values(), key=lambda s: s.scenario)
        return PoolStats(scenarios=escenarios, total=sum(s.total for s in escenarios))

    # -- EXPORT -----------------------------------------------------------
    def export_csv(
        self,
        db: Session,
        scenario: str,
        limit: int,
        reserve_for: str | None = None,
        ttl_seconds: int = 86_400,
    ) -> str:
        """Extraccion masiva a CSV para JMeter.

        JMeter necesita volumen precargado, no datos on-demand: pedir un
        registro por iteracion convertiria al TDM en el cuello de botella de
        la prueba de carga.

        Si se pasa ``reserve_for``, los registros exportados quedan reservados
        con TTL largo. Eso resuelve el problema clasico de las pruebas de
        carga: los datos se queman en la primera corrida y la segunda da
        falsos negativos porque reutiliza registros ya consumidos.
        """
        stmt = (
            select(PoolRecord)
            .where(
                PoolRecord.scenario == scenario,
                PoolRecord.status == DataStatus.AVAILABLE.value,
            )
            .order_by(PoolRecord.id)
            .limit(limit)
        )
        registros = list(db.execute(stmt).scalars())

        if reserve_for:
            ahora = utcnow()
            from datetime import timedelta

            vence = ahora + timedelta(seconds=ttl_seconds)
            for registro in registros:
                registro.status = DataStatus.RESERVED.value
                registro.reserved_by = reserve_for
                registro.reserved_at = ahora
                registro.expires_at = vence
                registro.updated_at = ahora
                audit_service.record(
                    db, registro.id, AuditAction.EXPORT, actor=reserve_for, detail="export csv"
                )
            db.commit()

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for registro in registros:
            writer.writerow({col: getattr(registro, col) for col in CSV_COLUMNS})

        return buffer.getvalue()

    # -- internos ---------------------------------------------------------
    def _persist(
        self,
        db: Session,
        crudo: dict,
        mask: bool,
        action: AuditAction,
        actor: str,
    ) -> PoolRecord:
        if mask:
            crudo.update(self._masking.mask_fields(crudo))

        registro = PoolRecord(
            **{k: v for k, v in crudo.items() if k in PoolRecord.__table__.columns.keys()},
        )
        registro.status = DataStatus.AVAILABLE.value
        registro.is_masked = mask

        db.add(registro)
        audit_service.record(
            db,
            registro.id,
            action,
            actor=actor,
            detail=f"masked={mask} scenario={registro.scenario}",
        )
        return registro

    @staticmethod
    def _next_index(db: Session, scenario: str) -> int:
        total = db.execute(
            select(func.count()).select_from(PoolRecord).where(PoolRecord.scenario == scenario)
        ).scalar_one()
        return int(total) + 1
