"""Verifica que pares X/USDC de OKX cumplen los criterios del informe seccion 4.1.

SOLO endpoints publicos. Sin claves, sin cuenta, sin ordenes.

Criterios (informe seccion 4.1):
  * el par X/USDC existe y esta activo,
  * spread medio < 0,05 %,
  * profundidad hasta 0,5 % > 20x el tamanyo de la orden.

Ademas comprueba lo que el informe seccion 1.6 avisa y es facil olvidar:
  * el minimo por orden (minSz x precio) frente a la posicion objetivo,
  * si una salida parcial del 50 % quedaria por debajo de ese minimo (polvo),
  * la correlacion a 7 d entre las finalistas (regla 15): 8 monedas muy
    correlacionadas no son 8 apuestas, son una.

AVISO SOBRE LA MEDICION: un muestreo corto en un momento concreto sirve para
descartar, no para confirmar. Con --minutes 60 o mas, y a ser posible repetido
en sesion asiatica, europea y americana, el numero ya es defendible.

Uso:
    python scripts/verify_okx_pairs.py --quick
    python scripts/verify_okx_pairs.py --minutes 60
    python scripts/verify_okx_pairs.py --minutes 60 --json var/verify.json

Medicion larga, whitelist contra USDC y contra USD, muestra a muestra:
    python scripts/verify_okx_pairs.py --symbols BTC ETH SOL XRP DOGE AVAX TRX NEAR         --also-quote USD --minutes 720 --interval 30 --no-correlation         --csv var/spread/muestras.csv

`--also-quote USD` existe por la pregunta abierta de CLAUDE.md: `X-USD` y
`X-USDC` son libros SEPARADOS y, con una sola muestra, BTC-USD salio 140 veces
mas estrecho. Los pares que no son USDC se miden pero NUNCA entran en la
propuesta de whitelist: la regla 3 dice `X/USDC`, y cambiarla es cosa del propietario.

`--csv` escribe cada muestra con su hora EN EL MOMENTO, no al final: si la
maquina se duerme o el proceso muere a las 6 horas, esas 6 horas no se pierden.
Y con la hora se puede separar por sesion (Asia, Europa, America).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt.pro as ccxtpro  # noqa: E402

from core.clock import utcnow  # noqa: E402

# Criterios del informe seccion 4.1.
MAX_SPREAD_PCT = 0.05
DEPTH_MULTIPLE = 20

# Candidatas del PRD mas el banco de sustitutos que ya medimos el 22/09/2026.
DEFAULT_CANDIDATES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX"]
DEFAULT_SUBSTITUTES = [
    "TRX", "NEAR", "LTC", "DOT", "BCH", "UNI", "ATOM",
    "SUI", "XLM", "HBAR", "AAVE", "ARB", "OP", "FIL", "ETC", "POL",
]


@dataclass
class PairSample:
    symbol: str
    spreads: list[float] = field(default_factory=list)
    depth_bid: list[float] = field(default_factory=list)
    depth_ask: list[float] = field(default_factory=list)
    mids: list[float] = field(default_factory=list)
    errors: int = 0

    @property
    def n(self) -> int:
        return len(self.spreads)

    def summary(self, order_usd: float) -> dict[str, Any] | None:
        if not self.spreads:
            return None
        spread_avg = statistics.fmean(self.spreads)
        spread_p95 = (
            statistics.quantiles(self.spreads, n=20)[-1]
            if len(self.spreads) >= 20
            else max(self.spreads)
        )
        depth_avg = statistics.fmean(
            [min(b, a) for b, a in zip(self.depth_bid, self.depth_ask)]
        )
        depth_min = min(
            [min(b, a) for b, a in zip(self.depth_bid, self.depth_ask)]
        )
        required = DEPTH_MULTIPLE * order_usd
        fails = []
        if spread_avg >= MAX_SPREAD_PCT:
            fails.append("spread")
        if depth_min <= required:
            fails.append("profundidad")
        return {
            "symbol": self.symbol,
            "samples": self.n,
            "errors": self.errors,
            "spread_avg_pct": spread_avg,
            "spread_p95_pct": spread_p95,
            "spread_max_pct": max(self.spreads),
            "depth_avg_usd": depth_avg,
            "depth_min_usd": depth_min,
            "depth_x_order": depth_min / order_usd if order_usd else 0.0,
            "price": statistics.fmean(self.mids),
            "passes": not fails,
            "fails": fails,
        }


def measure_book(book: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bids = [(float(p), float(q)) for p, q, *_ in book.get("bids", [])]
    asks = [(float(p), float(q)) for p, q, *_ in book.get("asks", [])]
    if not bids or not asks:
        return None
    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
        return None
    mid = (best_bid + best_ask) / 2
    spread = (best_ask - best_bid) / mid * 100
    depth_bid = sum(p * q for p, q in bids if p >= mid * 0.995)
    depth_ask = sum(p * q for p, q in asks if p <= mid * 1.005)
    return spread, depth_bid, depth_ask, mid


async def sample_books(
    client: ccxtpro.okx,
    symbols: list[str],
    samples: int,
    interval: float,
    csv_path: Path | None = None,
) -> dict[str, PairSample]:
    out = {s: PairSample(symbol=s) for s in symbols}
    fichero = None
    escritor = None
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not csv_path.exists()
        fichero = csv_path.open("a", newline="", encoding="utf-8")
        escritor = csv.writer(fichero)
        if nuevo:
            escritor.writerow(
                ["ts_utc", "symbol", "spread_pct", "depth_bid_usd", "depth_ask_usd", "mid"]
            )
    try:
        for i in range(samples):
            for symbol in symbols:
                try:
                    book = await client.fetch_order_book(symbol, 400)
                except Exception:
                    out[symbol].errors += 1
                    continue
                measured = measure_book(book)
                if measured is None:
                    out[symbol].errors += 1
                    continue
                spread, dbid, dask, mid = measured
                if escritor is not None:
                    escritor.writerow(
                        [utcnow().isoformat(timespec="seconds"), symbol,
                         f"{spread:.6f}", f"{dbid:.2f}", f"{dask:.2f}", f"{mid:.8g}"]
                    )
                sample = out[symbol]
                sample.spreads.append(spread)
                sample.depth_bid.append(dbid)
                sample.depth_ask.append(dask)
                sample.mids.append(mid)
            if fichero is not None:
                fichero.flush()
            if i < samples - 1:
                await asyncio.sleep(interval)
    finally:
        if fichero is not None:
            fichero.close()
    return out


async def correlation_matrix(
    client: ccxtpro.okx, symbols: list[str], days: int = 7
) -> dict[str, dict[str, float]]:
    """Correlacion de rendimientos horarios a `days` dias (regla 15)."""
    import numpy as np

    closes: dict[str, np.ndarray] = {}
    limit = min(days * 24, 300)
    for symbol in symbols:
        try:
            rows = await client.fetch_ohlcv(symbol, "1h", None, limit)
        except Exception:
            continue
        if len(rows) >= 24:
            closes[symbol] = np.array([float(r[4]) for r in rows])
        await asyncio.sleep(client.rateLimit / 1000)

    if len(closes) < 2:
        return {}

    size = min(len(v) for v in closes.values())
    returns = {
        symbol: np.diff(np.log(values[-size:])) for symbol, values in closes.items()
    }
    names = sorted(returns)
    matrix: dict[str, dict[str, float]] = {}
    for a in names:
        matrix[a] = {}
        for b in names:
            matrix[a][b] = float(np.corrcoef(returns[a], returns[b])[0, 1])
    return matrix


async def run(args: argparse.Namespace) -> int:
    client = ccxtpro.okx(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
            # OKX devuelve 403 sin User-Agent reconocible (comprobado 22/09/2026).
            "headers": {"User-Agent": "ploutos-verify/0.1"},
        }
    )
    result: dict[str, Any] = {"generated_at": utcnow().isoformat()}

    try:
        await client.load_markets()

        usdc = sorted(
            m["symbol"]
            for m in client.markets.values()
            if m.get("quote") == "USDC" and m.get("spot") and m.get("active")
        )
        print(f"Pares X/USDC activos en OKX: {len(usdc)}")
        print()
        print("AVISO: los endpoints publicos devuelven el catalogo GLOBAL de OKX.")
        print("       Que la entidad europea permita operar estos pares solo se")
        print("       confirma desde tu propia cuenta (fase 0).")
        print()

        bases = args.symbols or (DEFAULT_CANDIDATES + DEFAULT_SUBSTITUTES)
        wanted = [f"{b}/USDC" for b in bases]
        for quote in args.also_quote:
            wanted += [f"{b}/{quote}" for b in bases]
        available = [s for s in wanted if s in client.markets]
        missing = [s for s in wanted if s not in client.markets]
        if missing:
            print(f"No existen en OKX: {', '.join(missing)}")
            print()

        samples = 6 if args.quick else max(2, int(args.minutes * 60 / args.interval))
        eta = samples * args.interval * len(available) / 60
        print(
            f"Muestreando {len(available)} pares, {samples} muestras cada "
            f"{args.interval:g} s (~{eta:.0f} min)..."
        )
        measured = await sample_books(
            client, available, samples, args.interval,
            Path(args.csv) if args.csv else None,
        )

        # --- tabla de criterios ---
        print()
        header = (
            f"{'par':<12}{'n':>5}{'spread med%':>13}{'p95%':>9}{'max%':>9}"
            f"{'prof.min $':>13}{'x orden':>10}  veredicto"
        )
        print(header)
        print("-" * (len(header) + 12))

        summaries: list[dict[str, Any]] = []
        for symbol in available:
            summary = measured[symbol].summary(args.order_usd)
            if summary is None:
                print(f"{symbol:<12}{'sin datos':>5}")
                continue
            summaries.append(summary)
            verdict = "PASA" if summary["passes"] else f"FALLA ({','.join(summary['fails'])})"
            print(
                f"{symbol:<12}{summary['samples']:>5}"
                f"{summary['spread_avg_pct']:>13.4f}{summary['spread_p95_pct']:>9.4f}"
                f"{summary['spread_max_pct']:>9.4f}{summary['depth_min_usd']:>13,.0f}"
                f"{summary['depth_x_order']:>10,.0f}  {verdict}"
            )
        result["pairs"] = summaries

        # --- minimos por orden y polvo (informe seccion 1.6 y 2.5) ---
        print()
        print("Minimo por orden y riesgo de polvo "
              f"(posicion objetivo {args.order_usd:g} $):")
        header2 = (
            f"{'par':<12}{'minSz':>14}{'precio':>12}{'min orden $':>13}"
            f"{'pos completa':>14}{'salida 50%':>12}"
        )
        print(header2)
        print("-" * len(header2))
        minimums: list[dict[str, Any]] = []
        for summary in summaries:
            market = client.markets[summary["symbol"]]
            min_sz = float(market["info"].get("minSz", 0) or 0)
            price = summary["price"]
            min_cost = min_sz * price
            row = {
                "symbol": summary["symbol"],
                "min_size": min_sz,
                "price": price,
                "min_notional_usd": min_cost,
                "full_exit_ok": args.order_usd >= min_cost,
                "half_exit_ok": args.order_usd / 2 >= min_cost,
            }
            minimums.append(row)
            print(
                f"{summary['symbol']:<12}{min_sz:>14g}{price:>12.4f}{min_cost:>13.2f}"
                f"{'si' if row['full_exit_ok'] else 'NO':>14}"
                f"{'si' if row['half_exit_ok'] else 'NO':>12}"
            )
        result["minimums"] = minimums

        dusty = [r["symbol"] for r in minimums if r["full_exit_ok"] and not r["half_exit_ok"]]
        if dusty:
            print()
            print(f"  AVISO: {', '.join(dusty)} no admite salidas parciales del 50 % "
                  f"con {args.order_usd:g} $.")
            print("         Cerrar la mitad dejaria un resto no vendible (polvo).")

        # --- propuesta de whitelist ---
        # Solo USDC: los pares de --also-quote se miden, no se proponen (regla 3).
        passing = [
            s for s in summaries if s["passes"] and s["symbol"].endswith("/USDC")
        ]
        passing.sort(key=lambda s: s["spread_avg_pct"])
        print()
        print("Pares que PASAN los criterios, por spread (mejor primero):")
        for i, summary in enumerate(passing, 1):
            mark = " <- top 8" if i == 8 else ""
            print(f"  {i:>2}. {summary['symbol']:<12} "
                  f"spread {summary['spread_avg_pct']:.4f} %{mark}")

        proposal = [s["symbol"] for s in passing[:8]]
        result["proposal"] = proposal

        # --- correlacion (regla 15) ---
        if proposal and not args.no_correlation:
            print()
            print("Correlacion de rendimientos horarios a 7 d entre las finalistas")
            print("(regla 15: como mucho 2 posiciones con correlacion > 0,8):")
            matrix = await correlation_matrix(client, proposal, args.correlation_days)
            result["correlation"] = matrix
            if matrix:
                names = sorted(matrix)
                print()
                print("        " + "".join(f"{n.split('/')[0]:>7}" for n in names))
                for a in names:
                    cells = "".join(f"{matrix[a][b]:>7.2f}" for b in names)
                    print(f"{a.split('/')[0]:>7} {cells}")
                high = [
                    (a, b, matrix[a][b])
                    for i, a in enumerate(names)
                    for b in names[i + 1:]
                    if matrix[a][b] > 0.8
                ]
                print()
                if high:
                    print(f"  {len(high)} pares con correlacion > 0,8:")
                    for a, b, value in sorted(high, key=lambda x: -x[2]):
                        print(f"    {a.split('/')[0]}-{b.split('/')[0]}: {value:.2f}")
                    print("  La regla 15 limitara a 2 posiciones simultaneas entre ellos.")
                else:
                    print("  Ninguna pareja supera 0,8. La cesta esta bien diversificada.")

        # --- propuesta final ---
        print()
        print("=" * 72)
        print("Propuesta para config/settings.yaml:")
        print()
        print("whitelist:")
        for symbol in proposal:
            print(f"  - {symbol}")
        if len(proposal) < 8:
            print()
            print(f"  AVISO: solo {len(proposal)} pares pasan. La regla 3 exige 8.")
            print("         Amplia el banco con --symbols o relaja el criterio a mano.")
        print("=" * 72)
        print()
        print(f"Medicion: {samples} muestras/par cada {args.interval:g} s.")
        if args.quick or samples < 60:
            print("AVISO: muestreo corto. Sirve para descartar, no para confirmar.")
            print("       Para fijar la whitelist, usa --minutes 60 o mas, repetido")
            print("       en distintas franjas horarias.")

        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"\nJSON guardado en {path}")

        return 0 if len(proposal) >= 8 else 1
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verifica pares X/USDC de OKX (solo endpoints publicos)"
    )
    parser.add_argument("--minutes", type=float, default=60.0,
                        help="duracion del muestreo (por defecto 60)")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="segundos entre muestras (por defecto 10)")
    parser.add_argument("--quick", action="store_true",
                        help="6 muestras rapidas; solo para descartar")
    parser.add_argument("--order-usd", type=float, default=15.0,
                        help="tamanyo de orden de referencia (por defecto 15)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="bases a medir (por defecto, candidatas + sustitutos)")
    parser.add_argument("--correlation-days", type=int, default=7)
    parser.add_argument("--no-correlation", action="store_true")
    parser.add_argument("--json", default=None, help="guardar el resultado en JSON")
    parser.add_argument("--also-quote", nargs="*", default=[],
                        help="medir tambien X/<quote> para las mismas bases (p. ej. USD)")
    parser.add_argument("--csv", default=None,
                        help="escribir cada muestra con su hora, segun se toma")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
