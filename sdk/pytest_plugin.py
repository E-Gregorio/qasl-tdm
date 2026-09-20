"""Plugin de pytest de QASL-TDM.

Para usarlo en una suite de automatizacion, en el conftest.py del proyecto:

    pytest_plugins = ["sdk.pytest_plugin"]

Y despues, en cualquier test:

    def test_transferencia(tdm_scenario):
        cliente = tdm_scenario("transferencia_exitosa")
        ...

El dato se libera al terminar el test sin que haya que acordarse.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from sdk.client import DEFAULT_BASE_URL, QaslTdmClient


def pytest_addoption(parser: pytest.Parser) -> None:
    grupo = parser.getgroup("qasl-tdm")
    grupo.addoption(
        "--tdm-url",
        action="store",
        default=DEFAULT_BASE_URL,
        help="URL base del servicio QASL-TDM",
    )
    grupo.addoption(
        "--tdm-ttl",
        action="store",
        type=int,
        default=None,
        help="TTL en segundos de las reservas que tome la suite",
    )


@pytest.fixture(scope="session")
def tdm_client(request: pytest.FixtureRequest) -> Iterator[QaslTdmClient]:
    """Cliente compartido por toda la sesion de tests."""
    client = QaslTdmClient(base_url=request.config.getoption("--tdm-url"))
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def tdm_scenario(
    tdm_client: QaslTdmClient,
    request: pytest.FixtureRequest,
) -> Iterator[Callable[..., dict[str, Any]]]:
    """Reserva escenarios y los libera al terminar el test.

    Se puede pedir mas de un escenario en el mismo test; todos se liberan.
    Si el test falla, se liberan como DIRTY.
    """
    ttl = request.config.getoption("--tdm-ttl")
    reservados: list[str] = []

    def _reservar(scenario: str, ttl_seconds: int | None = None) -> dict[str, Any]:
        registro = tdm_client.reserve(scenario, ttl_seconds or ttl)
        reservados.append(registro["id"])
        return registro

    yield _reservar

    fallo = getattr(request.node, "_tdm_failed", False)
    resultado = "DIRTY" if fallo else "CLEAN"

    for data_id in reservados:
        try:
            tdm_client.release(data_id, resultado)
        except Exception:  # noqa: BLE001 - la limpieza nunca rompe el reporte
            pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Marca el test como fallado para que la fixture libere como DIRTY."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        item._tdm_failed = True
