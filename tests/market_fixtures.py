"""Series de velas sinteticas con un regimen conocido.

POR QUE SINTETICAS Y NO REALES: para probar un setup hace falta poder decir
"esto ES un pullback en tendencia" con certeza. En datos reales nunca se sabe
del todo, asi que un test que falle no distingue entre "el setup esta mal" y
"la vela que elegi no era lo que yo creia".

Los datos reales se usan para OTRA cosa, que es igual de importante: comprobar
que sobre el mercado de verdad el clasificador no dice disparates y que los
setups no se disparan cada dos velas. Eso esta en los scripts de validacion,
no aqui.

Cada constructor deja el precio en un estado concreto en la ULTIMA vela, que
es la que miran el clasificador y los setups.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Milisegundos de una vela de 4 h. Los timestamps son reales para que
# `make_decision_id` produzca algo con sentido.
BAR_MS = 4 * 60 * 60 * 1000
START_MS = 1_756_000_000_000


def _frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Monta un DataFrame de velas a partir de los cierres.

    Las maximas y minimas se derivan del cierre con un rango pequenyo y
    constante. Basta para el ATR y para la mayoria de condiciones; el setup que
    necesita maximas de verdad (la ruptura) las coloca a mano.
    """
    n = len(closes)
    close = np.asarray(closes, dtype="float64")
    opens = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(close) * 0.004
    high = np.maximum(opens, close) + spread
    low = np.minimum(opens, close) - spread
    vol = np.asarray(volumes if volumes is not None else [1000.0] * n, dtype="float64")
    return pd.DataFrame(
        {
            "ts_open_ms": [START_MS + i * BAR_MS for i in range(n)],
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )


def trending_up(n: int = 200, *, start: float = 100.0, pullback: bool = False):
    """Tendencia alcista sostenida: ADX alto, EMA20 por encima de la EMA50.

    Con `pullback=True` las ultimas velas retroceden hasta la EMA20 sin romper
    la EMA50, que es exactamente lo que busca `pullback_trend`.
    """
    # LA DERIVA ESTA MEDIDA, no elegida. Cuanto mas empinada es la tendencia,
    # mas lejos queda la EMA20 por debajo del precio y mas profundo tiene que
    # ser el retroceso para tocarla... y un retroceso profundo dispara el ATR,
    # con lo que el regimen pasa a `HIGH_VOL` y el setup ni se ejecuta.
    #
    #   deriva/vela   precio sobre la EMA20
    #     0,15 %            2,0 %      <- alcanzable con un retroceso normal
    #     0,40 %            4,3 %      <- hay que hundirlo, y salta HIGH_VOL
    #
    # Con 0,15 % la tendencia sigue siendo clarisima (ADX por encima de 60) y
    # el retroceso cabe sin deformar la serie.
    rng = np.random.default_rng(7)
    closes = [start]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + 0.0015 + rng.normal(0, 0.004)))

    if pullback:
        for step in (-0.012, -0.010):
            closes.append(closes[-1] * (1 + step))

    return _frame(closes)


def trending_down(n: int = 200, *, start: float = 100.0):
    """Tendencia bajista: ADX alto, EMA20 por debajo de la EMA50."""
    rng = np.random.default_rng(11)
    closes = [start]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 - 0.004 + rng.normal(0, 0.003)))
    return _frame(closes)


def ranging(n: int = 200, *, start: float = 100.0, oversold: bool = False):
    """Rango: movido al principio, estrecho y picado al final.

    Dos detalles que costaron un par de intentos:

    * La primera mitad tiene que ser MAS volatil, porque el percentil de la
      anchura de Bollinger se mide contra la propia historia de la serie: sin
      un pasado mas ancho, el presente no puede estar "estrecho".
    * La oscilacion tiene que ser CORTA (periodo de unas 6 velas). Con un seno
      lento, cada medio ciclo es un tramo direccional de 12 velas seguidas y
      el ADX se va por encima de 25: el clasificador lee tendencia, y hace
      bien, porque eso no es un rango picado sino una onda.
    """
    rng = np.random.default_rng(3)
    closes = []
    half = n // 2
    for i in range(half):
        closes.append(start + 9.0 * np.sin(i / 5.0) + rng.normal(0, 1.2))
    for i in range(n - half):
        closes.append(start + 1.4 * np.sin(i) + rng.normal(0, 0.45))

    if oversold:
        # Una sola vela de caida brusca al suelo de las bandas. Tres seguidas
        # crearian movimiento direccional y el regimen pasaria a tendencia
        # bajista, que es precisamente donde este setup NO debe operar.
        closes.append(closes[-1] - 4.6)

    return _frame(closes)


def range_then_breakout(
    n: int = 200, *, start: float = 100.0, volume_spike: bool = True,
    breakout: bool = True,
):
    """Consolidacion ancha y lenta y, en la ultima vela, salida con volumen.

    `volume_spike=False` da la trampa clasica: el precio sale pero nadie le
    acompanya. `breakout=False` deja el precio dentro del rango.

    Que una ruptura demasiado timida siga clasificandose `RANGE` (y por tanto
    el setup ni se ejecute) NO se prueba con un fixture, porque el umbral
    exacto es fragil: se prueba directamente sobre el registro de regimenes
    permitidos, que es donde vive la regla.

    LA CONSOLIDACION TIENE QUE SER ANCHA Y LENTA, y es por aritmetica, no por
    gusto: el objetivo del setup es el movimiento medido (la altura del rango)
    y el stop es 1,9xATR, asi que para un R:R de 2:1 hace falta un rango de al
    menos 3,8 ATR de alto. Un rango picado tiene mucho ATR por vela y poca
    altura total, y nunca llega. Medido: amplitud 5 con periodo de 18 velas y
    ruido bajo da 4,5 ATR, que si pasa.
    """
    rng = np.random.default_rng(5)
    closes = []
    volumes = []
    half = n // 2
    for i in range(half):
        closes.append(start + 8.0 * np.sin(i / 6.0) + rng.normal(0, 1.0))
        volumes.append(1000.0 + rng.normal(0, 60))
    for i in range(n - half):
        closes.append(start + 5.0 * np.sin(i / 2.87) + rng.normal(0, 0.2))
        volumes.append(1000.0 + rng.normal(0, 60))

    # La ruptura es UNA vela. Si fuesen tres, las dos primeras quedarian
    # dentro de la ventana de 20 velas que el setup mira para medir el rango,
    # el "rango" saldria altisimo y el setup lo descartaria por no ser un
    # rango. Que es lo correcto, pero entonces el fixture no prueba nada.
    # Sube un 1,2 % por encima del techo: medido, eso deja la extension en
    # +0,37 ATR (por debajo del limite de no-perseguir) y el regimen en
    # `TRANSITION`. Con un 3,5 % el R:R caia de 2,4 a 1,6 y el setup lo
    # rechazaba por perseguir.
    ceiling = max(closes[-25:])
    if breakout:
        closes.append(ceiling * 1.012)
    else:
        closes.append(closes[-1])
    volumes.append(2600.0 if volume_spike else 980.0)

    return _frame(closes, volumes)


def high_volatility(n: int = 200, *, start: float = 100.0):
    """Serie tranquila que termina con un estallido de volatilidad."""
    rng = np.random.default_rng(13)
    closes = [start]
    for _ in range(n - 12):
        closes.append(closes[-1] * (1 + rng.normal(0, 0.0015)))
    for i in range(12):
        shock = 0.06 if i % 2 == 0 else -0.055
        closes.append(closes[-1] * (1 + shock))
    return _frame(closes)


def flat(n: int = 200, *, start: float = 100.0):
    """Precio literalmente constante. Caso limite: ATR cero, todo indefinido."""
    return _frame([start] * n)
