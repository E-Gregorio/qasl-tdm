"""Generacion de datos de prueba a partir de una especificacion de escenario.

El escenario es declarativo: dice que condiciones de negocio tiene que
cumplir el dato. El generador es deterministico dado un seed, asi que el
mismo seed produce siempre el mismo lote. Eso es lo que hace reproducible
un fallo de test.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field

from app.models.enums import AccountState
from app.services.banking import build_cbu, build_cuit, build_pan

NOMBRES = [
    "Carlos", "Maria", "Jorge", "Lucia", "Martin", "Sofia", "Diego", "Valeria",
    "Ernesto", "Camila", "Rodrigo", "Paula", "Andres", "Julieta", "Sebastian",
    "Florencia", "Gonzalo", "Agustina", "Nicolas", "Micaela",
]

APELLIDOS = [
    "Ramirez", "Gomez", "Fernandez", "Lopez", "Martinez", "Sosa", "Benitez",
    "Acosta", "Medina", "Rojas", "Herrera", "Aguirre", "Molina", "Peralta",
    "Vega", "Cabrera", "Ibarra", "Quiroga", "Ledesma", "Ojeda",
]

#: Bancos ficticios. Los codigos no corresponden a entidades reales.
BANCOS = ["072", "011", "007", "191", "285"]

#: BIN de prueba. 4 = Visa, 5 = Mastercard. No pertenecen a ningun emisor real.
BINES = ["400000", "450000", "510000", "550000"]


@dataclass(frozen=True)
class ScenarioSpec:
    """Condiciones de negocio que define un escenario."""

    name: str
    description: str
    saldo_min: float
    saldo_max: float
    estado_cuenta: AccountState = AccountState.ACTIVA
    mora_min: int = 0
    mora_max: int = 0
    moneda: str = "ARS"
    tags: tuple[str, ...] = field(default=())


SCENARIOS: dict[str, ScenarioSpec] = {
    "transferencia_exitosa": ScenarioSpec(
        name="transferencia_exitosa",
        description="Cliente activo con saldo suficiente para transferir",
        saldo_min=100_000,
        saldo_max=5_000_000,
        estado_cuenta=AccountState.ACTIVA,
        tags=("transferencias", "camino_feliz"),
    ),
    "saldo_insuficiente": ScenarioSpec(
        name="saldo_insuficiente",
        description="Cliente activo sin fondos para operar",
        saldo_min=0,
        saldo_max=999,
        estado_cuenta=AccountState.ACTIVA,
        tags=("transferencias", "camino_alternativo"),
    ),
    "cuenta_bloqueada": ScenarioSpec(
        name="cuenta_bloqueada",
        description="Cuenta con saldo pero bloqueada operativamente",
        saldo_min=10_000,
        saldo_max=500_000,
        estado_cuenta=AccountState.BLOQUEADA,
        tags=("transferencias", "restricciones"),
    ),
    "cuenta_cerrada": ScenarioSpec(
        name="cuenta_cerrada",
        description="Cuenta dada de baja",
        saldo_min=0,
        saldo_max=0,
        estado_cuenta=AccountState.CERRADA,
        tags=("restricciones",),
    ),
    "cliente_con_mora": ScenarioSpec(
        name="cliente_con_mora",
        description="Cliente con mora mayor a 90 dias",
        saldo_min=0,
        saldo_max=50_000,
        estado_cuenta=AccountState.ACTIVA,
        mora_min=90,
        mora_max=365,
        tags=("riesgo", "cobranzas"),
    ),
    "transferencia_usd": ScenarioSpec(
        name="transferencia_usd",
        description="Cuenta en dolares con saldo suficiente",
        saldo_min=1_000,
        saldo_max=50_000,
        estado_cuenta=AccountState.ACTIVA,
        moneda="USD",
        tags=("transferencias", "moneda_extranjera"),
    ),
}


class UnknownScenarioError(ValueError):
    """El escenario solicitado no esta definido."""


def get_spec(scenario: str) -> ScenarioSpec:
    try:
        return SCENARIOS[scenario]
    except KeyError as exc:
        conocidos = ", ".join(sorted(SCENARIOS))
        raise UnknownScenarioError(
            f"Escenario '{scenario}' no definido. Disponibles: {conocidos}"
        ) from exc


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if c.isascii() and c.isalnum()).lower()


class GeneratorService:
    """Produce registros que cumplen la especificacion de un escenario."""

    def generate(
        self,
        scenario: str,
        count: int,
        seed: int | None = None,
        id_prefix: str = "TD",
        start_index: int = 1,
    ) -> list[dict]:
        spec = get_spec(scenario)
        rng = random.Random(seed)

        registros: list[dict] = []
        for offset in range(count):
            index = start_index + offset
            registros.append(self._build_one(spec, rng, id_prefix, index))

        return registros

    def volatile_values(self, scenario: str, seed: int | None = None) -> dict:
        """Valores que RESET regenera, manteniendo la identidad del cliente.

        La identidad (DNI, CUIT, CBU, tarjeta) no cambia nunca: si cambiara,
        un test que guardo el identificador para verificar despues dejaria de
        encontrarlo. Lo que se restaura es la condicion de negocio.
        """
        spec = get_spec(scenario)
        rng = random.Random(seed)
        return {
            "saldo": self._saldo(spec, rng),
            "moneda": spec.moneda,
            "estado_cuenta": spec.estado_cuenta.value,
            "dias_mora": rng.randint(spec.mora_min, spec.mora_max),
        }

    # -- internos ---------------------------------------------------------
    def _build_one(self, spec: ScenarioSpec, rng: random.Random, prefix: str, index: int) -> dict:
        nombre = rng.choice(NOMBRES)
        apellido = rng.choice(APELLIDOS)
        dni = str(rng.randint(10_000_000, 45_999_999))
        cuit_prefix = rng.choice(["20", "23", "24", "27"])

        return {
            "id": f"{prefix}-{spec.name.upper()}-{index:06d}",
            "scenario": spec.name,
            "dni": dni,
            "cuit": build_cuit(dni, cuit_prefix),
            "nombre": f"{nombre} {apellido}",
            "email": f"{_slug(nombre)}.{_slug(apellido)}{index}@example.com",
            "cuenta": build_cbu(
                rng.choice(BANCOS),
                str(rng.randint(1, 9999)),
                str(rng.randint(0, 9_999_999_999_999)),
            ),
            "tarjeta": build_pan(rng.choice(BINES), str(rng.randint(0, 999_999_999))),
            "saldo": self._saldo(spec, rng),
            "moneda": spec.moneda,
            "estado_cuenta": spec.estado_cuenta.value,
            "dias_mora": rng.randint(spec.mora_min, spec.mora_max),
        }

    @staticmethod
    def _saldo(spec: ScenarioSpec, rng: random.Random) -> float:
        if spec.saldo_max <= spec.saldo_min:
            return float(spec.saldo_min)
        return round(rng.uniform(spec.saldo_min, spec.saldo_max), 2)
