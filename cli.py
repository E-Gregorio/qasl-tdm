"""CLI de operacion de QASL-TDM.

Es la mitad batch del ciclo: lo que corre un job nocturno o un step de
pipeline, no lo que llama un test.

    python cli.py seed transferencia_exitosa --count 500
    python cli.py stats
    python cli.py refresh --min 50
    python cli.py export transferencia_exitosa --limit 10000 --out carga.csv
    python cli.py expire
"""

from __future__ import annotations

import argparse
import sys

from app.database import Base, SessionLocal, engine
from app.models import db as _models  # noqa: F401  (registra las tablas)
from app.services.generator_service import SCENARIOS, UnknownScenarioError
from app.services.pool_service import PoolService
from app.services.reservation_service import ReservationService

pool_service = PoolService()
reservation_service = ReservationService()


def cmd_init(_args: argparse.Namespace) -> int:
    Base.metadata.create_all(bind=engine)
    print("Esquema creado.")
    return 0


def cmd_scenarios(_args: argparse.Namespace) -> int:
    for spec in sorted(SCENARIOS.values(), key=lambda s: s.name):
        print(f"  {spec.name:<26} {spec.description}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            registros = pool_service.seed(db, args.scenario, args.count, args.seed)
        except UnknownScenarioError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    print(f"Generados {len(registros)} registros de '{args.scenario}'.")
    return 0


def cmd_seed_all(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        for scenario in SCENARIOS:
            pool_service.seed(db, scenario, args.count, args.seed)
            print(f"  {scenario:<26} +{args.count}")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        stats = pool_service.stats(db)

    if not stats.scenarios:
        print("El pool esta vacio. Ejecuta: python cli.py seed-all --count 50")
        return 0

    print(f"{'ESCENARIO':<26}{'DISP':>7}{'RESERV':>8}{'DIRTY':>7}{'TOTAL':>7}")
    print("-" * 55)
    for s in stats.scenarios:
        print(f"{s.scenario:<26}{s.available:>7}{s.reserved:>8}{s.dirty:>7}{s.total:>7}")
    print("-" * 55)
    print(f"{'TOTAL':<26}{'':>7}{'':>8}{'':>7}{stats.total:>7}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        resultado = pool_service.refresh(db, args.min)

    print(
        f"Expirados: {resultado.expired} | "
        f"Reseteados: {resultado.reset} | "
        f"Generados: {resultado.generated}"
    )
    return 0


def cmd_expire(_args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        print(f"Reservas vencidas liberadas: {reservation_service.expire_stale(db)}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        contenido = pool_service.export_csv(db, args.scenario, args.limit, args.reserve_for)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as handle:
            handle.write(contenido)
        filas = len(contenido.strip().split("\n")) - 1
        print(f"Exportadas {filas} filas a {args.out}")
    else:
        print(contenido, end="")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qasl-tdm", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Crea el esquema").set_defaults(func=cmd_init)
    sub.add_parser("scenarios", help="Lista los escenarios").set_defaults(func=cmd_scenarios)
    sub.add_parser("stats", help="Estado del pool").set_defaults(func=cmd_stats)
    sub.add_parser("expire", help="Libera reservas vencidas").set_defaults(func=cmd_expire)

    p_seed = sub.add_parser("seed", help="Genera datos de un escenario")
    p_seed.add_argument("scenario")
    p_seed.add_argument("--count", type=int, default=50)
    p_seed.add_argument("--seed", type=int, default=None, help="Semilla reproducible")
    p_seed.set_defaults(func=cmd_seed)

    p_all = sub.add_parser("seed-all", help="Genera datos de todos los escenarios")
    p_all.add_argument("--count", type=int, default=50)
    p_all.add_argument("--seed", type=int, default=None)
    p_all.set_defaults(func=cmd_seed_all)

    p_refresh = sub.add_parser("refresh", help="Expira, limpia y repone el pool")
    p_refresh.add_argument("--min", type=int, default=None, help="Minimo por escenario")
    p_refresh.set_defaults(func=cmd_refresh)

    p_export = sub.add_parser("export", help="Exporta CSV para JMeter")
    p_export.add_argument("scenario")
    p_export.add_argument("--limit", type=int, default=1000)
    p_export.add_argument("--out", default=None, help="Archivo destino")
    p_export.add_argument(
        "--reserve-for",
        dest="reserve_for",
        default=None,
        help="Reserva los registros exportados para esa corrida de carga",
    )
    p_export.set_defaults(func=cmd_export)

    return parser


def main() -> int:
    Base.metadata.create_all(bind=engine)
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
