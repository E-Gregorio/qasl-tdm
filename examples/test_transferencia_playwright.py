"""Como consume el automatizador los datos de QASL-TDM.

Este archivo no forma parte de la suite del proyecto: es el ejemplo de uso.
Para correrlo hace falta el servicio levantado y Playwright instalado.

    uvicorn app.main:app
    python cli.py seed-all --count 50
    pytest examples -m e2e

Lo importante es lo que el test NO tiene: ni SQL, ni DNIs hardcodeados, ni
un Excel con cuentas, ni limpieza manual. Pide el escenario y trabaja.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

playwright_sync = pytest.importorskip(
    "playwright.sync_api", reason="Playwright no instalado"
)


@pytest.fixture(scope="session")
def page():
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        pagina = browser.new_page()
        yield pagina
        browser.close()


def test_transferencia_exitosa(page, tdm_scenario):
    """Camino feliz: el dato ya viene con saldo suficiente y cuenta activa."""
    cliente = tdm_scenario("transferencia_exitosa")

    page.goto("https://mi-banco-de-pruebas.local/transferencias")
    page.fill("#cuenta-origen", cliente["cuenta"])
    page.fill("#cuit", cliente["cuit"])
    page.fill("#monto", "1000")
    page.click("#confirmar")

    assert page.locator("#resultado").inner_text() == "Transferencia realizada"


def test_transferencia_rechazada_por_saldo(page, tdm_scenario):
    """El escenario garantiza saldo menor a 1000. No hay que prepararlo."""
    cliente = tdm_scenario("saldo_insuficiente")

    page.goto("https://mi-banco-de-pruebas.local/transferencias")
    page.fill("#cuenta-origen", cliente["cuenta"])
    page.fill("#monto", "5000")
    page.click("#confirmar")

    assert "saldo insuficiente" in page.locator("#error").inner_text().lower()


def test_operacion_sobre_cuenta_bloqueada(page, tdm_scenario):
    cliente = tdm_scenario("cuenta_bloqueada")

    page.goto("https://mi-banco-de-pruebas.local/transferencias")
    page.fill("#cuenta-origen", cliente["cuenta"])
    page.click("#confirmar")

    assert "bloqueada" in page.locator("#error").inner_text().lower()


def test_dos_tests_en_paralelo_nunca_comparten_cliente(tdm_scenario):
    """Se pueden pedir varios escenarios; todos se liberan al terminar."""
    primero = tdm_scenario("transferencia_exitosa")
    segundo = tdm_scenario("transferencia_exitosa")

    assert primero["id"] != segundo["id"]
    assert primero["cuenta"] != segundo["cuenta"]
