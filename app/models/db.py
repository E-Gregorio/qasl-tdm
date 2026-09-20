"""Tablas de QASL-TDM."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import AccountState, DataStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PoolRecord(Base):
    """Un registro del pool de datos de prueba.

    Un registro representa un escenario completo y autocontenido: el
    automatizador reserva esta fila y tiene todo lo que necesita para
    ejecutar el caso. La unidad de reserva es el escenario, no la entidad
    suelta, justamente para evitar interbloqueos entre tests que toman
    piezas en distinto orden.
    """

    __tablename__ = "test_data"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # --- Identidad (PII) ---
    dni: Mapped[str] = mapped_column(String(16), nullable=False)
    cuit: Mapped[str] = mapped_column(String(16), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False)

    # --- Instrumentos (PII / PCI) ---
    cuenta: Mapped[str] = mapped_column(String(22), nullable=False)
    tarjeta: Mapped[str] = mapped_column(String(19), nullable=False)

    # --- Condicion de negocio ---
    saldo: Mapped[float] = mapped_column(Float, nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="ARS")
    estado_cuenta: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AccountState.ACTIVA.value
    )
    dias_mora: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Ciclo de vida ---
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataStatus.AVAILABLE.value, index=True
    )
    is_masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    reserved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


# Indice compuesto: es la consulta que ejecuta RESERVE en cada llamada.
Index("ix_test_data_scenario_status", PoolRecord.scenario, PoolRecord.status)


class AuditLog(Base):
    """Bitacora de transiciones del ciclo de vida.

    Existe por una razon concreta: la Comunicacion "A" 7724 del BCRA (9.2.2)
    exige documentar el diseno, creacion y preparacion de los datos de prueba.
    Esta tabla es esa documentacion, generada automaticamente.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
