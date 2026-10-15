"""Metricas del paso 2: rendimiento anual, caida, Sharpe (diario, como pide ml4t-deflated-sharpe), probabilistico,
deflactado (Bailey y Lopez de Prado), tipos de mercado con el cierre de AYER (C4) y PBO por validacion combinatoria."""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import combinations
from statistics import NormalDist

from sim import indicadores as ind

N = NormalDist()
EULER = 0.5772156649


def anual(curva: Sequence[float]) -> float:
    dias = len(curva) - 1
    return (curva[-1] / curva[0]) ** (365 / dias) - 1 if dias > 0 and curva[0] > 0 else 0.0


def caida_maxima(curva: Sequence[float]) -> float:
    pico, caida = curva[0], 0.0
    for v in curva:
        pico = max(pico, v)
        caida = max(caida, 1 - v / pico)
    return caida


def rendimientos(curva: Sequence[float]) -> list[float]:
    return [curva[i] / curva[i - 1] - 1 for i in range(1, len(curva))]


def sharpe_diario(rend: Sequence[float]) -> float:
    sd = statistics.pstdev(rend)
    return statistics.fmean(rend) / sd if sd > 0 else 0.0


def momentos(rend: Sequence[float]) -> tuple[float, float]:
    """(asimetria, curtosis) de los rendimientos (curtosis normal = 3)."""
    mu, sd, n = statistics.fmean(rend), statistics.pstdev(rend), len(rend)
    if sd == 0:
        return 0.0, 3.0
    return (sum((x - mu) ** 3 for x in rend) / n / sd ** 3, sum((x - mu) ** 4 for x in rend) / n / sd ** 4)


def probabilistico(sr: float, n: int, asim: float, curt: float, sr0: float = 0.0) -> float:
    """P(el Sharpe de verdad > sr0), con el Sharpe por periodo."""
    se = math.sqrt(max(1e-12, (1 - asim * sr + (curt - 1) / 4 * sr * sr) / (n - 1)))
    return N.cdf((sr - sr0) / se)


def deflactado(sr: float, n: int, intentos: int, dispersion: float, asim: float, curt: float) -> float:
    """El probabilistico frente al maximo esperado por suerte entre `intentos` (dispersion de sus Sharpe, por periodo)."""
    sr0 = dispersion * ((1 - EULER) * N.inv_cdf(1 - 1 / intentos) + EULER * N.inv_cdf(1 - 1 / (intentos * math.e)))
    return probabilistico(sr, n, asim, curt, sr0)


def tipos_de_mercado(cierres_btc: Sequence[float]) -> list[str | None]:
    """El tipo del dia i con el cierre de AYER (C4): alcista si el cierre de i-1 esta sobre su media de 200 y la media
    sube (frente a la de i-2); bajista si esta debajo y baja; lateral el resto. Sin datos, None."""
    m = ind.media(cierres_btc, 200)
    out: list[str | None] = [None] * len(cierres_btc)
    for i in range(2, len(cierres_btc)):
        a, b = m[i - 1], m[i - 2]
        if a is None or b is None:
            continue
        c = cierres_btc[i - 1]
        out[i] = "alcista" if c > a and a > b else "bajista" if c < a and a < b else "lateral"
    return out


def por_tipo(curva: Sequence[float], tipos: Sequence[str | None]) -> dict[str, dict[str, float]]:
    """Por tipo: rendimiento total compuesto de sus dias, dias y anualizado."""
    out = {}
    for tipo in ("alcista", "bajista", "lateral"):
        r = [curva[i] / curva[i - 1] - 1 for i in range(1, len(curva)) if tipos[i] == tipo]
        total = math.prod(1 + x for x in r) - 1 if r else 0.0
        out[tipo] = {"dias": len(r), "total": total, "anual": (1 + total) ** (365 / len(r)) - 1 if r else 0.0}
    return out


def pbo(rend: Sequence[Sequence[float]], trozos: int = 8) -> float:
    """Probabilidad de sobreajuste (CSCV): en cada mitad de trozos se elige la de mejor Sharpe y se mira su puesto en la
    otra mitad; PBO = proporcion de veces que queda por debajo de la mediana."""
    n = len(rend[0])
    limites = [n * k // trozos for k in range(trozos + 1)]
    grupos = [range(limites[k], limites[k + 1]) for k in range(trozos)]
    malos, total = 0, 0
    for dentro in combinations(range(trozos), trozos // 2):
        fuera = [k for k in range(trozos) if k not in dentro]
        sel = lambda ks, s: [s[j] for k in ks for j in grupos[k]]  # noqa: E731
        is_sr = [sharpe_diario(sel(dentro, s)) for s in rend]
        oos_sr = [sharpe_diario(sel(fuera, s)) for s in rend]
        mejor = max(range(len(rend)), key=lambda j: is_sr[j])
        puesto = sorted(range(len(rend)), key=lambda j: -oos_sr[j]).index(mejor) / (len(rend) - 1)
        malos += puesto > 0.5
        total += 1
    return malos / total
