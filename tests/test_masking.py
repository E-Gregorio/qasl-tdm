"""Las tres propiedades que tiene que cumplir el enmascaramiento."""

from __future__ import annotations

import pytest

from app.services.banking import validate_cbu, validate_cuit, validate_pan
from app.services.generator_service import GeneratorService
from app.services.masking_service import MaskingService

stdnum_cbu = pytest.importorskip("stdnum.ar.cbu")
stdnum_cuit = pytest.importorskip("stdnum.ar.cuit")
stdnum_luhn = pytest.importorskip("stdnum.luhn")


@pytest.fixture
def registro() -> dict:
    return GeneratorService().generate("transferencia_exitosa", 1, seed=99)[0]


def test_el_dato_enmascarado_sigue_siendo_valido(registro):
    """Propiedad 1: preserva el formato y los verificadores."""
    enmascarado = MaskingService().mask_fields(registro)

    assert len(enmascarado["dni"]) == 8 and enmascarado["dni"].isdigit()
    assert validate_cuit(enmascarado["cuit"]) and stdnum_cuit.is_valid(enmascarado["cuit"])
    assert validate_cbu(enmascarado["cuenta"]) and stdnum_cbu.is_valid(enmascarado["cuenta"])
    assert validate_pan(enmascarado["tarjeta"]) and stdnum_luhn.is_valid(enmascarado["tarjeta"])


def test_el_dato_enmascarado_es_distinto_del_original(registro):
    enmascarado = MaskingService().mask_fields(registro)

    assert enmascarado["dni"] != registro["dni"]
    assert enmascarado["cuenta"] != registro["cuenta"]
    assert enmascarado["tarjeta"] != registro["tarjeta"]
    assert enmascarado["nombre"] != registro["nombre"]


def test_no_quedan_asteriscos(registro):
    """Un dato con asteriscos no se puede tipear en un formulario."""
    enmascarado = MaskingService().mask_fields(registro)
    assert "*" not in "".join(str(v) for v in enmascarado.values())


def test_es_deterministico(registro):
    """Propiedad 2: el mismo origen produce siempre el mismo resultado.

    Sin esto se rompe la integridad referencial entre tablas.
    """
    servicio = MaskingService()
    assert servicio.mask_fields(registro) == servicio.mask_fields(registro)


def test_mismo_dni_en_registros_distintos_da_el_mismo_valor():
    servicio = MaskingService()
    base = GeneratorService().generate("transferencia_exitosa", 1, seed=5)[0]
    otro = {**base, "id": "OTRO", "nombre": base["nombre"]}

    assert servicio.mask_fields(base)["dni"] == servicio.mask_fields(otro)["dni"]


def test_conserva_banco_sucursal_y_bin(registro):
    """Identifican a la entidad emisora, no a la persona."""
    enmascarado = MaskingService().mask_fields(registro)

    assert enmascarado["cuenta"][:7] == registro["cuenta"][:7]
    assert enmascarado["tarjeta"][:6] == registro["tarjeta"][:6]


def test_no_toca_la_condicion_de_negocio(registro):
    """El saldo y el estado son la razon por la que el dato sirve."""
    enmascarado = MaskingService().mask_fields(registro)

    assert "saldo" not in enmascarado
    assert "estado_cuenta" not in enmascarado


def test_es_idempotente_via_api(api, sdk):
    """Propiedad 3: enmascarar dos veces no vuelve a enmascarar.

    Este era el bug de la version anterior: ****6789 se convertia en
    ********6789 en la segunda llamada.
    """
    sdk.seed("transferencia_exitosa", 1, seed=3)
    data_id = sdk.stats() and api.get("/tdm/records", params={"limit": 1}).json()[0]["id"]

    primero = api.post(f"/tdm/records/{data_id}/mask").json()
    segundo = api.post(f"/tdm/records/{data_id}/mask").json()

    assert primero["dni"] == segundo["dni"]
    assert primero["cuenta"] == segundo["cuenta"]
    assert primero["tarjeta"] == segundo["tarjeta"]
    assert segundo["is_masked"] is True
