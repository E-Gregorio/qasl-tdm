"""Motor de base de datos y sesion.

QASL-TDM funciona sobre SQLite (laboratorio) y PostgreSQL (concurrencia real).
El codigo de reserva consulta estas banderas para elegir la estrategia de
bloqueo correcta en cada motor.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgres")

_connect_args: dict = {}
if IS_SQLITE:
    # check_same_thread=False permite usar la sesion desde los workers de
    # uvicorn; el timeout evita "database is locked" bajo contencion.
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=not IS_SQLITE,
    future=True,
)


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        """WAL mejora la concurrencia lectura/escritura de SQLite."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass
