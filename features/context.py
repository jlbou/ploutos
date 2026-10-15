"""Contexto de cartera: correlaciones entre monedas (informe seccion 1.3[3]).

POR QUE ESTE MODULO EXISTE, y por que faltaba:

La regla 15 tiene dos mitades. La de exposicion (maximo 90 % del equity)
funcionaba. La de correlacion (maximo 2 posiciones que correlacionen mas de 0,8
entre si) **no habia vetado nunca nada**, porque `RiskState.correlations`
llegaba siempre vacio: no habia nadie que calculara ese numero. El motor
preguntaba y la respuesta era siempre 0,0.

Es el mismo patron que el invariante de exposicion que estaba escrito en la
cabecera de un test sin `@invariant()` detras: una proteccion que todo el mundo
da por hecha y que no comprueba nadie.

POR QUE IMPORTA (informe seccion 2.4): "tres altcoins largas con correlacion
0,9 no son tres apuestas: son una sola, apalancada". Con 3 huecos y monedas que
se mueven juntas, la diversificacion puede ser una ilusion: crees que tienes
tres posiciones y tienes una del triple de tamanyo.

Medido el 22/09/2026 sobre datos reales (7 dias de rendimientos horarios):
BTC-ETH 0,84, ETH-SOL 0,84, BTC-SOL 0,81. **Los tres pares del grupo
BTC/ETH/SOL pasan de 0,80**, asi que tenerlos los tres a la vez es justo lo que
la regla 15 existe para impedir. El resto de la whitelist correlaciona mucho
menos (media general 0,45) y TRX es casi independiente (0,26 con todo).

DOS DECISIONES:

1. **Correlacion de RENDIMIENTOS, no de precios.** Dos series de precios que
   suben correlacionan cerca de 1 aunque suban por motivos distintos: es la
   tendencia comun, no la relacion. Lo que importa es si se mueven juntas vela
   a vela.
2. **Si no hay muestra suficiente, se devuelve NaN y el par no se registra**,
   igual que en los indicadores. Una correlacion calculada con 10 velas no es
   una correlacion baja: es una correlacion que no se sabe. Registrarla como
   0,0 seria decirle al motor de riesgo que dos monedas son independientes
   cuando nadie lo ha comprobado, que es el error caro en esta direccion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Velas minimas para fiarse. La regla 15 pide una ventana de 7 dias; con velas
# de 1 h eso son 168 puntos. Se exige al menos la mitad para dar un numero.
MIN_SAMPLES = 84

# Ventana de la regla 15, en horas.
WINDOW_HOURS = 7 * 24


@dataclass(frozen=True, slots=True)
class CorrelationMatrix:
    """Correlaciones por pares, listas para `RiskState.correlations`.

    Las claves van ordenadas alfabeticamente (a < b), igual que las espera
    `RiskState.correlation()`. Que el formato coincida evita el fallo tonto de
    calcularlo bien y guardarlo donde nadie lo lee.
    """

    values: dict[tuple[str, str], float] = field(default_factory=dict)
    samples: int = 0
    skipped: tuple[str, ...] = ()

    def get(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.values.get((a, b) if a < b else (b, a), 0.0)

    def above(self, threshold: float) -> list[tuple[str, str, float]]:
        """Pares por encima del umbral, de mas a menos correlacionados."""
        return sorted(
            ((a, b, v) for (a, b), v in self.values.items() if v > threshold),
            key=lambda item: -item[2],
        )

    def clusters(self, threshold: float) -> list[frozenset[str]]:
        """Grupos de monedas correlacionadas entre si por encima del umbral.

        Sirve para el panel: "BTC, ETH y SOL se mueven juntos" dice mas que
        tres lineas de numeros.
        """
        grupos: list[set[str]] = []
        for a, b, _v in self.above(threshold):
            for grupo in grupos:
                if a in grupo or b in grupo:
                    grupo.update((a, b))
                    break
            else:
                grupos.append({a, b})
        # Fusionar los que hayan quedado solapados.
        fusionados: list[set[str]] = []
        for grupo in grupos:
            for otro in fusionados:
                if grupo & otro:
                    otro.update(grupo)
                    break
            else:
                fusionados.append(set(grupo))
        return [frozenset(g) for g in fusionados]

    def __str__(self) -> str:
        if not self.values:
            return "sin correlaciones calculadas"
        altos = self.above(0.8)
        return (
            f"{len(self.values)} pares sobre {self.samples} velas; "
            f"{len(altos)} por encima de 0,8"
        )


def compute(
    closes: dict[str, pd.Series],
    *,
    window: int = WINDOW_HOURS,
    min_samples: int = MIN_SAMPLES,
) -> CorrelationMatrix:
    """Correlaciones por pares sobre los rendimientos de las ultimas `window` velas.

    `closes` son series de cierres de velas CERRADAS, indexadas por timestamp.
    Quien llama garantiza el timeframe; la regla 15 habla de 7 dias, asi que
    con velas de 1 h la ventana por defecto ya son esos 7 dias.

    Las series se alinean por timestamp antes de comparar. Sin alinear, un
    hueco en una moneda desplazaria todas las demas y la correlacion resultante
    seria ruido con pinta de dato.
    """
    if len(closes) < 2:
        return CorrelationMatrix()

    frame = pd.DataFrame(
        {symbol: serie.astype("float64") for symbol, serie in closes.items()}
    ).sort_index()
    returns = frame.pct_change().tail(window)

    values: dict[tuple[str, str], float] = {}
    skipped: list[str] = []
    symbols = sorted(frame.columns)

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            pareja = returns[[a, b]].dropna()
            if len(pareja) < min_samples:
                skipped.append(f"{a}/{b}")
                continue
            valor = float(pareja[a].corr(pareja[b]))
            if np.isnan(valor):
                skipped.append(f"{a}/{b}")
                continue
            values[(a, b)] = valor

    return CorrelationMatrix(
        values=values,
        samples=int(len(returns)),
        skipped=tuple(skipped),
    )


def correlated_budget_used(
    matrix: CorrelationMatrix, symbol: str, held: list[str], threshold: float
) -> int:
    """Cuantas posiciones en cartera correlacionan con `symbol`.

    Es lo mismo que hace `RiskState.correlated_with()`, aqui en forma de
    numero para el panel y para los logs. El motor de riesgo sigue usando el
    suyo: no se le cambia la fuente de verdad a una regla dura.
    """
    # Igual que el motor: una pareja sin medir cuenta como correlacionada.
    def cuenta(other: str) -> bool:
        key = (symbol, other) if symbol < other else (other, symbol)
        return key not in matrix.values or matrix.values[key] > threshold

    return sum(1 for other in held if other != symbol and cuenta(other))
