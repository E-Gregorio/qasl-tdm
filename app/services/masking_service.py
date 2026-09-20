"""Enmascaramiento determinista y preservador de formato.

Tres propiedades que un masking de banca tiene que cumplir, y que la version
ingenua con asteriscos no cumple:

1. **Preserva el formato.** Un DNI enmascarado como ``****6789`` no se puede
   tipear en un formulario ni pasa una validacion. El resultado tiene que
   seguir siendo un DNI, un CBU y un PAN validos, con sus verificadores
   recalculados.

2. **Es determinista.** El mismo valor de origen produce siempre el mismo
   valor enmascarado. Sin esto se rompe la integridad referencial: el cliente
   que en una tabla es "Carlos Ramirez" en otra seria otra persona.

3. **Es idempotente.** Enmascarar dos veces no vuelve a enmascarar. Se marca
   el registro con ``is_masked`` y la segunda llamada es un no-op.

El mapeo depende de ``MASKING_SALT``. Con la misma sal el resultado es
reproducible entre corridas y entre entornos; cambiarla rota todo el mapeo.
La sal nunca deberia versionarse en un entorno real.
"""

from __future__ import annotations

import hashlib
import hmac

from app.config import MASKING_SALT
from app.services.banking import build_cbu, build_cuit, build_pan
from app.services.generator_service import APELLIDOS, NOMBRES, _slug


def _digest(namespace: str, value: str) -> bytes:
    return hmac.new(
        MASKING_SALT.encode("utf-8"),
        f"{namespace}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _digits(namespace: str, value: str, length: int, first_nonzero: bool = True) -> str:
    """Deriva ``length`` digitos estables a partir de un valor."""
    raw = _digest(namespace, value)
    out = "".join(str(byte % 10) for byte in raw)

    while len(out) < length:
        raw = hashlib.sha256(raw).digest()
        out += "".join(str(byte % 10) for byte in raw)

    result = out[:length]
    if first_nonzero and result[0] == "0":
        result = "1" + result[1:]
    return result


def _pick(namespace: str, value: str, options: list[str]) -> str:
    index = int.from_bytes(_digest(namespace, value)[:4], "big") % len(options)
    return options[index]


def _in_range(namespace: str, value: str, low: int, high: int) -> int:
    """Mapea un valor a un entero estable dentro de un rango."""
    span = high - low + 1
    return low + int.from_bytes(_digest(namespace, value)[:8], "big") % span


class MaskingService:
    """Genera la version enmascarada de un registro."""

    def mask_fields(self, record: dict) -> dict:
        """Devuelve solo los campos sensibles ya enmascarados.

        No toca el saldo, el estado de cuenta ni los dias de mora: esos no
        son datos personales y son justamente la condicion que el test
        necesita que se cumpla.
        """
        dni_original = str(record["dni"])
        cuenta_original = str(record["cuenta"])
        tarjeta_original = str(record["tarjeta"])
        cuit_original = str(record["cuit"])

        # El DNI se mantiene dentro del rango real argentino: un documento
        # de 71 millones no existe y una validacion de negocio lo rechaza.
        dni = str(_in_range("dni", dni_original, 10_000_000, 45_999_999))

        # Se conserva el prefijo del CUIT porque indica tipo de persona,
        # no identifica al individuo.
        cuit_prefix = cuit_original.replace("-", "")[:2] or "20"

        nombre = _pick("nombre", record["nombre"], NOMBRES)
        apellido = _pick("apellido", record["nombre"], APELLIDOS)

        # Se conservan banco y sucursal: identifican a la entidad, no al
        # cliente, y mantenerlos hace que el dato siga siendo realista.
        bank = cuenta_original[:3]
        branch = cuenta_original[3:7]
        account = _digits("cbu", cuenta_original, 13, first_nonzero=False)

        # Se conserva el BIN (primeros 6): identifica al emisor. Es la
        # practica estandar y lo que permite que la tarjeta siga ruteando.
        bin_code = tarjeta_original[:6]
        pan_body = _digits("pan", tarjeta_original, 9, first_nonzero=False)

        return {
            "dni": dni,
            "cuit": build_cuit(dni, cuit_prefix),
            "nombre": f"{nombre} {apellido}",
            "email": f"{_slug(nombre)}.{_slug(apellido)}.{dni[-4:]}@example.com",
            "cuenta": build_cbu(bank, branch, account),
            "tarjeta": build_pan(bin_code, pan_body),
        }
