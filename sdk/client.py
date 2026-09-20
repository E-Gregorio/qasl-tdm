"""Cliente Python de QASL-TDM.

La pieza que hace que el automatizador no tenga que saber nada del TDM:

    from sdk import QaslTdmClient

    tdm = QaslTdmClient("http://localhost:8000")

    with tdm.scenario("transferencia_exitosa") as cliente:
        page.fill("#cuenta", cliente["cuenta"])
        page.fill("#monto", "1000")

El context manager libera el dato al salir, incluso si el test falla. Si
hubo excepcion lo libera como DIRTY, porque no se puede asumir que el dato
quedo intacto.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

DEFAULT_BASE_URL = os.getenv("QASL_TDM_URL", "http://localhost:8000")


def default_worker_id() -> str:
    """Identificador estable por proceso, util para rastrear quien reservo."""
    xdist = os.getenv("PYTEST_XDIST_WORKER")
    sufijo = xdist or uuid.uuid4().hex[:8]
    return f"{socket.gethostname()}:{os.getpid()}:{sufijo}"


class QaslTdmError(RuntimeError):
    """Error devuelto por la API de QASL-TDM."""


class PoolExhausted(QaslTdmError):
    """No quedan datos disponibles para el escenario pedido."""


class QaslTdmClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        worker_id: str | None = None,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.worker_id = worker_id or default_worker_id()
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self._owns_client = client is None

    # -- ciclo de vida del cliente ---------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> QaslTdmClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- operaciones ------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def scenarios(self) -> list[dict[str, Any]]:
        return self._request("GET", "/tdm/pool/scenarios")

    def stats(self) -> dict[str, Any]:
        return self._request("GET", "/tdm/pool/stats")

    def seed(self, scenario: str, count: int = 50, seed: int | None = None) -> list[dict]:
        return self._request(
            "POST", "/tdm/pool/seed",
            json={"scenario": scenario, "count": count, "seed": seed},
        )

    def refresh(self, min_available: int | None = None) -> dict[str, Any]:
        return self._request(
            "POST", "/tdm/pool/refresh",
            json={"min_available": min_available, "reset_dirty": True},
        )

    def reserve(self, scenario: str, ttl_seconds: int | None = None) -> dict[str, Any]:
        """Reserva un registro. Lanza PoolExhausted si no hay disponibles."""
        return self._request(
            "POST", "/tdm/reserve",
            json={
                "scenario": scenario,
                "reserved_by": self.worker_id,
                "ttl_seconds": ttl_seconds,
            },
        )

    def release(self, data_id: str, outcome: str = "CLEAN") -> dict[str, Any]:
        return self._request(
            "POST", "/tdm/release",
            json={"data_id": data_id, "reserved_by": self.worker_id, "outcome": outcome},
        )

    def reset(self, data_id: str) -> dict[str, Any]:
        return self._request("POST", f"/tdm/reset/{data_id}")

    def get(self, data_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tdm/records/{data_id}")

    def audit(self, data_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/tdm/records/{data_id}/audit")

    def export_csv(
        self,
        scenario: str,
        limit: int = 1000,
        reserve_for: str | None = None,
        path: str | None = None,
    ) -> str:
        """Descarga el CSV de volumen para JMeter. Si se pasa ``path``, lo guarda."""
        params: dict[str, Any] = {"scenario": scenario, "limit": limit}
        if reserve_for:
            params["reserve_for"] = reserve_for

        response = self._client.get("/tdm/pool/export", params=params)
        self._raise_for_status(response)

        if path:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(response.text)

        return response.text

    # -- azucar para los tests --------------------------------------------
    @contextmanager
    def scenario(
        self,
        name: str,
        ttl_seconds: int | None = None,
        always_dirty: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Reserva un registro y lo libera al salir, pase lo que pase.

        Si el bloque lanza excepcion, se libera como DIRTY: un test que fallo
        a mitad de camino pudo haber dejado el dato en un estado intermedio.
        Devolverlo al pool sin revisarlo es como se contamina un ambiente.
        """
        registro = self.reserve(name, ttl_seconds)
        sucio = always_dirty

        try:
            yield registro
        except BaseException:
            sucio = True
            raise
        finally:
            try:
                self.release(registro["id"], "DIRTY" if sucio else "CLEAN")
            except QaslTdmError:
                # Si falla la liberacion, el TTL lo recupera igual. No se
                # enmascara el error original del test con uno de limpieza.
                pass

    # -- internos ---------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return

        try:
            detalle = response.json().get("detail", response.text)
        except ValueError:
            detalle = response.text

        if response.status_code == 409 and "AVAILABLE" in str(detalle):
            raise PoolExhausted(detalle)

        raise QaslTdmError(f"[{response.status_code}] {detalle}")
