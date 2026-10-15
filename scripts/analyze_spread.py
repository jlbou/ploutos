"""Analiza la medicion larga de spread (`verify_okx_pairs.py --csv`).

Contesta las dos preguntas abiertas de CLAUDE.md:

1. **SOL aguanta?** Entro en la whitelist con un spread medio del 0,048 % en una
   muestra corta, frente al 0,05 % del informe seccion 4.1.
2. **X/USD contra X/USDC.** Con una sola muestra, BTC-USD salio 140 veces mas
   estrecho que BTC-USDC. Si se mantiene, podria compensar; si no, se cierra.

Separa por franja horaria (UTC), porque un spread que pasa de media puede no
pasar en la franja asiatica, y el bot opera las 24 h:

    asia     00-08    europa   08-13    america  13-21    cierre   21-24

    python scripts/analyze_spread.py var/spread/muestras-20260922.csv

Solo lee el CSV. No decide nada: la whitelist (regla 3) la cambia el propietario.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Informe seccion 4.1: criterio de entrada en la whitelist.
MAX_SPREAD_MEDIO_PCT = 0.05
# Regla 16: con el spread por encima de esto no se entra.
MAX_SPREAD_ENTRADA_PCT = 0.10
# Profundidad minima: 20x una orden de 15 $ (informe seccion 4.1).
MIN_PROFUNDIDAD_USD = 20 * 15.0

FRANJAS = (("asia", 0, 8), ("europa", 8, 13), ("america", 13, 21), ("cierre", 21, 24))


@dataclass(frozen=True, slots=True)
class Muestra:
    ts: datetime
    symbol: str
    spread_pct: float
    depth_usd: float     # el lado mas flojo
    ronda: int           # a que pasada del medidor pertenece


def franja(ts: datetime) -> str:
    for nombre, desde, hasta in FRANJAS:
        if desde <= ts.hour < hasta:
            return nombre
    raise ValueError(ts)


def leer(path: Path) -> list[Muestra]:
    """Lee el CSV y numera las rondas.

    El medidor escribe los pares SIEMPRE en el mismo orden, una ronda cada 30 s.
    Una ronda nueva empieza cada vez que reaparece el primer par del fichero.
    No se agrupa por minuto: caben dos rondas por minuto, y se emparejaria el
    USDC de una con el USD de la otra.
    """
    out = []
    primero: str | None = None
    ronda = 0
    with path.open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if primero is None:
                primero = fila["symbol"]
            elif fila["symbol"] == primero:
                ronda += 1
            out.append(Muestra(
                ts=datetime.fromisoformat(fila["ts_utc"]),
                symbol=fila["symbol"],
                spread_pct=float(fila["spread_pct"]),
                depth_usd=min(float(fila["depth_bid_usd"]), float(fila["depth_ask_usd"])),
                ronda=ronda,
            ))
    return out


@dataclass(frozen=True, slots=True)
class Resumen:
    n: int
    medio: float
    mediana: float
    p95: float
    sobre_entrada_pct: float     # % de muestras con spread > 0,10 % (regla 16)
    profundidad_min: float


def resumir(muestras: list[Muestra]) -> Resumen:
    spreads = sorted(m.spread_pct for m in muestras)
    p95 = spreads[min(len(spreads) - 1, int(0.95 * len(spreads)))]
    return Resumen(
        n=len(spreads),
        medio=statistics.fmean(spreads),
        mediana=statistics.median(spreads),
        p95=p95,
        sobre_entrada_pct=100 * sum(s > MAX_SPREAD_ENTRADA_PCT for s in spreads) / len(spreads),
        profundidad_min=min(m.depth_usd for m in muestras),
    )


def por_simbolo_y_franja(muestras: list[Muestra]) -> dict[str, dict[str, Resumen]]:
    grupos: dict[str, dict[str, list[Muestra]]] = defaultdict(lambda: defaultdict(list))
    for m in muestras:
        grupos[m.symbol]["total"].append(m)
        grupos[m.symbol][franja(m.ts)].append(m)
    return {s: {f: resumir(ms) for f, ms in g.items()} for s, g in grupos.items()}


def emparejar(muestras: list[Muestra], base: str) -> list[tuple[float, float]]:
    """(spread USDC, spread USD) de la MISMA ronda, para comparar sin sesgo.

    Misma ronda = medidos con segundos de diferencia (ver `leer`).
    """
    usdc, usd = {}, {}
    for m in muestras:
        clave = m.ronda
        if m.symbol == f"{base}/USDC":
            usdc[clave] = m.spread_pct
        elif m.symbol == f"{base}/USD":
            usd[clave] = m.spread_pct
    return [(usdc[k], usd[k]) for k in sorted(usdc.keys() & usd.keys())]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("var/spread/muestras-20260922.csv")
    muestras = leer(path)
    if not muestras:
        print("CSV vacio")
        return 1
    horas = (max(m.ts for m in muestras) - min(m.ts for m in muestras)).total_seconds() / 3600
    print(f"{path.name}: {len(muestras)} muestras, {horas:.1f} h, "
          f"{min(m.ts for m in muestras):%d/%m %H:%M} -> {max(m.ts for m in muestras):%d/%m %H:%M} UTC")
    tabla = por_simbolo_y_franja(muestras)

    # --- 1. la whitelist contra USDC, por franja ---
    print()
    print(f"Spread medio (%) contra USDC, por franja. Criterio del informe: < {MAX_SPREAD_MEDIO_PCT} %")
    nombres = [f for f, _a, _b in FRANJAS]
    print(f"  {'par':<11}{'total':>8}" + "".join(f"{f:>9}" for f in nombres)
          + f"{'p95':>8}{'>0,10%':>8}{'prof.min $':>12}  veredicto")
    usdc = sorted(s for s in tabla if s.endswith("/USDC"))
    for s in usdc:
        t = tabla[s]
        celdas = "".join(f"{t[f].medio:>9.4f}" if f in t else f"{'-':>9}" for f in nombres)
        peor = max(t[f].medio for f in nombres if f in t)
        falla = []
        if t["total"].medio >= MAX_SPREAD_MEDIO_PCT:
            falla.append("media")
        elif peor >= MAX_SPREAD_MEDIO_PCT:
            falla.append("en alguna franja")
        if t["total"].profundidad_min < MIN_PROFUNDIDAD_USD:
            falla.append("profundidad")
        veredicto = "PASA" if not falla else "FALLA: " + ", ".join(falla)
        print(f"  {s:<11}{t['total'].medio:>8.4f}{celdas}{t['total'].p95:>8.4f}"
              f"{t['total'].sobre_entrada_pct:>7.1f}%{t['total'].profundidad_min:>12,.0f}  {veredicto}")

    # --- 2. USD contra USDC, emparejado ---
    print()
    print("USD contra USDC, en la MISMA ronda (spread medio % y cuantas veces gana USD)")
    print(f"  {'base':<6}{'rondas':>8}{'USDC':>9}{'USD':>9}{'USD/USDC':>10}{'gana USD':>10}")
    for s in usdc:
        base = s.split("/")[0]
        pares = emparejar(muestras, base)
        if not pares:
            continue
        m_usdc = statistics.fmean(a for a, _b in pares)
        m_usd = statistics.fmean(b for _a, b in pares)
        gana = 100 * sum(b < a for a, b in pares) / len(pares)
        print(f"  {base:<6}{len(pares):>8}{m_usdc:>9.4f}{m_usd:>9.4f}"
              f"{m_usd / m_usdc if m_usdc else float('nan'):>10.2f}{gana:>9.0f}%")

    print()
    print("Esto no cambia nada por si solo: la whitelist y la quote son la regla 3,")
    print("y la regla 3 la cambia el propietario. Ademas, que es 'USD' en OKX sigue sin saberse")
    print("(CLAUDE.md, pregunta abierta sobre la quote).")
    if horas < 20:
        print(f"\nAVISO: solo {horas:.1f} h. La medicion esta pensada para 24 h, todas las franjas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
