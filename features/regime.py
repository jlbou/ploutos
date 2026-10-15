"""Clasificador de regimen de mercado (informe seccion 1.3[3]).

PARA QUE SIRVE: "no operar rupturas en rango ni reversiones en tendencia
fuerte" (informe seccion 2.3[5]). Cada setup tiene un regimen en el que tiene
sentido y otros en los que es una forma cara de perder dinero. El clasificador
es barato y evita mucho danyo.

TRES SENYALES, COMO PIDE EL INFORME: ADX (fuerza de la tendencia), anchura de
Bollinger (compresion o expansion) y percentil del ATR (si la volatilidad de
ahora es normal para ESTA moneda o excepcional).

El percentil es lo que hace que el clasificador sea comparable entre monedas.
Un ATR del 3 % es una barbaridad en BTC y un martes cualquiera en DOGE; el
percentil pregunta "cuanto de raro es esto PARA TI", no "cuanto es en absoluto".

DOS DECISIONES QUE CONVIENE NO DESHACER:

1. **`TRANSITION` y `UNKNOWN` son cosas DISTINTAS, y mezclarlas seria un
   error caro.** `UNKNOWN` es "no se puede clasificar" (faltan velas, hay
   NaN): ahi no opera nadie, nunca. `TRANSITION` es una lectura valida que
   dice "ni tendencia ni rango, esto se esta moviendo de un estado a otro", y
   resulta que **es justo donde vive una ruptura de rango**: cuando el precio
   sale del rango, el ADX todavia esta subiendo por la zona de 20-25. Si las
   dos etiquetas fuesen la misma, o bien se prohibirian las rupturas o bien se
   dejaria operar sobre datos insuficientes.

   Este modulo DESCRIBE el mercado; no decide quien opera. Que regimenes
   acepta cada setup se declara en `strategy/setups/`, junto al setup.
2. **La alta volatilidad manda sobre todo lo demas.** Si el ATR esta en su
   percentil 85, da igual lo que diga el ADX: el stop que saldria de ahi es
   enorme, la posicion resultante minuscula y el ruido se come cualquier
   senyal. Se clasifica `HIGH_VOL` y no opera nadie.

La direccion de la tendencia NO la da el ADX (mide fuerza, no direccion). La
da la EMA20 contra la EMA50, que es la senyal mas simple que funciona y no
anyade un indicador nuevo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from features.indicators import adx, atr_pct, bollinger_width_pct, ema

# Umbrales del clasificador. El informe seccion 2.3[1] usa "ADX > 25" como
# ejemplo de tendencia utilizable, y 20 es el limite clasico por debajo del
# cual se considera que no hay tendencia. Entre los dos, transicion.
ADX_TREND = 25.0
ADX_RANGE = 20.0

# Percentil del ATR a partir del cual la moneda esta excepcionalmente movida
# PARA SU PROPIO historial.
ATR_PERCENTILE_HIGH = 80.0

# ...Y ADEMAS tiene que estar de verdad por encima de lo suyo. El percentil
# solo no vale: una moneda cuya volatilidad apenas cambia (medido: una serie
# con ATR entre 1,06 % y 1,20 %) reparte percentiles extremos por puro ruido,
# asi que acabaria clasificada HIGH_VOL una de cada cinco velas sin que haya
# pasado nada. Con las dos condiciones, "excepcional" quiere decir
# excepcional: alta en su ranking Y medio ATR por encima de su mediana.
#
# Con datos reales del 22/09/2026 esto separa bien: AVAX (4,41 % contra una
# mediana de 1,98 %) y NEAR (5,37 % contra 3,33 %) si estan disparadas; TRX,
# que es plana como una mesa, no se cuela nunca.
ATR_HIGH_RATIO = 1.5

# Para llamar rango a un rango, las bandas tienen que estar estrechas respecto
# a como suelen estar en esta moneda.
BB_PERCENTILE_TIGHT = 50.0

# Velas minimas para fiarse del percentil. Con menos, el percentil dice mas de
# la muestra que del mercado.
MIN_HISTORY = 60


class Regime(Enum):
    """Regimen de mercado.

    `UNKNOWN` significa "no se puede saber", no "normal" ni "tranquilo".
    `TRANSITION` si es una lectura: significa "entre estados".
    """

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    # Lectura valida: ni tendencia ni rango. Aqui es donde rompe un rango.
    TRANSITION = "transition"
    # NO se puede clasificar (faltan velas o hay NaN). Nadie opera aqui.
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RegimeReading:
    """La etiqueta y los numeros de los que sale.

    Los numeros van dentro porque el panel del PRD seccion 10 tiene que poder
    ensenyar POR QUE se clasifico asi, y porque en la fase 6 hay que poder
    revisar si los umbrales estaban bien elegidos.
    """

    regime: Regime
    adx: float
    atr_pct: float
    atr_percentile: float
    bb_width_pct: float
    bb_percentile: float
    ema_fast: float
    ema_slow: float
    detail: str = ""

    @property
    def is_trend(self) -> bool:
        return self.regime in (Regime.TREND_UP, Regime.TREND_DOWN)

    @property
    def is_known(self) -> bool:
        """Si la lectura sirve para algo. `UNKNOWN` no."""
        return self.regime is not Regime.UNKNOWN

    def __str__(self) -> str:
        return (
            f"{self.regime} (ADX {self.adx:.1f}, ATR {self.atr_pct:.2f} % "
            f"= percentil {self.atr_percentile:.0f}, bandas "
            f"{self.bb_width_pct:.2f} % = percentil {self.bb_percentile:.0f})"
        )


def _percentile_of(series: pd.Series, value: float) -> float:
    """En que percentil de su propia historia cae el valor de ahora.

    Los empates cuentan la MITAD, no entera. Con `<=` a secas, una moneda cuya
    volatilidad no cambia (todos los valores iguales) daria percentil 100, o
    sea "excepcionalmente movida", que es justo lo contrario de lo que pasa:
    seria la moneda mas aburrida de la lista y se clasificaria `HIGH_VOL`.
    Con el convenio del punto medio, una serie constante da 50, que es lo
    honesto: ni alta ni baja, normal para si misma.
    """
    clean = series.dropna()
    if len(clean) < MIN_HISTORY or value != value:
        return float("nan")
    below = float((clean < value).sum())
    equal = float((clean == value).sum())
    return (below + 0.5 * equal) / len(clean) * 100.0


def _unknown(reason: str, **values: float) -> RegimeReading:
    nan = float("nan")
    return RegimeReading(
        regime=Regime.UNKNOWN,
        adx=values.get("adx", nan),
        atr_pct=values.get("atr_pct", nan),
        atr_percentile=values.get("atr_percentile", nan),
        bb_width_pct=values.get("bb_width_pct", nan),
        bb_percentile=values.get("bb_percentile", nan),
        ema_fast=values.get("ema_fast", nan),
        ema_slow=values.get("ema_slow", nan),
        detail=reason,
    )


def classify(
    candles: pd.DataFrame,
    *,
    adx_period: int = 14,
    atr_period: int = 14,
    bb_period: int = 20,
    fast: int = 20,
    slow: int = 50,
) -> RegimeReading:
    """Clasifica el regimen en la ULTIMA vela de `candles`.

    `candles` tiene que traer SOLO velas cerradas, en orden y con las columnas
    high/low/close. Quien llama lo garantiza: este modulo no sabe de relojes ni
    de bases de datos (informe seccion 1.3[1], evita el look-ahead bias).
    """
    needed = {"high", "low", "close"}
    missing = needed - set(candles.columns)
    if missing:
        raise ValueError(f"faltan columnas en las velas: {sorted(missing)}")

    if len(candles) < MIN_HISTORY:
        return _unknown(
            f"solo {len(candles)} velas cerradas, hacen falta {MIN_HISTORY} "
            f"para que el percentil signifique algo"
        )

    high, low, close = candles["high"], candles["low"], candles["close"]

    adx_series = adx(high, low, close, adx_period)
    atr_series = atr_pct(high, low, close, atr_period)
    bb_series = bollinger_width_pct(close, bb_period)
    ema_fast_series = ema(close, fast)
    ema_slow_series = ema(close, slow)

    adx_now = float(adx_series.iloc[-1])
    atr_now = float(atr_series.iloc[-1])
    bb_now = float(bb_series.iloc[-1])
    fast_now = float(ema_fast_series.iloc[-1])
    slow_now = float(ema_slow_series.iloc[-1])

    atr_pctile = _percentile_of(atr_series, atr_now)
    bb_pctile = _percentile_of(bb_series, bb_now)

    values = {
        "adx": adx_now,
        "atr_pct": atr_now,
        "atr_percentile": atr_pctile,
        "bb_width_pct": bb_now,
        "bb_percentile": bb_pctile,
        "ema_fast": fast_now,
        "ema_slow": slow_now,
    }

    # Cualquier NaN -> no se sabe. Nunca se rellena con un numero inventado.
    if any(np.isnan(v) for v in values.values()):
        faltan = sorted(k for k, v in values.items() if np.isnan(v))
        return _unknown(f"sin calentamiento suficiente para {faltan}", **values)

    def reading(regime: Regime, detail: str) -> RegimeReading:
        return RegimeReading(regime=regime, detail=detail, **values)

    # 1. La volatilidad excepcional manda sobre todo lo demas. Hacen falta las
    #    DOS condiciones: alta en su propio ranking y alta en valor absoluto
    #    respecto a su mediana (ver `ATR_HIGH_RATIO`).
    atr_median = float(atr_series.dropna().median())
    atr_ratio = atr_now / atr_median if atr_median > 0 else 1.0
    if atr_pctile >= ATR_PERCENTILE_HIGH and atr_ratio >= ATR_HIGH_RATIO:
        return reading(
            Regime.HIGH_VOL,
            f"ATR {atr_now:.2f} % es {atr_ratio:.1f} veces su mediana "
            f"({atr_median:.2f} %) y esta en el percentil {atr_pctile:.0f}: "
            f"demasiado movida para colocar un stop sensato",
        )

    # 2. Tendencia: fuerza del ADX, direccion de las EMA.
    if adx_now >= ADX_TREND:
        if fast_now > slow_now:
            return reading(
                Regime.TREND_UP,
                f"ADX {adx_now:.1f} con EMA{fast} por encima de EMA{slow}",
            )
        return reading(
            Regime.TREND_DOWN,
            f"ADX {adx_now:.1f} con EMA{fast} por debajo de EMA{slow}",
        )

    # 3. Rango: sin fuerza Y con las bandas estrechas para lo que suelen.
    #    Las dos condiciones, no una: un ADX bajo con las bandas anchas es
    #    indecision volatil, que no es un rango operable.
    if adx_now < ADX_RANGE and bb_pctile <= BB_PERCENTILE_TIGHT:
        return reading(
            Regime.RANGE,
            f"ADX {adx_now:.1f} sin fuerza y bandas en el percentil "
            f"{bb_pctile:.0f}",
        )

    # 4. Todo lo demas esta entre estados. Es una lectura, no una duda: el
    #    mercado se esta moviendo de un regimen a otro, y ahi es donde una
    #    ruptura de rango tiene sentido.
    return reading(
        Regime.TRANSITION,
        f"entre estados: ADX {adx_now:.1f} (tendencia desde {ADX_TREND}, "
        f"rango por debajo de {ADX_RANGE}), bandas en el percentil "
        f"{bb_pctile:.0f}",
    )
