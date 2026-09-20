"""Endpoints del pool: SEED, LOAD, REFRESH, STATS y export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, pool_service, tdm_service
from app.models.schemas import (
    DataRecord,
    LoadRequest,
    PoolStats,
    RefreshRequest,
    RefreshResult,
    SeedRequest,
)
from app.services.generator_service import SCENARIOS, UnknownScenarioError

router = APIRouter(prefix="/tdm/pool", tags=["Pool"])


@router.get("/scenarios")
def list_scenarios() -> list[dict]:
    """Catalogo de escenarios disponibles y su condicion de negocio."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "saldo_min": spec.saldo_min,
            "saldo_max": spec.saldo_max,
            "estado_cuenta": spec.estado_cuenta.value,
            "dias_mora": [spec.mora_min, spec.mora_max],
            "moneda": spec.moneda,
            "tags": list(spec.tags),
        }
        for spec in sorted(SCENARIOS.values(), key=lambda s: s.name)
    ]


@router.post("/seed", response_model=list[DataRecord], status_code=status.HTTP_201_CREATED)
def seed_pool(payload: SeedRequest, db: Session = Depends(get_db)) -> list[DataRecord]:
    """SEED. Genera datos sinteticos que cumplen el escenario."""
    try:
        registros = pool_service.seed(db, payload.scenario, payload.count, payload.seed)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return [DataRecord.model_validate(r) for r in registros]


@router.post("/load", response_model=list[DataRecord], status_code=status.HTTP_201_CREATED)
def load_pool(payload: LoadRequest, db: Session = Depends(get_db)) -> list[DataRecord]:
    """LOAD. Carga registros preparados afuera (extraccion de DB2, CSV, API)."""
    crudos = []
    for registro in payload.records:
        datos = registro.model_dump()
        datos["estado_cuenta"] = registro.estado_cuenta.value
        crudos.append(datos)

    registros = pool_service.load(db, crudos, mask=payload.mask)
    return [DataRecord.model_validate(r) for r in registros]


@router.post("/refresh", response_model=RefreshResult)
def refresh_pool(
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
) -> RefreshResult:
    """REFRESH. Expira vencidos, limpia DIRTY y repone hasta el minimo."""
    payload = payload or RefreshRequest()
    return pool_service.refresh(db, payload.min_available, payload.reset_dirty)


@router.get("/stats", response_model=PoolStats)
def pool_stats(db: Session = Depends(get_db)) -> PoolStats:
    """Estado del pool por escenario. Es el tablero de operacion."""
    return pool_service.stats(db)


@router.post("/mask-all")
def mask_all(db: Session = Depends(get_db)) -> dict:
    """Enmascara todo lo que quedo sin enmascarar."""
    return {"masked": tdm_service.mask_all(db)}


@router.get("/export", response_class=PlainTextResponse)
def export_csv(
    scenario: str,
    limit: int = Query(default=1000, ge=1, le=1_000_000),
    reserve_for: str | None = Query(
        default=None,
        description="Si se indica, reserva los registros exportados para esa corrida",
    ),
    ttl_seconds: int = Query(default=86_400, ge=60),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Extraccion masiva a CSV para JMeter (CSV Data Set Config)."""
    contenido = pool_service.export_csv(db, scenario, limit, reserve_for, ttl_seconds)
    return PlainTextResponse(
        content=contenido,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{scenario}.csv"'},
    )
