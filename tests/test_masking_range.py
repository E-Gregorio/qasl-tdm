"""El dato enmascarado tiene que ser verosimil, no solo tener el formato.

Un DNI de 71 millones tiene ocho digitos y pasa cualquier validacion de
formato, pero no existe: una validacion de negocio lo rechaza y el test
muere antes de probar nada.
"""

from __future__ import annotations

from app.services.generator_service import GeneratorService
from app.services.masking_service import MaskingService


def test_el_dni_enmascarado_queda_en_rango_real():
    servicio = MaskingService()
    registros = GeneratorService().generate("transferencia_exitosa", 300, seed=13)

    for registro in registros:
        dni = int(servicio.mask_fields(registro)["dni"])
        assert 10_000_000 <= dni <= 45_999_999, dni


def test_el_saldo_enmascarado_sigue_cumpliendo_el_escenario():
    """El masking no puede romper la condicion que hace util al dato."""
    servicio = MaskingService()
    registros = GeneratorService().generate("transferencia_exitosa", 50, seed=17)

    for registro in registros:
        enmascarado = {**registro, **servicio.mask_fields(registro)}
        assert enmascarado["saldo"] >= 100_000
        assert enmascarado["estado_cuenta"] == "ACTIVA"
