"""Configuracion central de QASL-TDM.

Todo se controla por variables de entorno para poder cambiar de motor
(SQLite local / PostgreSQL en Docker) sin tocar codigo.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

#: URL de conexion. SQLite por defecto para arrancar sin dependencias.
#: Para PostgreSQL: postgresql+psycopg://qasl:qasl@localhost:5432/qasl_tdm
DATABASE_URL = os.getenv(
    "QASL_TDM_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'qasl_tdm.db').as_posix()}",
)

#: Semilla del enmascaramiento. Cambiarla produce otro mapeo de valores.
#: En un entorno real vive en un secret manager, nunca en el repositorio.
MASKING_SALT = os.getenv("QASL_TDM_MASKING_SALT", "qasl-tdm-local-salt")

#: Vida util por defecto de una reserva, en segundos.
DEFAULT_TTL_SECONDS = int(os.getenv("QASL_TDM_DEFAULT_TTL", "300"))

#: Cantidad minima de registros disponibles por escenario que REFRESH mantiene.
POOL_MIN_AVAILABLE = int(os.getenv("QASL_TDM_POOL_MIN", "20"))

#: Reintentos del camino generico de reserva cuando hay contencion.
RESERVE_MAX_RETRIES = int(os.getenv("QASL_TDM_RESERVE_RETRIES", "8"))
