"""Recorrido historico del bucle completo, sin IA.

    generador de candidatos -> baseline -> motor de riesgo -> papel

Es el arnes del criterio de avance ampliado de la fase 2 ("baseline sin IA
generando operaciones de papel coherentes") y el que en la fase 6 servira para
comparar contra la IA: mismo recorrido, mismos candidatos, mismo motor, mismo
simulador, y solo cambia quien elige.

    python scripts/replay_baseline.py
    python scripts/replay_baseline.py --tf 4h --equity 50 --slider 3
    python scripts/replay_baseline.py --trades       # lista las operaciones

NO MIRA EL FUTURO EN NINGUN PASO. En cada vela solo se pasan las velas
cerradas hasta ese instante, y una orden creada con el cierre de la vela T no
puede llenarse hasta la T+1. Si algun dia estos numeros salen demasiado
bonitos, el primer sitio donde mirar es aqui.

Exit 0 siempre: esto mide, no juzga. El criterio de 72 h lo cierra el propietario mirando
si las operaciones tienen sentido, no un umbral automatico.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import load_settings  # noqa: E402
from portfolio.loop import TradingLoop  # noqa: E402
from portfolio.paper import Bar, PaperBroker, PaperLedger  # noqa: E402
from risk.types import Instrument  # noqa: E402
from strategy.costs import CostModel  # noqa: E402
from strategy.pipeline import MarketData  # noqa: E402

# Velas minimas antes de empezar a decidir: el percentil del regimen necesita
# 60 valores NO nulos del ATR, y el ATR se come 42 velas de calentamiento.
WARMUP_BARS = 110


def main() -> int:
    parser = argparse.ArgumentParser(description="Recorrido del baseline sin IA")
    parser.add_argument("--tf", default="4h")
    parser.add_argument("--equity", type=float, default=50.0)
    parser.add_argument("--slider", type=int, default=3)
    parser.add_argument("--db", default=str(REPO / "var" / "ploutos.db"))
    parser.add_argument("--trades", action="store_true", help="lista las operaciones")
    parser.add_argument(
        "--since",
        help=(
            "AAAA-MM-DD: empezar a DECIDIR desde esta fecha. La historia "
            "anterior se sigue usando para el calentamiento, asi que sirve "
            "para comparar dos timeframes sobre la MISMA ventana."
        ),
    )
    args = parser.parse_args()

    settings = load_settings()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Comisiones de settings.yaml, no las de ccxt (decision del propietario, 23/09/2026).
    rows = settings.exchange.fees.apply([dict(r) for r in db.execute("SELECT * FROM instruments")])
    instruments = {r["symbol"]: Instrument.from_row(r) for r in rows}
    cost = CostModel.from_repo(
        type("R", (), {"all": lambda self: rows})(),
        now_ms=max(r["fetched_ms"] for r in rows),
    )
    # Profundidad y spread: solo hay medidas del libro RECIENTES, porque
    # `book_metrics` empezo a llenarse con la fase 1. Para el recorrido
    # historico se aplica la medida actual a todo el periodo. Es una
    # aproximacion y hay que saberlo: si el spread de hace un mes era peor,
    # este recorrido lo pinta mas barato de lo que fue. La profundidad
    # importa menos porque nunca ata (medido: 41.000-1.330.000 $ contra los
    # 300 $ que exige el filtro).
    spreads = {}
    depths = {}
    for symbol in settings.whitelist:
        row = db.execute(
            "SELECT spread_pct, depth_bid_05pct, depth_ask_05pct "
            "FROM book_metrics WHERE symbol = ? ORDER BY ts_ms DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        spreads[symbol] = float(row["spread_pct"]) if row else 0.05
        depths[symbol] = (
            min(float(row["depth_bid_05pct"]), float(row["depth_ask_05pct"]))
            if row
            else 0.0
        )

    candles: dict[str, pd.DataFrame] = {}
    for symbol in settings.whitelist:
        candles[symbol] = pd.DataFrame(
            [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? "
                    "AND closed = 1 ORDER BY ts_open_ms",
                    (symbol, args.tf),
                )
            ]
        )

    # Series de 1 h para las correlaciones de la regla 15 (ventana de 7 dias).
    hourly: dict[str, pd.Series] = {}
    for symbol in settings.whitelist:
        rows_h = [
            dict(r)
            for r in db.execute(
                "SELECT ts_open_ms, close FROM candles WHERE symbol = ? "
                "AND timeframe = ? AND closed = 1 ORDER BY ts_open_ms",
                (symbol, "1h"),
            )
        ]
        if rows_h:
            frame = pd.DataFrame(rows_h)
            hourly[symbol] = frame.set_index("ts_open_ms")["close"]

    stamps = sorted({int(t) for df in candles.values() for t in df["ts_open_ms"]})

    # `--since` recorta donde EMPIEZAN las decisiones, no donde empieza la
    # historia: las velas anteriores se siguen pasando para el calentamiento.
    # Sin esto, comparar 4 h contra 1 h es comparar 32 dias contra 8.
    desde = WARMUP_BARS
    if args.since:
        corte = int(
            datetime.strptime(args.since, "%Y-%m-%d")
            .replace(tzinfo=UTC)
            .timestamp()
            * 1000
        )
        candidatos = [i for i, t in enumerate(stamps) if t >= corte]
        if not candidatos:
            print(f"no hay velas de {args.tf} a partir de {args.since}")
            return 0
        desde = max(WARMUP_BARS, candidatos[0])

    if len(stamps) <= desde:
        print(f"Solo hay {len(stamps)} velas de {args.tf} utiles; hacen falta "
              f"mas de {desde} para que el clasificador de regimen arranque.")
        return 0

    broker = PaperBroker(instruments)
    ledger = PaperLedger(starting_usd=args.equity, broker=broker)

    # EL MISMO BUCLE QUE USA EL VIVO. No es una comodidad: si el historico y el
    # vivo tuvieran cada uno su copia de los pasos, se separarian con el tiempo
    # y las 72 h en vivo estarian midiendo algo distinto de lo que se midio
    # aqui, sin que nadie se entere.
    loop = TradingLoop(
        instruments=instruments,
        cost=cost,
        settings=settings,
        broker=broker,
        ledger=ledger,
        timeframe=args.tf,
        slider_level=args.slider,
    )

    submitted = vetoed = 0
    veto_counts: dict[int, int] = {}
    filter_counts: dict[str, int] = {}

    print(f"Recorrido del baseline sin IA ({args.tf}, {args.equity:.0f} $, "
          f"slider {args.slider})")
    print("=" * 74)
    print("SUPOSICION: USDC en paridad todo el periodo (no hay historia de su precio;")
    print("            la regla 17 no se ejercita en este recorrido).")

    for stamp in stamps[desde:]:
        market: dict[str, MarketData] = {}
        bars: dict[str, Bar] = {}
        for symbol, df in candles.items():
            history = df[df["ts_open_ms"] <= stamp]
            if len(history) < WARMUP_BARS:
                continue
            if int(history["ts_open_ms"].iloc[-1]) == stamp:
                bars[symbol] = Bar.from_row(history.iloc[-1].to_dict())
            market[symbol] = MarketData(
                symbol=symbol,
                candles=history,
                spread_pct=spreads[symbol],
                depth_usd=depths[symbol],
            )
        if not market:
            continue

        ventana = {s: serie[serie.index <= stamp] for s, serie in hourly.items()}
        # SUPOSICION: USDC en paridad. No hay historia de su precio, y con
        # `None` (desconocida) la regla 17 vetaria todo el recorrido. Se dice
        # en la cabecera del informe para que nadie lo tome por medido.
        result = loop.step(stamp, market, bars, ventana, usdc_deviation_pct=0.0)

        submitted += len(result.submitted)
        vetoed += len(result.vetoed)
        for _c, numeros, _motivo in result.vetoed:
            for n in numeros:
                veto_counts[n] = veto_counts.get(n, 0) + 1
        if result.pipeline:
            for cribada in result.pipeline.filtered_out:
                for r in cribada.rejections:
                    filter_counts[r.name] = filter_counts.get(r.name, 0) + 1

    # --- informe ---
    inicio = datetime.fromtimestamp(stamps[desde] / 1000, tz=UTC)
    fin = datetime.fromtimestamp(stamps[-1] / 1000, tz=UTC)
    dias = (fin - inicio) / timedelta(days=1)
    print(f"Periodo: {inicio:%Y-%m-%d} a {fin:%Y-%m-%d} ({dias:.0f} dias, "
          f"{len(stamps) - desde} velas)")
    print()
    print(f"  ordenes enviadas   {submitted}")
    print(f"  candidatos vetados {vetoed}")
    if veto_counts:
        detalle = ", ".join(
            f"regla {n}: {c}" for n, c in sorted(veto_counts.items(), key=lambda x: -x[1])
        )
        print(f"    {detalle}")
    expiradas = sum(1 for o in broker.orders if str(o.state) == "expired")
    print(f"  ordenes caducadas  {expiradas} (el precio no volvio al limite)")
    if filter_counts:
        detalle = ", ".join(
            f"{n}: {c}"
            for n, c in sorted(filter_counts.items(), key=lambda x: -x[1])
        )
        print(f"  cribado por filtros  {detalle}")
    print()

    stats = broker.stats()
    if stats["trades"] == 0:
        print("  No se cerro ninguna operacion.")
        return 0

    print(f"  operaciones        {stats['trades']}  "
          f"({stats['trades'] / dias:.2f}/dia)")
    print(f"  aciertos           {stats['win_rate_pct']:.0f} %  "
          f"({stats['targets']} objetivos, {stats['stops']} stops)")
    print(f"  expectativa        {stats['expectancy_r']:+.3f} R por operacion")
    print(f"  P&L neto           {stats['net_pnl_usd']:+.3f} $")
    print(f"  P&L bruto          {stats['gross_pnl_usd']:+.3f} $")
    print(f"  comisiones         {stats['fees_usd']:.3f} $  "
          f"({stats['fees_usd'] / abs(stats['gross_pnl_usd']) * 100:.0f} % del bruto)"
          if stats["gross_pnl_usd"] else f"  comisiones {stats['fees_usd']:.3f} $")
    if "profit_factor" in stats:
        print(f"  profit factor      {stats['profit_factor']:.2f}")
    print(f"  MAE / MFE medios   {stats['mae_pct_medio']:+.2f} % / "
          f"{stats['mfe_pct_medio']:+.2f} %")
    print(f"  salidas maker      {stats['maker_exit_pct']:.0f} %")
    print(f"  drawdown maximo    {ledger.max_drawdown_pct():.2f} %")
    final = ledger.history[-1][1] if ledger.history else args.equity
    print(f"  equity             {args.equity:.2f} $ -> {final:.2f} $")

    # --- LA COMPARACION QUE IMPIDE ENGANYARSE (informe 1.9, metrica 7) ---
    #
    # Un sistema SOLO LARGO en un mercado alcista gana dinero por definicion.
    # Sin estas dos lineas, un "+19,6 %" parece una ventaja cuando puede ser la
    # marea subiendo. No es una comparacion perfecta (el bot no esta invertido
    # todo el rato y arriesga mucho menos), pero es la que evita el autoengano,
    # y por eso el informe la pide SIEMPRE.
    print()
    print("  Contra no hacer nada:")
    retorno = (final / args.equity - 1) * 100
    print(f"    baseline            {retorno:+.1f} %")

    cambios = []
    for symbol, df in candles.items():
        tramo = df[df["ts_open_ms"] >= stamps[desde]]
        if len(tramo) < 2:
            continue
        cambio = (tramo["close"].iloc[-1] / tramo["close"].iloc[0] - 1) * 100
        cambios.append(cambio)
        if symbol == "BTC/USDC":
            print(f"    comprar y esperar BTC   {cambio:+.1f} %")
    if cambios:
        cesta = sum(cambios) / len(cambios)
        print(f"    comprar y esperar las {len(cambios)}  {cesta:+.1f} %")
        if retorno < cesta:
            print()
            print(f"    OJO: el baseline rinde MENOS que no hacer nada "
                  f"({retorno:+.1f} % contra {cesta:+.1f} %).")
            print("    En un tramo alcista eso es lo normal en un sistema solo")
            print("    largo con 3 huecos: lo que mide no es la estrategia, es")
            print("    el mercado. La prueba de verdad es un tramo lateral o")
            print("    bajista, y estos datos no lo tienen.")

    por_setup: dict[str, list] = {}
    for t in broker.trades:
        por_setup.setdefault(t.setup, []).append(t)
    print()
    print(f"  {'setup':<17}{'op.':>5}{'aciertos':>10}{'expectativa':>13}{'neto':>10}")
    for setup, ts in sorted(por_setup.items()):
        wins = sum(1 for t in ts if t.net_pnl_usd > 0)
        exp = sum(t.r_multiple for t in ts) / len(ts)
        print(f"  {setup:<17}{len(ts):>5}{wins / len(ts) * 100:>9.0f} %"
              f"{exp:>+13.3f}{sum(t.net_pnl_usd for t in ts):>+10.3f}")

    if args.trades:
        print()
        print("  Operaciones:")
        for t in broker.trades:
            abierto = datetime.fromtimestamp(t.opened_ts_ms / 1000, tz=UTC)
            print(f"   {abierto:%m-%d %H:%M}  {t}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
