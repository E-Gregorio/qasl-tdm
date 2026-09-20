"""La prueba que justifica todo el proyecto.

Si veinte tests corren en paralelo y dos reciben el mismo cliente, los dos
fallan por razones que nadie va a entender. Esta suite verifica que eso no
pueda pasar.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database import SessionLocal
from app.services.pool_service import PoolService
from app.services.reservation_service import PoolExhaustedError, ReservationService

WORKERS = 12
POOL = 40


@pytest.fixture
def pool_cargado(db):
    PoolService().seed(db, "transferencia_exitosa", POOL, seed=11)
    return POOL


def _reservar(worker: int) -> str | None:
    """Cada hilo abre su propia sesion, como haria un worker real."""
    session = SessionLocal()
    try:
        registro = ReservationService().reserve(
            session, "transferencia_exitosa", f"worker-{worker}", ttl_seconds=120
        )
        return registro.id
    except PoolExhaustedError:
        return None
    finally:
        session.close()


def test_reservas_concurrentes_no_se_repiten(pool_cargado):
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        obtenidos = list(executor.map(_reservar, range(WORKERS)))

    ids = [i for i in obtenidos if i is not None]

    assert len(ids) == WORKERS, "algun worker se quedo sin dato habiendo pool"
    assert len(set(ids)) == len(ids), "dos workers recibieron el mismo registro"


def test_bajo_presion_nunca_se_entrega_dos_veces(db):
    """Mas workers que registros: sobran los que no consiguen, no se duplica."""
    PoolService().seed(db, "saldo_insuficiente", 5, seed=3)

    with ThreadPoolExecutor(max_workers=10) as executor:
        obtenidos = list(
            executor.map(
                lambda w: _reservar_escenario("saldo_insuficiente", w), range(10)
            )
        )

    ids = [i for i in obtenidos if i is not None]

    assert len(ids) == 5, f"se entregaron {len(ids)} de 5 registros disponibles"
    assert len(set(ids)) == 5, "hubo entregas duplicadas"


def _reservar_escenario(scenario: str, worker: int) -> str | None:
    session = SessionLocal()
    try:
        registro = ReservationService().reserve(
            session, scenario, f"worker-{worker}", ttl_seconds=120
        )
        return registro.id
    except PoolExhaustedError:
        return None
    finally:
        session.close()
