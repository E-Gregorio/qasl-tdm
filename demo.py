"""Recorrido narrado del ciclo de vida de QASL-TDM.

Un solo comando que ejecuta el ciclo completo y va explicando que pasa en
cada paso. Es la forma mas rapida de entender que hace un TDM.

Requiere la API levantada en otra terminal:

    uvicorn app.main:app --reload

Y despues, en esta terminal:

    python demo.py
"""

from __future__ import annotations

import sys

import httpx

from sdk.client import PoolExhausted, QaslTdmClient, QaslTdmError

API = "http://127.0.0.1:8000"
ESCENARIO = "transferencia_exitosa"

ANCHO = 74


def titulo(numero: str, texto: str) -> None:
    print()
    print("=" * ANCHO)
    print(f"  {numero}  {texto}")
    print("=" * ANCHO)


def explica(texto: str) -> None:
    print()
    for linea in texto.strip().split("\n"):
        print(f"  | {linea.strip()}")
    print()


def accion(texto: str) -> None:
    print(f"  >> {texto}")


def dato(registro: dict, campos: tuple[str, ...]) -> None:
    for campo in campos:
        print(f"       {campo:<16} {registro.get(campo)}")


def tabla_stats(stats: dict) -> None:
    print(f"       {'ESCENARIO':<26}{'DISP':>6}{'RESERV':>8}{'DIRTY':>7}")
    print(f"       {'-' * 47}")
    for s in stats["scenarios"]:
        print(
            f"       {s['scenario']:<26}{s['available']:>6}"
            f"{s['reserved']:>8}{s['dirty']:>7}"
        )


def pausa() -> None:
    try:
        input("\n  [Enter para continuar]")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


def verificar_api(tdm: QaslTdmClient) -> None:
    try:
        salud = tdm.health()
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print()
        print("  No se pudo conectar con la API.")
        print()
        print("  Abri OTRA terminal, parate en la carpeta del proyecto,")
        print("  activa el venv y ejecuta:")
        print()
        print("      uvicorn app.main:app --reload")
        print()
        print("  Dejala abierta y volve a correr: python demo.py")
        print()
        raise SystemExit(1)

    print(f"  API conectada. Motor: {salud['engine']}")


def main() -> int:
    worker_1 = QaslTdmClient(API, worker_id="worker-1")
    worker_2 = QaslTdmClient(API, worker_id="worker-2")

    print()
    print("=" * ANCHO)
    print("  QASL-TDM  —  recorrido del ciclo de vida")
    print("=" * ANCHO)
    verificar_api(worker_1)

    # ------------------------------------------------------------------
    titulo("1/9", "ESTADO INICIAL DEL POOL")
    explica(
        """
        El pool es el inventario de datos de prueba. Cada escenario tiene
        registros en cuatro estados posibles:

          AVAILABLE  listo para entregar a un test
          RESERVED   tomado por una ejecucion, con vencimiento
          DIRTY      usado y modificado, necesita RESET
          RETIRED    fuera de servicio

        Esto es lo que mira quien opera la suite todas las mananas.
        """
    )
    accion("GET /tdm/pool/stats")
    tabla_stats(worker_1.stats())
    pausa()

    # ------------------------------------------------------------------
    titulo("2/9", "SEED — crear datos de prueba")
    explica(
        """
        Aca es donde NACEN los datos. Es la mitad batch del ciclo: corre en
        un job, por lotes, y ningun test la espera.

        No se le pasan valores. Se le pasa el NOMBRE DE UN ESCENARIO, y el
        generador arma registros que cumplen esa condicion de negocio
        (definida en app/services/generator_service.py).

        Los identificadores salen con su digito verificador correcto, y se
        enmascaran antes de guardarse.
        """
    )
    accion(f"POST /tdm/pool/seed  -->  escenario '{ESCENARIO}', 3 registros")
    nuevos = worker_1.seed(ESCENARIO, count=3, seed=2026)
    print()
    print("       Uno de los tres que se acaban de crear:")
    dato(nuevos[0], ("id", "nombre", "dni", "cuit", "cuenta", "saldo", "status", "is_masked"))
    explica(
        """
        Fijate: saldo por encima de 100.000 y estado ACTIVA, porque eso es
        lo que define el escenario 'transferencia_exitosa'. Y is_masked=True:
        el nombre y el DNI que ves NO son los que genero el generador, son
        los enmascarados. El original nunca toco la base.
        """
    )
    pausa()

    # ------------------------------------------------------------------
    titulo("3/9", "RESERVE — un test pide un dato")
    explica(
        """
        Aca empieza la mitad de runtime. Responde en milisegundos a cada test.

        OJO: esto NO crea nada. Busca el primer registro AVAILABLE del
        escenario y lo marca como tomado. Es un SELECT + un UPDATE.

        El test no sabe que cliente le van a dar, y no le importa. Pide una
        condicion de negocio y recibe un dato que la cumple.
        """
    )
    accion(f"POST /tdm/reserve  -->  escenario '{ESCENARIO}', reserved_by 'worker-1'")
    reservado_1 = worker_1.reserve(ESCENARIO, ttl_seconds=300)
    print()
    dato(reservado_1, ("id", "cuenta", "saldo", "status", "reserved_by", "expires_at"))
    pausa()

    # ------------------------------------------------------------------
    titulo("4/9", "CONCURRENCIA — otro test pide al mismo tiempo")
    explica(
        """
        Esta es LA razon de existir del proyecto.

        Sin reserva, dos tests en paralelo agarran el mismo cliente, los dos
        le cambian el saldo, y los dos fallan por motivos que nadie entiende.
        Eso es la causa mas comun de flakiness en una suite bancaria.

        worker-2 pide el mismo escenario. Mira que recibe.
        """
    )
    accion(f"POST /tdm/reserve  -->  mismo escenario, reserved_by 'worker-2'")
    reservado_2 = worker_2.reserve(ESCENARIO, ttl_seconds=300)
    print()
    print(f"       worker-1 tiene:  {reservado_1['id']}")
    print(f"       worker-2 tiene:  {reservado_2['id']}")
    print()
    print(f"       Son distintos:   {reservado_1['id'] != reservado_2['id']}")
    explica(
        """
        Lo garantiza un UPDATE condicional: 'marcalo como reservado SOLO si
        sigue disponible'. El que llega segundo actualiza cero filas y
        reintenta con otro registro.
        """
    )
    pausa()

    # ------------------------------------------------------------------
    titulo("5/9", "LA RESERVA TIENE DUENO")
    explica(
        """
        worker-2 intenta liberar el dato de worker-1. Puede pasar por un
        teardown mal escrito o por una limpieza que borra de mas.
        """
    )
    accion(f"POST /tdm/release  -->  worker-2 intenta liberar {reservado_1['id']}")
    try:
        worker_2.release(reservado_1["id"], "CLEAN")
        print("\n       Se libero. Esto NO deberia pasar.")
    except QaslTdmError as exc:
        print(f"\n       RECHAZADO: {exc}")
    pausa()

    # ------------------------------------------------------------------
    titulo("6/9", "RELEASE — el test termina y devuelve el dato")
    explica(
        """
        Hay dos formas de devolverlo:

          CLEAN  el test no modifico el dato   -->  vuelve a AVAILABLE
          DIRTY  el test lo modifico           -->  queda fuera hasta el RESET

        worker-2 devuelve el suyo limpio. worker-1 devuelve el suyo sucio,
        como si el test le hubiera hecho una transferencia y cambiado el saldo.
        """
    )
    accion(f"POST /tdm/release  -->  worker-2 devuelve {reservado_2['id']} como CLEAN")
    limpio = worker_2.release(reservado_2["id"], "CLEAN")
    print(f"       status: {limpio['status']}")

    accion(f"POST /tdm/release  -->  worker-1 devuelve {reservado_1['id']} como DIRTY")
    sucio = worker_1.release(reservado_1["id"], "DIRTY")
    print(f"       status: {sucio['status']}")
    explica(
        """
        Por que DIRTY no vuelve solo al pool: si el test modifico el dato y
        lo devolvemos sin revisar, el proximo test lo recibe en un estado
        que no espera. Asi se pudren los ambientes de QA.
        """
    )
    pausa()

    # ------------------------------------------------------------------
    titulo("7/9", "RESET — recuperar el dato sucio")
    explica(
        """
        RESET restaura la CONDICION DE NEGOCIO (saldo, estado de cuenta,
        dias de mora) y devuelve el registro al pool.

        No toca la IDENTIDAD: DNI, CUIT, CBU y tarjeta siguen siendo los
        mismos. Si cambiaran, un test que guardo el CBU para verificar
        despues dejaria de encontrarlo.
        """
    )
    accion(f"POST /tdm/reset/{reservado_1['id']}")
    reseteado = worker_1.reset(reservado_1["id"])
    print()
    print(f"       {'CAMPO':<9}{'ANTES':<24}{'DESPUES':<24}")
    print(f"       {'-' * 60}")
    for campo, antes, despues in (
        ("cuenta", reservado_1["cuenta"], reseteado["cuenta"]),
        ("dni", reservado_1["dni"], reseteado["dni"]),
        ("cuit", reservado_1["cuit"], reseteado["cuit"]),
        ("saldo", reservado_1["saldo"], reseteado["saldo"]),
        ("status", sucio["status"], reseteado["status"]),
    ):
        marca = "CAMBIO" if str(antes) != str(despues) else "igual"
        print(f"       {campo:<9}{str(antes):<24}{str(despues):<24}{marca}")
    print()
    print("       Identidad igual, condicion de negocio nueva, vuelve al pool.")
    pausa()

    # ------------------------------------------------------------------
    titulo("8/9", "AUDITORIA — quien toco el dato y cuando")
    explica(
        """
        Cada transicion queda registrada sola. Esto es lo que exige el punto
        9.2.2 de la Comunicacion 'A' 7724 del BCRA: documentar el diseno,
        creacion y preparacion de los datos de prueba.

        No es un documento que alguien escribe. Es la traza que deja el
        sistema.
        """
    )
    accion(f"GET /tdm/records/{reservado_1['id']}/audit")
    print()
    print(f"       {'CUANDO':<28}{'ACCION':<10}{'QUIEN':<12}")
    print(f"       {'-' * 50}")
    for entrada in reversed(worker_1.audit(reservado_1["id"])):
        cuando = entrada["created_at"].replace("T", " ")[:19]
        print(f"       {cuando:<28}{entrada['action']:<10}{entrada['actor']:<12}")
    pausa()

    # ------------------------------------------------------------------
    titulo("9/9", "EXPORT — datos de volumen para JMeter")
    explica(
        """
        Las pruebas de carga funcionan distinto: necesitan volumen PRECARGADO
        en un CSV. Pedir un registro por iteracion convertiria al TDM en el
        cuello de botella de la propia prueba.

        Con reserve_for, los registros exportados quedan reservados para esa
        corrida. Asi la segunda corrida recibe datos distintos y no reusa los
        que ya se consumieron — el error clasico que hace que la segunda
        pasada de una prueba de carga de falsos negativos.
        """
    )
    accion("GET /tdm/pool/export  -->  limit 5, reserve_for 'carga-001'")
    csv_1 = worker_1.export_csv(ESCENARIO, limit=5, reserve_for="carga-001")
    ids_1 = [linea.split(",")[0] for linea in csv_1.strip().split("\n")[1:]]

    accion("GET /tdm/pool/export  -->  limit 5, reserve_for 'carga-002'")
    csv_2 = worker_1.export_csv(ESCENARIO, limit=5, reserve_for="carga-002")
    ids_2 = [linea.split(",")[0] for linea in csv_2.strip().split("\n")[1:]]

    print()
    print(f"       carga-001 se llevo:  {len(ids_1)} registros")
    print(f"       carga-002 se llevo:  {len(ids_2)} registros")
    print(f"       Se superponen:       {not set(ids_1).isdisjoint(ids_2)}")
    print()
    print("       Cabecera del CSV que consume JMeter con CSV Data Set Config:")
    print(f"       {csv_1.split(chr(10))[0]}")
    pausa()

    # ------------------------------------------------------------------
    titulo("FIN", "ESTADO FINAL DEL POOL")
    accion("GET /tdm/pool/stats")
    tabla_stats(worker_1.stats())
    explica(
        f"""
        Para devolver todo a AVAILABLE y reponer el pool:

            python cli.py refresh --min 50

        Eso es lo que corre un job nocturno: expira las reservas vencidas,
        limpia los DIRTY y genera los que falten.
        """
    )

    worker_1.close()
    worker_2.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PoolExhausted as exc:
        print(f"\n  Pool agotado: {exc}")
        print("  Ejecuta:  python cli.py refresh --min 50\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Interrumpido.\n")
        sys.exit(0)
