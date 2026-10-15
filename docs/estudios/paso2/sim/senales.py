"""Las senyales del paso 2 (plan, seccion 8): la fraccion objetivo [0, 1] de cada moneda con el cierre del dia i. El
tamanyo de verdad (topes, riesgo, escalones) lo pone el motor. Una senyal sin datos suficientes es 0 (fuera)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sim import indicadores as ind

PLAZOS = (20, 50, 100, 200)
SEMANAS = (1, 2, 3, 4)
VOL_OBJETIVO = 0.60


def h1(cierres: Sequence[float]) -> list[float]:
    """Dentro (1) si el cierre esta por encima de las 4 medias simples; fuera (0) en otro caso."""
    medias = [ind.media(cierres, n) for n in PLAZOS]
    return [1.0 if all(m[i] is not None and c > m[i] for m in medias) else 0.0 for i, c in enumerate(cierres)]


def h2(altos: Sequence[float], bajos: Sequence[float], cierres: Sequence[float]) -> list[float]:
    """Cada plazo N entra si el cierre supera el maximo de los N dias anteriores y sale si baja del minimo de los N/2
    anteriores; la fraccion es la media de los 4."""
    estados = []
    for n in PLAZOS:
        mx, mn = ind.maximo_anterior(altos, n), ind.minimo_anterior(bajos, n // 2)
        dentro, serie = False, []
        for i, c in enumerate(cierres):
            if not dentro and mx[i] is not None and c > mx[i]:
                dentro = True
            elif dentro and mn[i] is not None and c < mn[i]:
                dentro = False
            serie.append(1.0 if dentro else 0.0)
        estados.append(serie)
    return [sum(e[i] for e in estados) / len(PLAZOS) for i in range(len(cierres))]


def h3(tiempos: Sequence[int], cierres: Sequence[float]) -> list[float]:
    """Con el cierre de cada DOMINGO (la orden, el lunes): la fraccion de los rendimientos de 1-4 semanas que son
    positivos (sin dato = no positivo). Entre domingos no cambia."""
    rend = {k: ind.rendimiento(cierres, 7 * k) for k in SEMANAS}
    out, actual = [], 0.0
    for i, t in enumerate(tiempos):
        if datetime.fromtimestamp(t, UTC).weekday() == 6:
            actual = sum(1 for k in SEMANAS if rend[k][i] is not None and rend[k][i] > 0) / len(SEMANAS)
        out.append(actual)
    return out


def capa_volatilidad(fracciones: Sequence[float], vol: Sequence[float | None]) -> list[float]:
    """La fraccion × min(1; 60 % / volatilidad de 30 dias); sin volatilidad calculable, 0 (no se sabe cuanto)."""
    return [0.0 if v is None else f * min(1.0, VOL_OBJETIVO / v) if v > 0 else f for f, v in zip(fracciones, vol, strict=True)]
