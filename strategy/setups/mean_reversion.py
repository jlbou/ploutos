"""Reversion a la media en rango (informe seccion 1.3[5]).

LA IDEA: dentro de un rango, el precio se aleja de su media y vuelve. Comprar
cerca del suelo del rango y vender cerca de la media es la version mas simple
de eso.

**"NO OPERAR REVERSIONES EN TENDENCIA FUERTE"** (informe seccion 2.3[5]), y
aqui la regla no tiene truco: comprar caidas en una tendencia bajista es
ponerse delante del tren. El unico regimen permitido es `RANGE`, que exige a la
vez ADX bajo Y bandas estrechas.

ESTE SETUP TIENE UN STOP PROPIO, Y ES EL UNICO. El motivo, medido:

Con el stop comun de `multiplo_atr x ATR` (1,9xATR en 4 h), este setup no
producia **ni un solo candidato**: sobre datos reales, 285 velas en regimen
`RANGE` dieron 7 senyales con un R:R mediano de 0,91 y maximo de 1,06, cuando
hace falta 2,0. La cuenta explica por que sin depender de los datos: el
objetivo es la banda central, a unas 2 desviaciones tipicas del precio, asi que
para un R:R de 2 haria falta una desviacion de 1,9 ATR o mas, y en un rango
estrecho (el unico sitio donde este setup se activa) la desviacion medida es de
0,74 ATR.

El stop uniforme estaba, ademas, en el sitio equivocado por concepto: **una
reversion a la media se invalida cuando el precio SALE DEL RANGO**, no cuando
recorre una distancia fija en ATR. El stop natural es el suelo del rango.

Medido con ese stop: la distancia al suelo es de 0,90 ATR de mediana (frente a
1,9 del uniforme), el R:R mediano sube de 0,91 a 1,90 y 3 de las 7 senyales
pasan del 2,0. **Son 7 senyales: muestra corta, no concluyente.** La fase 6 lo
tiene que confirmar.

Que esto no rompa el dimensionado: `risk/sizing.py` calcula el nocional a
partir del stop REAL, asi que un stop mas estrecho da una posicion mayor,
topada en `max_notional_usd`, y el riesgo sigue siendo el mismo. No hace falta
un tope superior para el stop: si el suelo del rango queda muy lejos, el R:R
cae y el candidato muere en su filtro, que es donde tiene que morir.

Decidido por el propietario el 22/09/2026, con estos numeros delante.
"""

from __future__ import annotations

from features.indicators import rsi, sma
from features.regime import Regime
from strategy.setups.base import SetupContext, SetupSignal, build_signal, setup

NAME = "mean_reversion"

BB_PERIOD = 20
BB_DEVIATIONS = 2.0

# %B es donde cae el precio dentro de las bandas: 0 es la banda baja, 1 la
# alta. Por debajo de 0,2 el precio esta pegado al suelo del rango.
MAX_PERCENT_B = 0.20

# Sobreventa. Mas exigente que el 30 clasico porque solo interesan los extremos.
MAX_RSI = 35.0

# Velas hacia atras para localizar el suelo del rango.
RANGE_LOOKBACK = 20

# Colchon por debajo del suelo, para no salir por una mecha que toque justo la
# minima anterior y rebote.
STOP_BUFFER_ATR = 0.25

# Suelo de la distancia al stop. Por debajo de medio ATR el stop esta dentro
# del ruido de una sola vela y salta por nada. Medido: la distancia minima al
# suelo del rango en la muestra real fue de 0,47 ATR, asi que este limite casi
# nunca ata; esta para la cola, no para afinar.
MIN_STOP_ATR = 0.5


@setup(NAME, regimes={Regime.RANGE})
def detect(ctx: SetupContext) -> SetupSignal | None:
    """Busca un precio pegado al suelo del rango, con el RSI en sobreventa."""
    close = ctx.candles["close"]

    middle = sma(close, BB_PERIOD)
    deviation = close.rolling(window=BB_PERIOD, min_periods=BB_PERIOD).std(ddof=0)

    middle_now = float(middle.iloc[-1])
    dev_now = float(deviation.iloc[-1])
    price = float(close.iloc[-1])
    rsi_now = float(rsi(close, 14).iloc[-1])

    if any(v != v for v in (middle_now, dev_now, rsi_now)) or dev_now <= 0:
        return None

    lower = middle_now - BB_DEVIATIONS * dev_now
    upper = middle_now + BB_DEVIATIONS * dev_now
    percent_b = (price - lower) / (upper - lower)

    # 1. Pegado al suelo de las bandas.
    if percent_b > MAX_PERCENT_B:
        return None

    # 2. Sobreventa confirmada por el RSI.
    if rsi_now > MAX_RSI:
        return None

    # 3. El stop va bajo el suelo del rango: ahi es donde la idea se rompe.
    range_low = float(ctx.candles["low"].iloc[-RANGE_LOOKBACK:].min())
    stop = range_low - STOP_BUFFER_ATR * ctx.atr
    widest_allowed = price - MIN_STOP_ATR * ctx.atr
    stop = min(stop, widest_allowed)
    stop_atr = (price - stop) / ctx.atr if ctx.atr > 0 else 0.0

    # 4. El objetivo es la banda central. Si el precio ya esta por encima de
    #    ella, no hay reversion que hacer (lo comprueba `build_signal`).
    return build_signal(
        ctx,
        NAME,
        stop=stop,
        target=middle_now,
        reasons=(
            f"rango con ADX {ctx.regime.adx:.1f} y bandas en el percentil "
            f"{ctx.regime.bb_percentile:.0f}",
            f"precio en el {percent_b * 100:.0f} % de las bandas: pegado al suelo",
            f"RSI {rsi_now:.0f} en sobreventa",
            f"objetivo en la banda central ({middle_now:.6g})",
            f"stop bajo el suelo del rango ({range_low:.6g}), a "
            f"{stop_atr:.2f} ATR: la reversion se invalida al salir del rango",
        ),
        features={
            "adx14": ctx.regime.adx,
            "rsi14": rsi_now,
            "atr_pct": ctx.atr_pct,
            "percent_b": percent_b,
            "bb_lower": lower,
            "bb_middle": middle_now,
            "bb_upper": upper,
            "range_low": range_low,
            "stop_atr": stop_atr,
        },
    )
