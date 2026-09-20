"""Contratos de entrada y salida de la API (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountState, DataStatus, ReleaseOutcome


class DataRecord(BaseModel):
    """Representacion publica de un registro del pool."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Identificador unico del registro")
    scenario: str = Field(..., description="Escenario de negocio que cubre")

    dni: str = Field(..., description="Documento del cliente")
    cuit: str = Field(..., description="CUIT del cliente, con digito verificador valido")
    nombre: str = Field(..., description="Nombre completo del cliente")
    email: str = Field(..., description="Correo del cliente")

    cuenta: str = Field(..., description="CBU de 22 digitos con ambos verificadores validos")
    tarjeta: str = Field(..., description="PAN de 16 digitos que satisface Luhn")

    saldo: float = Field(..., description="Saldo disponible en la cuenta")
    moneda: str = Field(default="ARS", description="Moneda de la cuenta")
    estado_cuenta: AccountState = Field(default=AccountState.ACTIVA)
    dias_mora: int = Field(default=0, description="Dias de mora del cliente")

    status: DataStatus = Field(default=DataStatus.AVAILABLE)
    is_masked: bool = Field(default=False)

    reserved_by: str | None = None
    reserved_at: datetime | None = None
    expires_at: datetime | None = None


class DataRecordCreate(BaseModel):
    """Alta manual de un registro. Los campos de ciclo de vida los fija el servidor."""

    id: str
    scenario: str
    dni: str
    cuit: str
    nombre: str
    email: str
    cuenta: str
    tarjeta: str
    saldo: float
    moneda: str = "ARS"
    estado_cuenta: AccountState = AccountState.ACTIVA
    dias_mora: int = 0


class SeedRequest(BaseModel):
    """Generacion masiva de registros para un escenario."""

    scenario: str = Field(..., description="Nombre del escenario a generar")
    count: int = Field(default=50, ge=1, le=100_000)
    seed: int | None = Field(
        default=None,
        description="Semilla del generador. Fijarla hace la generacion reproducible.",
    )


class LoadRequest(BaseModel):
    """Carga de registros ya preparados fuera de QASL-TDM."""

    records: list[DataRecordCreate]
    mask: bool = Field(
        default=True,
        description="Enmascara al cargar. Es el comportamiento por defecto a proposito.",
    )


class ReserveRequest(BaseModel):
    scenario: str
    reserved_by: str = Field(..., description="Quien reserva: worker, job o persona")
    ttl_seconds: int | None = Field(default=None, ge=1, le=86_400)


class ReleaseRequest(BaseModel):
    data_id: str
    reserved_by: str
    outcome: ReleaseOutcome = ReleaseOutcome.CLEAN


class RefreshRequest(BaseModel):
    min_available: int | None = Field(default=None, ge=0)
    reset_dirty: bool = Field(default=True)


class ScenarioStats(BaseModel):
    scenario: str
    available: int = 0
    reserved: int = 0
    dirty: int = 0
    retired: int = 0
    total: int = 0


class PoolStats(BaseModel):
    scenarios: list[ScenarioStats]
    total: int


class RefreshResult(BaseModel):
    expired: int = Field(..., description="Reservas vencidas pasadas a DIRTY")
    reset: int = Field(..., description="Registros DIRTY devueltos a AVAILABLE")
    generated: int = Field(..., description="Registros nuevos creados para llegar al minimo")


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_id: str
    action: str
    actor: str
    detail: str | None
    created_at: datetime
