"""Estados del ciclo de vida del dato de prueba."""

from __future__ import annotations

from enum import Enum


class DataStatus(str, Enum):
    """Estado de un registro dentro del pool.

    Nota de diseno: no existe un estado IN_USE separado de RESERVED.
    Desde el punto de vista del pool, un dato reservado esta fuera de
    circulacion; distinguir "reservado" de "en uso" obligaria al consumidor
    a hacer una llamada extra que no aporta informacion nueva.
    """

    AVAILABLE = "AVAILABLE"
    """Disponible para ser reservado."""

    RESERVED = "RESERVED"
    """Tomado por una ejecucion, con vencimiento."""

    DIRTY = "DIRTY"
    """Usado y modificado. No se puede reutilizar hasta hacer RESET."""

    RETIRED = "RETIRED"
    """Fuera de servicio de forma permanente."""


class AccountState(str, Enum):
    """Estado de la cuenta bancaria, parte de la condicion de negocio."""

    ACTIVA = "ACTIVA"
    BLOQUEADA = "BLOQUEADA"
    CERRADA = "CERRADA"


class ReleaseOutcome(str, Enum):
    """Como termino el consumo del dato."""

    CLEAN = "CLEAN"
    """El test no modifico el dato: vuelve directo a AVAILABLE."""

    DIRTY = "DIRTY"
    """El test modifico el dato: requiere RESET antes de reutilizarse."""


class AuditAction(str, Enum):
    """Acciones registradas en la bitacora del ciclo de vida."""

    CREATE = "CREATE"
    SEED = "SEED"
    LOAD = "LOAD"
    MASK = "MASK"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    RESET = "RESET"
    EXPIRE = "EXPIRE"
    EXPORT = "EXPORT"
    RETIRE = "RETIRE"
