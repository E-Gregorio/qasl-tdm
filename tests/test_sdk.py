"""El SDK es lo que ve el automatizador. Tiene que ser a prueba de olvidos."""

from __future__ import annotations

import pytest

from sdk.client import PoolExhausted


def test_context_manager_libera_al_salir(sdk, api):
    sdk.seed("transferencia_exitosa", 2, seed=4)

    with sdk.scenario("transferencia_exitosa") as cliente:
        assert cliente["status"] == "RESERVED"
        data_id = cliente["id"]
        assert api.get(f"/tdm/records/{data_id}").json()["status"] == "RESERVED"

    assert api.get(f"/tdm/records/{data_id}").json()["status"] == "AVAILABLE"


def test_si_el_test_falla_el_dato_queda_dirty(sdk, api):
    """No se puede asumir que un test que exploto dejo el dato intacto."""
    sdk.seed("transferencia_exitosa", 1, seed=4)

    with pytest.raises(ValueError):
        with sdk.scenario("transferencia_exitosa") as cliente:
            data_id = cliente["id"]
            raise ValueError("el test fallo a mitad de camino")

    assert api.get(f"/tdm/records/{data_id}").json()["status"] == "DIRTY"


def test_pool_agotado_lanza_excepcion_clara(sdk):
    with pytest.raises(PoolExhausted):
        sdk.reserve("transferencia_exitosa")


def test_el_dato_trae_todo_lo_que_el_test_necesita(sdk):
    sdk.seed("transferencia_exitosa", 1, seed=8)

    with sdk.scenario("transferencia_exitosa") as cliente:
        for campo in ("dni", "cuit", "nombre", "email", "cuenta", "tarjeta", "saldo"):
            assert cliente[campo], f"falta {campo}"
        assert cliente["saldo"] >= 100_000


def test_export_csv_desde_el_sdk(sdk, tmp_path):
    sdk.seed("transferencia_exitosa", 5, seed=2)
    destino = tmp_path / "carga.csv"

    contenido = sdk.export_csv("transferencia_exitosa", limit=5, path=str(destino))

    assert destino.exists()
    assert contenido.startswith("id,scenario,dni,cuit")
    assert len(destino.read_text(encoding="utf-8").strip().split("\n")) == 6


def test_stats_y_refresh(sdk):
    sdk.seed("transferencia_exitosa", 3, seed=6)
    assert sdk.stats()["total"] == 3

    sdk.refresh(min_available=4)
    assert sdk.stats()["total"] > 3


def test_la_bitacora_es_consultable_desde_el_sdk(sdk):
    sdk.seed("cuenta_bloqueada", 1, seed=9)

    with sdk.scenario("cuenta_bloqueada") as cliente:
        data_id = cliente["id"]

    acciones = {entrada["action"] for entrada in sdk.audit(data_id)}
    assert {"SEED", "RESERVE", "RELEASE"} <= acciones
