"""Primitivas de dominio bancario: identificadores con digito verificador.

Un dato de prueba bancario que no pasa la validacion de formato no sirve:
la aplicacion lo rechaza antes de llegar a la logica que uno queria probar.
Por eso todo lo que genera QASL-TDM se construye con su checksum correcto.

Referencias de los algoritmos:
- CUIT/CUIL: modulo 11 con ponderadores 5,4,3,2,7,6,5,4,3,2
- CBU: dos bloques, ponderadores ciclicos 3,1,7,9 sobre el bloque invertido
- PAN: algoritmo de Luhn (ISO/IEC 7812-1)
"""

from __future__ import annotations

CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
CBU_WEIGHTS = (3, 1, 7, 9)


# --------------------------------------------------------------------------
# CUIT / CUIL
# --------------------------------------------------------------------------
def cuit_check_digit(prefix: str, dni: str) -> str:
    """Calcula el digito verificador de un CUIT a partir del prefijo y el DNI."""
    body = f"{prefix}{dni.zfill(8)}"
    total = sum(int(d) * w for d, w in zip(body, CUIT_WEIGHTS))
    remainder = total % 11

    if remainder == 0:
        return "0"
    if remainder == 1:
        # Caso especial: se reasigna el prefijo en la practica. Para datos de
        # prueba alcanza con devolver 9, que es la convencion habitual.
        return "9"
    return str(11 - remainder)


def build_cuit(dni: str, prefix: str = "20") -> str:
    """Devuelve un CUIT formateado PP-DNI-V."""
    dni = dni.zfill(8)
    return f"{prefix}-{dni}-{cuit_check_digit(prefix, dni)}"


def validate_cuit(cuit: str) -> bool:
    digits = cuit.replace("-", "")
    if len(digits) != 11 or not digits.isdigit():
        return False
    return cuit_check_digit(digits[:2], digits[2:10]) == digits[10]


# --------------------------------------------------------------------------
# CBU
# --------------------------------------------------------------------------
def cbu_check_digit(block: str) -> str:
    """Digito verificador de un bloque de CBU.

    Los ponderadores 3,1,7,9 se aplican de forma ciclica sobre el bloque
    leido de derecha a izquierda.
    """
    total = sum(int(n) * CBU_WEIGHTS[i % 4] for i, n in enumerate(reversed(block)))
    return str((10 - total % 10) % 10)


def build_cbu(bank: str, branch: str, account: str) -> str:
    """Arma un CBU de 22 digitos: banco(3) sucursal(4) DV1 cuenta(13) DV2."""
    bank = bank.zfill(3)
    branch = branch.zfill(4)
    account = account.zfill(13)

    block1 = f"{bank}{branch}"
    block2 = account

    return f"{block1}{cbu_check_digit(block1)}{block2}{cbu_check_digit(block2)}"


def validate_cbu(cbu: str) -> bool:
    if len(cbu) != 22 or not cbu.isdigit():
        return False
    return cbu_check_digit(cbu[:7]) == cbu[7] and cbu_check_digit(cbu[8:21]) == cbu[21]


# --------------------------------------------------------------------------
# PAN (numero de tarjeta)
# --------------------------------------------------------------------------
def luhn_check_digit(partial: str) -> str:
    """Digito de control de Luhn para un PAN sin su ultimo digito."""
    total = 0
    for i, ch in enumerate(reversed(partial)):
        digit = int(ch)
        # El primer digito a duplicar es el de la posicion 0 desde la derecha,
        # porque todavia falta agregar el verificador.
        if i % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)


def build_pan(bin_code: str, account_part: str) -> str:
    """Arma un PAN de 16 digitos valido segun Luhn."""
    bin_code = bin_code.zfill(6)[:6]
    account_part = account_part.zfill(9)[:9]
    partial = f"{bin_code}{account_part}"
    return f"{partial}{luhn_check_digit(partial)}"


def validate_pan(pan: str) -> bool:
    if not pan.isdigit() or len(pan) < 13:
        return False
    return luhn_check_digit(pan[:-1]) == pan[-1]
