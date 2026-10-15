"""Mide el criterio de avance de la fase 1: 72 h sin huecos.

Este script es el juez. No es una opinion ni una impresion: mira la base de
datos, cuenta las velas que deberian estar y las que estan, y devuelve un
codigo de salida.

    exit 0 -> criterio CUMPLIDO
    exit 1 -> hay huecos sin rellenar
    exit 2 -> no hay suficiente historia todavia

Uso:
    python scripts/check_gaps.py
    python scripts/check_gaps.py --hours 72 --timeframe 1m
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.clock import from_ms, timeframe_ms, utcnow_ms  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from data.coverage import coverage as cobertura  # noqa: E402
from data.store.db import open_database  # noqa: E402
from data.store.repos import CandleRepo, GapRepo  # noqa: E402

# LAS VELAS ESPERADAS SALEN DEL RELOJ, NO DE LAS PRESENTES (22/09/2026). La
# version anterior buscaba huecos solo entre dos velas guardadas y contaba las
# esperadas de la primera a la ultima presente: si la ingesta moria a la hora
# 60, a la 72 decia "CRITERIO CUMPLIDO" con cobertura del 100 %. Ver
# `data/coverage.py` y `tests/unit/test_check_gaps.py`.


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Criterio de avance de la fase 1: 72 h sin huecos"
    )
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument(
        "--timeframe",
        default=None,
        help="solo este timeframe (por defecto, todos los ingeridos)",
    )
    parser.add_argument(
        "--db", default=None,
        help="otra base (p. ej. una copia restaurada); por defecto la de la configuracion",
    )
    parser.add_argument(
        "--until", default=None,
        help="juzgar como si fuera este instante (AAAA-MM-DDTHH:MM, UTC). Para una "
             "copia restaurada: si no, lo que paso desde que se hizo cuenta como hueco",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"configuracion invalida: {exc}", file=sys.stderr)
        return 2

    db = open_database(args.db or settings.storage.db_path, run_migrations=False)
    candles = CandleRepo(db)
    gaps_repo = GapRepo(db)

    window_ms = int(args.hours * 3600 * 1000)
    now = utcnow_ms()
    if args.until:
        from datetime import UTC, datetime

        now = int(datetime.fromisoformat(args.until).replace(tzinfo=UTC).timestamp() * 1000)
    since = now - window_ms
    timeframes = (
        [args.timeframe] if args.timeframe else list(settings.data.timeframes)
    )

    print(f"Ventana: ultimas {args.hours:g} h  ({from_ms(since):%Y-%m-%d %H:%M} -> "
          f"{from_ms(now):%Y-%m-%d %H:%M} UTC)")
    print()
    header = (
        f"{'par':<11}{'tf':>5}{'esperadas':>11}{'presentes':>11}"
        f"{'huecos':>8}{'faltan':>8}{'cobertura':>11}"
    )
    print(header)
    print("-" * len(header))

    total_missing = 0
    total_expected = 0
    total_gaps = 0
    insufficient: list[str] = []

    for symbol in settings.whitelist:
        for timeframe in timeframes:
            step = timeframe_ms(timeframe)
            stamps = [r["ts_open_ms"] for r in candles.range(symbol, timeframe, since, now)]
            cov = cobertura(stamps, since, now, step)

            # Historia suficiente = la ingesta ya existia al empezar la ventana.
            # Se mira la vela MAS ANTIGUA que haya, dentro o fuera de la ventana:
            # si es posterior al inicio, lo que falta al principio no es un
            # hueco, es que todavia no han pasado las horas.
            primera = db.query(
                "SELECT MIN(ts_open_ms) AS t FROM candles WHERE symbol = ?"
                " AND timeframe = ? AND closed = 1",
                (symbol, timeframe),
            )[0]["t"]
            if primera is None or cov.first_expected_ms is None or primera > cov.first_expected_ms:
                insufficient.append(f"{symbol} {timeframe}")
                print(f"{symbol:<11}{timeframe:>5}{cov.expected:>11}{cov.present:>11}"
                      f"{'-':>8}{'-':>8}{'sin historia':>11}")
                continue

            total_expected += cov.expected
            total_missing += cov.missing
            total_gaps += len(cov.holes)

            flag = "" if cov.missing == 0 else "  <-- HUECOS"
            if cov.holes and cov.holes[-1].last_ms == cov.last_expected_ms:
                flag += " (falta el FINAL: la ingesta esta parada?)"
            print(
                f"{symbol:<11}{timeframe:>5}{cov.expected:>11}{cov.present:>11}"
                f"{len(cov.holes):>8}{cov.missing:>8}{cov.pct:>10.3f}%{flag}"
            )

    print()
    unfilled = gaps_repo.unfilled(since_ms=since)
    coverage = (
        (total_expected - total_missing) / total_expected * 100
        if total_expected
        else 0.0
    )
    print(f"TOTAL: {total_expected} velas esperadas, {total_missing} faltan, "
          f"{total_gaps} huecos -> cobertura {coverage:.4f} %")
    print(f"Huecos registrados sin rellenar: {len(unfilled)}")

    db.close()
    print()

    if insufficient:
        print(f"RESULTADO: todavia no hay {args.hours:g} h de historia completa.")
        print("           Deja corriendo `python scripts/run_ingest.py` y vuelve a mirar.")
        return 2
    if total_missing or unfilled:
        print("RESULTADO: CRITERIO NO CUMPLIDO. Hay huecos sin rellenar.")
        return 1

    print(f"RESULTADO: CRITERIO CUMPLIDO. {args.hours:g} h sin huecos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
