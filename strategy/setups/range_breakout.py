"""Ruptura de rango con volumen (informe seccion 1.3[5]).

LA IDEA: el precio lleva un tiempo yendo de un lado a otro entre dos niveles.
Cuando sale por arriba, la gente que vendia en el techo deja de hacerlo y el
precio suele recorrer, como minimo, otra vez la altura del rango.

**"NO OPERAR RUPTURAS EN RANGO"** (informe seccion 2.3[5]) es la regla que da
forma a este setup, y hay que leerla con cuidado porque suena contradictoria:
si es una ruptura DE un rango, como no va a haber un rango? Lo que quiere decir
es que el rango tiene que estar en el PASADO de la vela, no en el presente:

  * en las velas anteriores, un rango estrecho (eso lo mide el setup);
  * en la vela de ahora, EXPANSION: el precio sale, el volumen confirma y el
    regimen ya no dice `RANGE`.

Si en el momento de "romper" el clasificador sigue viendo un rango (ADX plano,
bandas comprimidas), no ha roto nada: es el precio asomandose, que es la trampa
clasica. Por eso los regimenes permitidos son `TRANSITION` (el ADX subiendo por
la zona de 20-25, que es como se ve una ruptura mientras pasa) y `TREND_UP`,
pero **nunca `RANGE`**.

Esa lectura es mia, y el informe no la desarrolla. Si en la fase 6 resulta que
este setup no da nada, el primer sitio donde mirar es aqui.

EL VOLUMEN NO ES OPCIONAL: una ruptura sin volumen suele ser una trampa
(informe seccion 1.3[3], el z-score de volumen esta para "confirmacion").

OBJETIVO: el movimiento medido, o sea el techo del rango mas la altura del
rango. Es la proyeccion clasica y, sobre todo, es un nivel que sale del grafico
y no de multiplicar el riesgo por dos.
"""

from __future__ import annotations

from features.indicators import volume_zscore
from features.regime import Regime
from strategy.setups.base import SetupContext, SetupSignal, build_signal, setup

NAME = "range_breakout"

# Velas que forman el rango, sin contar la de la ruptura.
RANGE_LOOKBACK = 20

# LA ALTURA DEL RANGO ES LO QUE DECIDE SI ESTE SETUP PUEDE EXISTIR, y la
# cuenta merece escribirse porque no es evidente:
#
#   entrada  ~ techo del rango
#   stop     = entrada - multiplo_atr x ATR
#   objetivo = techo + altura       (movimiento medido)
#   R:R      = altura / (multiplo_atr x ATR)
#
# Para un R:R de 2:1 hace falta altura >= 2 x multiplo_atr ATR, o sea **3,8 ATR
# en velas de 4 h** y 6,6 ATR en las de 1 h. El primer intento puso el techo en
# 4,0 ATR "porque un rango es algo estrecho", lo que dejaba una ventana util de
# [3,8; 4,0] ATR: el setup no habria producido un candidato en su vida y habria
# parecido que el mercado no daba oportunidades.
#
# Asi que el limite INFERIOR util no se fija aqui: lo fija el filtro de R:R de
# `strategy/candidates.py`, que es donde vive esa regla. Aqui solo queda un
# suelo contra rangos degenerados y un techo que separa "consolidacion" de
# "esto ya es una tendencia con forma de rango".
MAX_RANGE_HEIGHT_ATR = 8.0
MIN_RANGE_HEIGHT_ATR = 1.0

# Confirmacion de volumen. 1,0 desviaciones sobre la media de 20 es exigente
# sin ser raro.
MIN_VOLUME_Z = 1.0

# NO PERSEGUIR. Cada punto que el precio ya ha corrido por encima del techo es
# un punto que se le resta al objetivo y no al stop, asi que el R:R se hunde
# rapido: medido, entrar un 3,5 % por encima del techo bajaba un R:R de 2,4 a
# 1,6. O se coge la ruptura pronto o no se coge.
MAX_EXTENSION_ATR = 1.0


@setup(NAME, regimes={Regime.TRANSITION, Regime.TREND_UP})
def detect(ctx: SetupContext) -> SetupSignal | None:
    """Busca una salida por arriba de un rango reciente, con volumen."""
    if "volume" not in ctx.candles.columns:
        return None

    high = ctx.candles["high"]
    low = ctx.candles["low"]
    close = ctx.candles["close"]

    if len(ctx.candles) < RANGE_LOOKBACK + 2:
        return None

    # El rango son las velas ANTERIORES a la actual. Incluir la vela de la
    # ruptura en el rango seria mirar el futuro desde el pasado.
    window_high = high.iloc[-(RANGE_LOOKBACK + 1):-1]
    window_low = low.iloc[-(RANGE_LOOKBACK + 1):-1]
    range_high = float(window_high.max())
    range_low = float(window_low.min())
    range_height = range_high - range_low

    if ctx.atr <= 0 or range_height <= 0:
        return None

    height_in_atr = range_height / ctx.atr

    # 1. Era un rango: ni degenerado ni tan alto que ya sea una tendencia.
    #    Quien descarta de verdad por altura insuficiente es el filtro de R:R,
    #    no este (ver el comentario de las constantes).
    if not (MIN_RANGE_HEIGHT_ATR <= height_in_atr <= MAX_RANGE_HEIGHT_ATR):
        return None

    # 2. Ha salido por arriba, y con el CIERRE, no con la mecha. Una mecha por
    #    encima del techo que se devuelve dentro es lo contrario de una ruptura.
    price = float(close.iloc[-1])
    if price <= range_high:
        return None

    # 3. No se persigue: el cierre no puede haberse ido muy por encima.
    extension_atr = (price - range_high) / ctx.atr
    if extension_atr > MAX_EXTENSION_ATR:
        return None

    # 4. El volumen confirma.
    vol_z = float(volume_zscore(ctx.candles["volume"], 20).iloc[-1])
    if vol_z != vol_z or vol_z < MIN_VOLUME_Z:
        return None

    # Objetivo: movimiento medido (techo del rango + altura del rango).
    target = range_high + range_height

    return build_signal(
        ctx,
        NAME,
        target=target,
        reasons=(
            f"rango de {height_in_atr:.1f} ATR durante {RANGE_LOOKBACK} velas "
            f"({range_low:.6g} - {range_high:.6g})",
            f"cierre en {price:.6g}, {extension_atr:.2f} ATR por encima del "
            f"techo (sin perseguir)",
            f"volumen a {vol_z:+.1f} desviaciones: la ruptura va acompanyada",
            f"regimen {ctx.regime.regime}: ya no es un rango",
        ),
        features={
            "adx14": ctx.regime.adx,
            "atr_pct": ctx.atr_pct,
            "vol_z": vol_z,
            "range_high": range_high,
            "range_low": range_low,
            "range_height_atr": height_in_atr,
            "breakout_pct": (price - range_high) / range_high * 100.0,
            "extension_atr": extension_atr,
        },
    )
