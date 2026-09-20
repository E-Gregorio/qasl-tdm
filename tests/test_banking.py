"""Los identificadores generados tienen que ser validos de verdad.

La validacion se cruza contra python-stdnum, una libreria independiente:
si nuestro generador y una libreria externa coinciden, el algoritmo esta
bien implementado. Es la diferencia entre un dato que la aplicacion acepta
y uno que rechaza antes de llegar a la logica que queriamos probar.
"""

from __future__ import annotations

import pytest

from app.services.banking import (
    build_cbu,
    build_cuit,
    build_pan,
    validate_cbu,
    validate_cuit,
    validate_pan,
)
from app.services.generator_service import GeneratorService

stdnum_cbu = pytest.importorskip("stdnum.ar.cbu", reason="python-stdnum no instalado")
stdnum_cuit = pytest.importorskip("stdnum.ar.cuit", reason="python-stdnum no instalado")
stdnum_luhn = pytest.importorskip("stdnum.luhn", reason="python-stdnum no instalado")


def test_cbu_conocido_es_valido():
    # Ejemplo de la documentacion de python-stdnum.
    assert validate_cbu("2850590940090418135201")


def test_cbu_generado_pasa_stdnum():
    cbu = build_cbu("072", "0001", "1234567890123")
    assert validate_cbu(cbu)
    assert stdnum_cbu.is_valid(cbu)


def test_cuit_generado_pasa_stdnum():
    cuit = build_cuit("28456789", "20")
    assert validate_cuit(cuit)
    assert stdnum_cuit.is_valid(cuit)


def test_pan_generado_pasa_luhn():
    pan = build_pan("450000", "123456789")
    assert validate_pan(pan)
    assert stdnum_luhn.is_valid(pan)


def test_lote_completo_es_valido():
    registros = GeneratorService().generate("transferencia_exitosa", 200, seed=7)

    for registro in registros:
        assert stdnum_cbu.is_valid(registro["cuenta"]), registro["cuenta"]
        assert stdnum_cuit.is_valid(registro["cuit"]), registro["cuit"]
        assert stdnum_luhn.is_valid(registro["tarjeta"]), registro["tarjeta"]


def test_generacion_es_reproducible_con_seed():
    primero = GeneratorService().generate("transferencia_exitosa", 10, seed=42)
    segundo = GeneratorService().generate("transferencia_exitosa", 10, seed=42)
    assert primero == segundo


def test_generacion_cambia_sin_seed_fijo():
    primero = GeneratorService().generate("transferencia_exitosa", 10, seed=1)
    segundo = GeneratorService().generate("transferencia_exitosa", 10, seed=2)
    assert primero != segundo
