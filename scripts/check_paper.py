"""Mide el criterio de avance AMPLIADO de la fase 2: 72 h de papel coherente.

Hermano de `check_gaps.py`, y con la misma idea: esto es el juez, no una
opinion. Lee la base de papel y las velas reales, lo recalcula todo por su
cuenta (ver la cabecera de `portfolio/audit.py`) y devuelve un codigo de
salida.

    exit 0 -> criterio CUMPLIDO: >= 72 h, al menos una orden, todo coherente
    exit 1 -> hay incoherencias (se dice cuales)
    exit 2 -> todo coherente, pero aun no hay evidencia suficiente
              (menos de 72 h, o ninguna orden en todo el periodo)

Solo LEE, de las dos bases: se puede lanzar en el VPS con el bucle en marcha.

    .venv/bin/python scripts/check_paper.py
    .venv/bin/python scripts/check_paper.py --hours 72 --tf 4h
    .venv/bin/python scripts/check_paper.py --decider ai --paper-db var/<la de la IA>.db

`--decider` dice de quien es la cartera: la del baseline no puede tener ni una
llamada a Claude; la de la IA se audita ademas contra el journal del analista.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.clock import from_ms, timeframe_ms  # noqa: E402
from core.config import load_settings  # noqa: E402
from data.news import store as noticias_db  # noqa: E402
from features.news import bases_de, flags  # noqa: E402
from notify import control  # noqa: E402
from portfolio.audit import MAX_EJEMPLOS, NO_LLAMO, Audit, PaperRecord  # noqa: E402
from portfolio.paper import Bar  # noqa: E402
from risk.types import Instrument  # noqa: E402


def solo_lectura(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"no existe {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _flags_de_noticias(ruta: Path, settings):
    """Las flags de la base de noticias, o None si no existe (sin noticias no hay nada que exigir)."""
    conn = noticias_db.solo_lectura(ruta)
    if conn is None:
        return None
    try:
        return flags(noticias_db.anuncios(conn), bases_de(settings.whitelist),
                     levantadas=noticias_db.levantadas(conn))
    finally:
        conn.close()


def _comandos(ruta: Path):
    """Los comandos de Telegram, o None si no hay base de control (nadie ha mandado nada)."""
    conn = control.solo_lectura(ruta)
    if conn is None:
        return None
    try:
        return control.comandos(conn)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Criterio ampliado de la fase 2")
    parser.add_argument("--tf", default="4h")
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--slider", type=int, default=3)
    parser.add_argument("--main-db", default=str(REPO / "var" / "ploutos.db"))
    parser.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper.db"))
    parser.add_argument("--decider", choices=("baseline", "ai"), default="baseline",
                        help="de quien es la cartera (fase 3: la IA tiene la suya)")
    parser.add_argument("--news-db", default=str(REPO / "var" / "ploutos-news.db"),
                        help="la base de ploutos-news: con ella se juzgan las ventas y cancelaciones por noticia")
    parser.add_argument("--control-db", default=str(REPO / "var" / "ploutos-control.db"),
                        help="la base de ploutos-telegram: con ella se juzgan la pausa y la parada")
    args = parser.parse_args()

    settings = load_settings()
    paso = timeframe_ms(args.tf)

    paper = solo_lectura(Path(args.paper_db))
    record = PaperRecord.from_db(paper, args.tf)
    if not record.equity:
        print("El bucle de papel no ha procesado ninguna vela todavia.")
        return 2

    main_db = solo_lectura(Path(args.main_db))
    instruments = {
        r["symbol"]: Instrument.from_row(r)
        # Las mismas comisiones que usa el bucle: las de settings.yaml.
        for r in settings.exchange.fees.apply(
            [dict(x) for x in main_db.execute("SELECT * FROM instruments")]
        )
    }
    desde = int(record.equity[0]["ts_ms"]) - 4 * paso
    bars: dict[str, list[Bar]] = {}
    for symbol in settings.whitelist:
        filas = main_db.execute(
            "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? AND closed = 1"
            " AND ts_open_ms >= ? AND ts_open_ms <= ? ORDER BY ts_open_ms",
            (symbol, args.tf, desde, record.cursor),
        ).fetchall()
        bars[symbol] = [Bar.from_row(dict(f)) for f in filas]

    audit = Audit(
        record=record, bars=bars, instruments=instruments, settings=settings,
        timeframe_ms=paso, slider_level=args.slider,
        starting_usd=settings.capital.initial_capital_usd, decider=args.decider,
        noticias=_flags_de_noticias(Path(args.news_db), settings),
        comandos=_comandos(Path(args.control_db)),
    )
    checks = audit.run()

    primera = int(record.equity[0]["ts_ms"])
    velas = len(record.equity)
    horas = velas * paso / 3_600_000
    print(f"Bucle de papel ({args.tf}): {velas} velas procesadas, "
          f"{from_ms(primera):%Y-%m-%d %H:%M} -> {from_ms(record.cursor):%Y-%m-%d %H:%M} UTC "
          f"(~{horas:.0f} h)")
    print(f"  ordenes {len(record.orders)}, operaciones cerradas {len(record.trades)}, "
          f"posiciones abiertas {len(record.positions)}")
    if args.decider == "ai":
        hechas = sum(1 for x in record.ai_calls if x["outcome"] not in NO_LLAMO)
        print(f"  cartera de la IA: {len(record.ai_calls)} filas del journal del analista, "
              f"{hechas} llamadas hechas")
    print()

    ancho = max(len(c.nombre) for c in checks)
    for c in checks:
        estado = "OK   " if c.ok else "FALLA"
        extra = f", {c.sin_datos} SIN DATOS" if c.sin_datos else ""
        print(f"  {estado} {c.nombre:<{ancho}}  [{c.regla}]  ({c.comprobados} comprobados{extra})")
        for texto in c.fallos[:MAX_EJEMPLOS]:
            print(f"          - {texto}")
        if len(c.fallos) > MAX_EJEMPLOS:
            print(f"          ... y {len(c.fallos) - MAX_EJEMPLOS} mas")
        for nota in c.notas:
            print(f"          OJO: {nota}")

    print()
    sin = sum(c.sin_datos for c in checks)
    if sin:
        print(f"  {sin} casos SIN DATOS: ordenes anteriores a que se guardara el contexto")
        print("  de mercado (22/09/2026). No son fallos, pero tampoco estan comprobados.")
    print()

    if any(not c.ok for c in checks):
        print("RESULTADO: hay incoherencias. El criterio NO se cumple.")
        return 1
    if horas < args.hours:
        print(f"RESULTADO: coherente, pero solo ~{horas:.0f} h de {args.hours:g}. Aun no.")
        return 2
    if not record.orders:
        print("RESULTADO: coherente, pero SIN NINGUNA ORDEN en todo el periodo.")
        print("Un bucle que no opera no demuestra que opere bien.")
        return 2
    print(f"RESULTADO: criterio CUMPLIDO ({horas:.0f} h, {len(record.orders)} ordenes, "
          f"todo coherente).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
