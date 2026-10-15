"""Indicadores sobre listas diarias (indice = dia). El valor del dia i usa SOLO datos hasta i (y los de Donchian, solo
hasta i-1). Sin suficientes dias, None: nunca una media con menos dias de los que dice (aclaracion 1, C10)."""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

Serie = list[float | None]


def media(x: Sequence[float], n: int) -> Serie:
    out: Serie = [None] * len(x)
    suma = 0.0
    for i, v in enumerate(x):
        suma += v
        if i >= n:
            suma -= x[i - n]
        if i >= n - 1:
            out[i] = suma / n
    return out


def maximo_anterior(x: Sequence[float], n: int) -> Serie:
    """El maximo de los n dias ANTERIORES (i-n .. i-1): la ruptura de hoy no se compara consigo misma."""
    return [max(x[i - n:i]) if i >= n else None for i in range(len(x))]


def minimo_anterior(x: Sequence[float], n: int) -> Serie:
    return [min(x[i - n:i]) if i >= n else None for i in range(len(x))]


def rendimiento(x: Sequence[float], k: int) -> Serie:
    return [x[i] / x[i - k] - 1 if i >= k else None for i in range(len(x))]


def atr(altos: Sequence[float], bajos: Sequence[float], cierres: Sequence[float], n: int = 14) -> Serie:
    """ATR de Wilder: la primera, la media de n rangos verdaderos; despues, (anterior * (n-1) + rango) / n."""
    rangos = [altos[0] - bajos[0]] + [max(altos[i] - bajos[i], abs(altos[i] - cierres[i - 1]),
                                          abs(bajos[i] - cierres[i - 1])) for i in range(1, len(cierres))]
    out: Serie = [None] * len(cierres)
    if len(rangos) < n:
        return out
    a = sum(rangos[:n]) / n
    out[n - 1] = a
    for i in range(n, len(rangos)):
        a = (a * (n - 1) + rangos[i]) / n
        out[i] = a
    return out


def volatilidad(cierres: Sequence[float], n: int = 30) -> Serie:
    """Desviacion de los n ultimos rendimientos logaritmicos diarios, anualizada con raiz de 365 (cripto, 7 dias)."""
    logs = [math.log(cierres[i] / cierres[i - 1]) for i in range(1, len(cierres))]
    out: Serie = [None] * len(cierres)
    for i in range(n, len(cierres)):
        out[i] = statistics.pstdev(logs[i - n:i]) * math.sqrt(365)
    return out
