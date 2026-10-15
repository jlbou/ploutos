"""El spread de la whitelist, medido con semanas: para decidir DOGE y NEAR antes de la fase 7.

CLAUDE.md (decision del propietario del 23/09): DOGE y NEAR se quedan por ahora y se decide ANTES de la fase 7,
"con semanas", porque en dos ventanas de un dia salieron al reves (DOGE 0,054 % y luego 0,046 %; NEAR
0,0501 % y luego 0,0525 %) y la linea del 0,05 % (informe 4.1) los parte por la mitad.

La ingesta guarda el libro de cada moneda cada ~10 s en `book_metrics` (desde el 22/09). Esto lo resume
por moneda:

- media, mediana y p95; y la media por franja horaria (UTC), laborables contra fin de semana y cuantos
  dias pasaron del 0,05 %: un spread que pasa de media puede no pasar en la franja asiatica o en domingo;
- % del tiempo por encima del 0,05 % (el criterio de la whitelist) y del 0,10 % (la regla 16);
- **lo que de verdad cuesta**: en cuantos cierres de vela de 4 h (cuando el bucle decide) el spread
  pasaba del 0,10 % y la regla 16 habria bloqueado la entrada;
- la profundidad del lado mas flojo hasta el 0,5 % (el informe pide 20 veces una orden de 15 $).

Solo LEE la base principal (`mode=ro`): se puede lanzar en el VPS con la ingesta en marcha. No decide
nada: la whitelist es la regla 3 y la cambia el propietario (y con ella, la clave de OKX).

    .venv/bin/python scripts/estudio_spread.py
    .venv/bin/python scripts/estudio_spread.py --desde 2026-09-25 --hasta 2026-10-09
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MAX_SPREAD_MEDIO_PCT = 0.05       # informe 4.1: criterio para entrar en la whitelist
MAX_SPREAD_ENTRADA_PCT = 0.10     # regla 16
MIN_PROFUNDIDAD_USD = 20 * 15.0   # informe 4.1: 20 veces una orden de 15 $
FRANJAS = (("asia", 0, 8), ("europa", 8, 13), ("america", 13, 21), ("cierre", 21, 24))
VELA_MS = 4 * 3600_000
MARGEN_CIERRE_MS = 2 * 60_000     # la muestra que vale para un cierre: la primera en los 2 min siguientes
DIAS_MINIMOS = 14                 # dos semanas: dos fines de semana y todas las franjas varias veces


@dataclass(frozen=True, slots=True)
class Muestra:
    ts_ms: int
    spread_pct: float
    profundidad_usd: float       # el lado mas flojo, hasta el 0,5 %


def franja(ts_ms: int) -> str:
    hora = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).hour
    return next(n for n, desde, hasta in FRANJAS if desde <= hora < hasta)


def es_fin_de_semana(ts_ms: int) -> bool:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).weekday() >= 5


def dia(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def percentil(xs: Sequence[float], p: float) -> float:
    orden = sorted(xs)
    return orden[max(0, min(len(orden), math.ceil(p / 100 * len(orden))) - 1)]


def en_los_cierres(muestras: Sequence[Muestra]) -> list[float]:
    """El spread en cada cierre de vela de 4 h: la primera muestra en los 2 min siguientes al cierre.
    Es el que ve el bucle al decidir (la regla 16 solo cuenta ahi). Muestras en orden."""
    out: list[float] = []
    ultimo = None
    for m in muestras:
        cierre = (m.ts_ms // VELA_MS) * VELA_MS
        if m.ts_ms - cierre < MARGEN_CIERRE_MS and cierre != ultimo:
            out.append(m.spread_pct)
            ultimo = cierre
    return out


@dataclass(frozen=True, slots=True)
class Resumen:
    n: int
    medio: float
    mediana: float
    p95: float
    por_franja: dict[str, float]
    laborable: float | None
    fin_de_semana: float | None
    dias: int
    dias_sobre: int                  # dias con la media por encima del 0,05 %
    sobre_medio_pct: float           # % de muestras > 0,05 %
    sobre_entrada_pct: float         # % de muestras > 0,10 %
    cierres: int
    cierres_bloqueados: int          # cierres de vela con spread > 0,10 %
    profundidad_p5: float
    profundidad_min: float

    @property
    def veredicto(self) -> str:
        fallos = []
        if self.medio >= MAX_SPREAD_MEDIO_PCT:
            fallos.append("media")
        elif max(self.por_franja.values()) >= MAX_SPREAD_MEDIO_PCT:
            fallos.append("en alguna franja")
        if self.fin_de_semana is not None and self.fin_de_semana >= MAX_SPREAD_MEDIO_PCT \
                and "media" not in fallos:
            fallos.append("en fin de semana")
        if self.profundidad_p5 < MIN_PROFUNDIDAD_USD:
            fallos.append("profundidad")
        return "PASA" if not fallos else "FALLA: " + ", ".join(fallos)


def resumir(muestras: Sequence[Muestra]) -> Resumen:
    """`muestras` de UNA moneda, en orden."""
    spreads = [m.spread_pct for m in muestras]
    grupos: dict[str, list[float]] = defaultdict(list)
    por_dia: dict[str, list[float]] = defaultdict(list)
    for m in muestras:
        grupos[franja(m.ts_ms)].append(m.spread_pct)
        grupos["finde" if es_fin_de_semana(m.ts_ms) else "laborable"].append(m.spread_pct)
        por_dia[dia(m.ts_ms)].append(m.spread_pct)
    cierres = en_los_cierres(muestras)
    profundidades = [m.profundidad_usd for m in muestras]

    def media(k: str) -> float | None:
        return statistics.fmean(grupos[k]) if grupos.get(k) else None

    return Resumen(
        n=len(spreads), medio=statistics.fmean(spreads), mediana=statistics.median(spreads),
        p95=percentil(spreads, 95),
        por_franja={n: statistics.fmean(grupos[n]) for n, _d, _h in FRANJAS if grupos.get(n)},
        laborable=media("laborable"), fin_de_semana=media("finde"),
        dias=len(por_dia), dias_sobre=sum(statistics.fmean(v) >= MAX_SPREAD_MEDIO_PCT for v in por_dia.values()),
        sobre_medio_pct=100 * sum(s > MAX_SPREAD_MEDIO_PCT for s in spreads) / len(spreads),
        sobre_entrada_pct=100 * sum(s > MAX_SPREAD_ENTRADA_PCT for s in spreads) / len(spreads),
        cierres=len(cierres), cierres_bloqueados=sum(s > MAX_SPREAD_ENTRADA_PCT for s in cierres),
        profundidad_p5=percentil(profundidades, 5), profundidad_min=min(profundidades),
    )


def leer(conn: sqlite3.Connection, desde_ms: int, hasta_ms: int) -> dict[str, list[Muestra]]:
    out: dict[str, list[Muestra]] = defaultdict(list)
    for simbolo, ts, spread, bid, ask in conn.execute(
            "SELECT symbol, ts_ms, spread_pct, depth_bid_05pct, depth_ask_05pct FROM book_metrics"
            " WHERE ts_ms >= ? AND ts_ms < ? ORDER BY symbol, ts_ms", (desde_ms, hasta_ms)):
        out[simbolo].append(Muestra(ts, spread, min(bid, ask)))
    return out


def informe(tabla: dict[str, Resumen], desde_ms: int, hasta_ms: int, whitelist: Iterable[str]) -> list[str]:
    fmt = "%d/%m %H:%M"
    dias = (hasta_ms - desde_ms) / 86_400_000
    lineas = [f"book_metrics: {datetime.fromtimestamp(desde_ms / 1000, tz=UTC):{fmt}} -> "
              f"{datetime.fromtimestamp(hasta_ms / 1000, tz=UTC):{fmt}} UTC ({dias:.1f} dias)", ""]
    nombres = [n for n, _d, _h in FRANJAS]
    lineas.append(f"Spread medio (%). Whitelist: < {MAX_SPREAD_MEDIO_PCT} % de media y en cada franja (informe 4.1)")
    lineas.append(f"  {'par':<11}{'media':>7}{'mediana':>8}{'p95':>7}" + "".join(f"{n:>8}" for n in nombres)
                  + f"{'labor.':>8}{'finde':>7}{'dias>':>7}  veredicto")
    for s in sorted(tabla):
        r = tabla[s]
        franjas = "".join(f"{r.por_franja[n]:>8.4f}" if n in r.por_franja else f"{'-':>8}" for n in nombres)
        lab = f"{r.laborable:>8.4f}" if r.laborable is not None else f"{'-':>8}"
        fin = f"{r.fin_de_semana:>7.4f}" if r.fin_de_semana is not None else f"{'-':>7}"
        lineas.append(f"  {s:<11}{r.medio:>7.4f}{r.mediana:>8.4f}{r.p95:>7.4f}{franjas}{lab}{fin}"
                      f"{f'{r.dias_sobre}/{r.dias}':>7}  {r.veredicto}")
    lineas += ["", "Lo que cuesta: tiempo por encima de cada linea y entradas que la regla 16 bloquea al decidir",
               f"  {'par':<11}{'>0,05 %':>9}{'>0,10 %':>9}{'cierres bloqueados':>20}{'prof. p5 $':>12}{'min $':>9}"]
    for s in sorted(tabla):
        r = tabla[s]
        bloq = f"{r.cierres_bloqueados}/{r.cierres}"
        lineas.append(f"  {s:<11}{r.sobre_medio_pct:>8.1f}%{r.sobre_entrada_pct:>8.1f}%{bloq:>20}"
                      f"{r.profundidad_p5:>12,.0f}{r.profundidad_min:>9,.0f}")
    faltan = sorted(set(whitelist) - set(tabla))
    if faltan:
        lineas += ["", f"AVISO: sin muestras de {', '.join(faltan)}"]
    if dias < DIAS_MINIMOS:
        lineas += ["", f"AVISO: solo {dias:.1f} dias. Para decidir, al menos {DIAS_MINIMOS} (dos fines de semana)."]
    lineas += ["", "Esto no decide nada: la whitelist es la regla 3 y la cambia el propietario (y con ella, la clave de OKX)."]
    return lineas


def _ms(texto: str) -> int:
    return int(datetime.fromisoformat(texto).replace(tzinfo=UTC).timestamp() * 1000)


def main() -> int:
    sys.path.insert(0, str(REPO))
    from core.config import load_settings

    ap = argparse.ArgumentParser(description="El spread de la whitelist, medido con semanas")
    ap.add_argument("--db", default=str(REPO / "var" / "ploutos.db"))
    ap.add_argument("--desde", help="AAAA-MM-DD[THH:MM], UTC (por defecto, la primera muestra)")
    ap.add_argument("--hasta", help="AAAA-MM-DD[THH:MM], UTC (por defecto, la ultima)")
    args = ap.parse_args()

    ruta = Path(args.db)
    if not ruta.exists():
        raise SystemExit(f"no existe {ruta}")
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
    try:
        lo, hi = conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM book_metrics").fetchone()
        if lo is None:
            print("book_metrics esta vacia")
            return 1
        desde = _ms(args.desde) if args.desde else lo
        hasta = _ms(args.hasta) if args.hasta else hi + 1
        muestras = leer(conn, desde, hasta)
    finally:
        conn.close()
    whitelist = load_settings().whitelist
    tabla = {s: resumir(ms) for s, ms in muestras.items() if s in whitelist and ms}
    print("\n".join(informe(tabla, desde, min(hasta, hi + 1), whitelist)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
