"""QASL-TDM — punto de entrada de la aplicacion."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import pool, records, reservations
from app.config import DATABASE_URL, DEFAULT_TTL_SECONDS, POOL_MIN_AVAILABLE
from app.database import Base, engine
from app.models import db as _db_models  # noqa: F401  (registra las tablas)

DESCRIPTION = """
Gestion del ciclo de vida de los datos de prueba y entrega a los procesos
de automatizacion.

```
CREATE / EXTRACT -> MASK -> LOAD -> RESERVE -> USE -> RELEASE / RESET -> REFRESH
```

La mitad batch (seed, mask, load, refresh) corre por lotes en un job.
La mitad de runtime (reserve, release) responde en milisegundos a cada test.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="QASL-TDM",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(records.router)
app.include_router(pool.router)
app.include_router(reservations.router)


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    motor = DATABASE_URL.split("://", 1)[0]
    return {
        "status": "UP",
        "engine": motor,
        "default_ttl_seconds": DEFAULT_TTL_SECONDS,
        "pool_min_available": POOL_MIN_AVAILABLE,
    }
