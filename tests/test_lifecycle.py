"""El ciclo completo, de punta a punta."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.db import PoolRecord, utcnow
from app.models.enums import DataStatus, ReleaseOutcome
from app.services.reservation_service import (
    NotReservedError,
    PoolExhaustedError,
    ReservationService,
)


def test_health(api):
    respuesta = api.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "UP"


def test_catalogo_de_escenarios(api):
    escenarios = api.get("/tdm/pool/scenarios").json()
    nombres = {e["name"] for e in escenarios}
    assert "transferencia_exitosa" in nombres
    assert "saldo_insuficiente" in nombres


def test_seed_genera_datos_que_cumplen_el_escenario(api):
    respuesta = api.post(
        "/tdm/pool/seed",
        json={"scenario": "transferencia_exitosa", "count": 5, "seed": 1},
    )
    assert respuesta.status_code == 201

    for registro in respuesta.json():
        assert registro["saldo"] >= 100_000
        assert registro["estado_cuenta"] == "ACTIVA"
        assert registro["status"] == "AVAILABLE"
        assert registro["is_masked"] is True


def test_seed_de_escenario_inexistente_da_400(api):
    respuesta = api.post("/tdm/pool/seed", json={"scenario": "no_existe", "count": 1})
    assert respuesta.status_code == 400
    assert "no definido" in respuesta.json()["detail"]


def test_ciclo_reserve_use_release(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 3})

    reservado = api.post(
        "/tdm/reserve",
        json={"scenario": "transferencia_exitosa", "reserved_by": "worker-1", "ttl_seconds": 60},
    ).json()

    assert reservado["status"] == "RESERVED"
    assert reservado["reserved_by"] == "worker-1"
    assert reservado["expires_at"] is not None

    liberado = api.post(
        "/tdm/release",
        json={"data_id": reservado["id"], "reserved_by": "worker-1", "outcome": "CLEAN"},
    ).json()

    assert liberado["status"] == "AVAILABLE"
    assert liberado["reserved_by"] is None


def test_release_dirty_deja_el_dato_fuera_del_pool(api):
    api.post("/tdm/pool/seed", json={"scenario": "saldo_insuficiente", "count": 1})

    reservado = api.post(
        "/tdm/reserve",
        json={"scenario": "saldo_insuficiente", "reserved_by": "w"},
    ).json()

    liberado = api.post(
        "/tdm/release",
        json={"data_id": reservado["id"], "reserved_by": "w", "outcome": "DIRTY"},
    ).json()
    assert liberado["status"] == "DIRTY"

    # Con un solo registro en el pool y ese registro sucio, no hay nada que dar.
    agotado = api.post(
        "/tdm/reserve", json={"scenario": "saldo_insuficiente", "reserved_by": "w2"}
    )
    assert agotado.status_code == 409


def test_reset_devuelve_el_dato_al_pool_manteniendo_la_identidad(api):
    api.post("/tdm/pool/seed", json={"scenario": "cliente_con_mora", "count": 1})
    registro = api.get("/tdm/records", params={"limit": 1}).json()[0]

    reservado = api.post(
        "/tdm/reserve", json={"scenario": "cliente_con_mora", "reserved_by": "w"}
    ).json()
    api.post(
        "/tdm/release",
        json={"data_id": reservado["id"], "reserved_by": "w", "outcome": "DIRTY"},
    )

    reseteado = api.post(f"/tdm/reset/{registro['id']}").json()

    assert reseteado["status"] == "AVAILABLE"
    # La identidad no cambia: un test que guardo el CBU lo sigue encontrando.
    assert reseteado["cuenta"] == registro["cuenta"]
    assert reseteado["dni"] == registro["dni"]
    # La condicion de negocio se regenera dentro del rango del escenario.
    assert reseteado["dias_mora"] >= 90


def test_no_se_puede_liberar_un_dato_de_otro(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 1})
    reservado = api.post(
        "/tdm/reserve", json={"scenario": "transferencia_exitosa", "reserved_by": "worker-1"}
    ).json()

    respuesta = api.post(
        "/tdm/release",
        json={"data_id": reservado["id"], "reserved_by": "worker-2", "outcome": "CLEAN"},
    )
    assert respuesta.status_code == 409
    assert "worker-1" in respuesta.json()["detail"]


def test_pool_agotado_devuelve_409(api):
    respuesta = api.post(
        "/tdm/reserve", json={"scenario": "transferencia_exitosa", "reserved_by": "w"}
    )
    assert respuesta.status_code == 409


def test_reserva_vencida_pasa_a_dirty_no_a_available(api, db):
    """Un test que murio a mitad pudo dejar el dato en cualquier estado."""
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 1})
    reservado = api.post(
        "/tdm/reserve",
        json={"scenario": "transferencia_exitosa", "reserved_by": "w", "ttl_seconds": 60},
    ).json()

    registro = db.get(PoolRecord, reservado["id"])
    registro.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert api.post("/tdm/expire").json()["expired"] == 1
    assert api.get(f"/tdm/records/{reservado['id']}").json()["status"] == "DIRTY"


def test_refresh_expira_limpia_y_repone(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 2})

    resultado = api.post("/tdm/pool/refresh", json={"min_available": 5}).json()
    assert resultado["generated"] >= 3

    stats = api.get("/tdm/pool/stats").json()
    por_escenario = {s["scenario"]: s for s in stats["scenarios"]}
    assert por_escenario["transferencia_exitosa"]["available"] >= 5


def test_la_bitacora_registra_el_ciclo(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 1})
    reservado = api.post(
        "/tdm/reserve", json={"scenario": "transferencia_exitosa", "reserved_by": "w"}
    ).json()
    api.post(
        "/tdm/release",
        json={"data_id": reservado["id"], "reserved_by": "w", "outcome": "CLEAN"},
    )

    acciones = {e["action"] for e in api.get(f"/tdm/records/{reservado['id']}/audit").json()}
    assert {"SEED", "RESERVE", "RELEASE"} <= acciones


def test_export_csv_para_jmeter(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 10})

    respuesta = api.get(
        "/tdm/pool/export", params={"scenario": "transferencia_exitosa", "limit": 10}
    )
    assert respuesta.status_code == 200

    lineas = respuesta.text.strip().split("\n")
    assert lineas[0].startswith("id,scenario,dni,cuit")
    assert len(lineas) == 11  # cabecera + 10 filas


def test_export_con_reserva_no_quema_los_datos_dos_veces(api):
    """El problema clasico de JMeter: la segunda corrida reusa datos gastados."""
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 6})

    primera = api.get(
        "/tdm/pool/export",
        params={"scenario": "transferencia_exitosa", "limit": 3, "reserve_for": "carga-001"},
    ).text
    segunda = api.get(
        "/tdm/pool/export",
        params={"scenario": "transferencia_exitosa", "limit": 3, "reserve_for": "carga-002"},
    ).text

    ids_primera = {linea.split(",")[0] for linea in primera.strip().split("\n")[1:]}
    ids_segunda = {linea.split(",")[0] for linea in segunda.strip().split("\n")[1:]}

    assert ids_primera and ids_segunda
    assert ids_primera.isdisjoint(ids_segunda)


def test_load_enmascara_por_defecto(api):
    payload = {
        "records": [
            {
                "id": "EXT-0001",
                "scenario": "transferencia_exitosa",
                "dni": "28456789",
                "cuit": "20-28456789-3",
                "nombre": "Juan Gonzalez",
                "email": "juan.gonzalez@example.com",
                "cuenta": "0720001100000000000123",
                "tarjeta": "4000001234567899",
                "saldo": 250000.0,
                "moneda": "ARS",
                "estado_cuenta": "ACTIVA",
                "dias_mora": 0,
            }
        ]
    }
    cargado = api.post("/tdm/pool/load", json=payload).json()[0]

    assert cargado["is_masked"] is True
    assert cargado["dni"] != "28456789"
    assert cargado["nombre"] != "Juan Gonzalez"
    # La condicion de negocio se respeta tal como vino.
    assert cargado["saldo"] == 250000.0


def test_alta_duplicada_devuelve_409(api):
    payload = {
        "id": "DUP-1",
        "scenario": "transferencia_exitosa",
        "dni": "30111222",
        "cuit": "20-30111222-4",
        "nombre": "Ana Suarez",
        "email": "ana@example.com",
        "cuenta": "0720001100000000000123",
        "tarjeta": "4000001234567899",
        "saldo": 500000.0,
    }
    assert api.post("/tdm/records", json=payload).status_code == 201
    assert api.post("/tdm/records", json=payload).status_code == 409


def test_reserve_service_lanza_pool_exhausted(db):
    with pytest.raises(PoolExhaustedError):
        ReservationService().reserve(db, "transferencia_exitosa", "w")


def test_release_de_registro_inexistente(db):
    with pytest.raises(NotReservedError):
        ReservationService().release(db, "NO-EXISTE", "w", ReleaseOutcome.CLEAN)


def test_listado_filtra_por_estado(api):
    api.post("/tdm/pool/seed", json={"scenario": "transferencia_exitosa", "count": 3})
    api.post("/tdm/reserve", json={"scenario": "transferencia_exitosa", "reserved_by": "w"})

    disponibles = api.get("/tdm/records", params={"status": DataStatus.AVAILABLE.value}).json()
    reservados = api.get("/tdm/records", params={"status": DataStatus.RESERVED.value}).json()

    assert len(disponibles) == 2
    assert len(reservados) == 1
