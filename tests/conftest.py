"""Configuracion de la suite.

La base de test se define ANTES de importar la aplicacion, porque el engine
se construye en tiempo de import. Por defecto usa un SQLite temporal que se
borra al terminar: un proyecto de gestion del ciclo de vida del dato no puede
dejar basura en sus propios tests.

Para correr la misma suite contra PostgreSQL y ejercitar el camino de
``FOR UPDATE SKIP LOCKED``, basta con exportar la variable antes de invocar
pytest:

    QASL_TDM_DATABASE_URL=postgresql+psycopg://qasl:qasl@localhost:5432/qasl_tdm pytest
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.gettempdir()) / "qasl_tdm_tests.db"

# setdefault, no asignacion directa: si el entorno ya define un motor
# (PostgreSQL en CI, por ejemplo) se respeta.
os.environ.setdefault("QASL_TDM_DATABASE_URL", f"sqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("QASL_TDM_MASKING_SALT", "salt-de-test")

_USING_TMP_SQLITE = os.environ["QASL_TDM_DATABASE_URL"] == f"sqlite:///{_TMP_DB.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from sdk.client import QaslTdmClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    if _USING_TMP_SQLITE and _TMP_DB.exists():
        _TMP_DB.unlink()

    Base.metadata.create_all(bind=engine)
    yield

    if not _USING_TMP_SQLITE:
        # En un motor externo no se borra el archivo: se limpian las tablas.
        Base.metadata.drop_all(bind=engine)

    engine.dispose()

    if _USING_TMP_SQLITE:
        _TMP_DB.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """Cada test arranca con el pool vacio."""
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sdk(api: TestClient) -> Iterator[QaslTdmClient]:
    """SDK apuntado contra la app en memoria, sin levantar un servidor."""
    client = QaslTdmClient(base_url="http://testserver", client=api, worker_id="worker-test")
    yield client
