"""Pullback en tendencia (informe secciones 1.3[5] y 2.3[1]).

LA VENTAJA, ESCRITA ANTES QUE EL CODIGO, como pide el informe seccion 2.3[1]:
*comprar retrocesos a la EMA20 en tendencia alcista de 4 h con ADX > 25*. No es
espectacular y puede acabar siendo nula; lo importante es que esta DEFINIDA, y
por tanto se puede medir en la fase 6 y descartar si no da nada.

La idea: en una tendencia alcista sana, el precio no sube en linea recta. Sube,
descansa hasta una media movil, y sigue. Comprar en el descanso es comprar mas
barato que comprar la subida, y con un stop mas cerca (la tendencia se da por
rota si pierde la estructura), asi que la misma cantidad de dolares de riesgo
compra mas posicion.

CUANDO NO SIRVE: cuando lo que parece un descanso es el principio de la vuelta.
Por eso hacen falta las tres condiciones a la vez (tendencia, retroceso Y
estructura intacta) y no solo "el precio ha bajado un poco".

OBJETIVO: el MOVIMIENTO MEDIDO, o sea la maxima del swing mas la altura del
impulso que la produjo (maxima menos minima de la ventana).

La primera version ponia el objetivo en la maxima previa del swing, y estaba
mal. La cuenta lo deja claro: si el objetivo es la maxima de la que el precio
acaba de venir, la distancia hasta el objetivo ES la profundidad del retroceso,
asi que

    R:R = profundidad_del_retroceso / (multiplo_atr x ATR)

y para llegar a 2:1 harian falta retrocesos de 3,8 ATR. Un retroceso de 3,8 ATR
en una tendencia no es un retroceso: es una ruptura de la tendencia, justo lo
que este setup NO quiere comprar. El objetivo se volvia inalcanzable por
construccion.

El fallo de fondo era conceptual: **este es un setup de CONTINUACION**. Si la
tendencia sigue, el precio hace una maxima NUEVA; no se conforma con volver a
tocar la anterior. Por eso el objetivo proyecta el impulso, igual que hace
`range_breakout` con la altura del rango.

Que la proyeccion correcta sea el 100 % del impulso y no el 61,8 % o el 161,8 %
es una eleccion, no una medicion: es la mas simple y la que hace que los dos
setups de continuacion usen el mismo criterio. **La fase 6 lo tiene que
comprobar con la expectativa real**, que para eso esta.
"""

from __future__ import annotations

from features.indicators import ema, rsi
from features.regime import Regime
from strategy.setups.base import SetupContext, SetupSignal, build_signal, setup

NAME = "pullback_trend"

# Velas hacia atras para buscar la maxima del swing. 20 velas de 4 h son algo
# mas de tres dias: suficiente para que haya una maxima reciente de verdad y
# poco para que no sea una maxima de hace un mes que ya no significa nada.
SWING_LOOKBACK = 20

# Como de cerca de la EMA20 tiene que haber llegado el retroceso, medido en
# ATR. Exigir que la toque exactamente descartaria la mayoria de retrocesos
# buenos por unos centimos.
PULLBACK_TOLERANCE_ATR = 0.5

# El RSI en un retroceso sano baja, pero no se hunde. Por debajo de 35 ya no es
# un descanso: algo ha cambiado.
RSI_MIN = 35.0
RSI_MAX = 62.0


@setup(NAME, regimes={Regime.TREND_UP})
def detect(ctx: SetupContext) -> SetupSignal | None:
    """Busca un retroceso a la EMA20 con la tendencia intacta."""
    close = ctx.candles["close"]
    low = ctx.candles["low"]
    high = ctx.candles["high"]

    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    rsi14 = rsi(close, 14)

    price = float(close.iloc[-1])
    ema20_now = float(ema20.iloc[-1])
    ema50_now = float(ema50.iloc[-1])
    rsi_now = float(rsi14.iloc[-1])
    low_now = float(low.iloc[-1])

    # Cualquier NaN: no hay lectura, no hay senyal. Nunca un numero inventado.
    if any(v != v for v in (ema20_now, ema50_now, rsi_now)):
        return None

    # 1. La estructura de la tendencia sigue entera. El regimen ya dice que hay
    #    tendencia alcista; esto comprueba que el retroceso no se la ha comido.
    if price <= ema50_now:
        return None

    # 2. Ha habido retroceso de verdad: la vela ha llegado a tocar la zona de
    #    la EMA20 (o a menos de medio ATR de ella).
    distance_to_ema20 = low_now - ema20_now
    if distance_to_ema20 > PULLBACK_TOLERANCE_ATR * ctx.atr:
        return None

    # 3. El retroceso es un descanso, no una vuelta.
    if not (RSI_MIN <= rsi_now <= RSI_MAX):
        return None

    # Objetivo: movimiento medido. La maxima del swing mas la altura del
    # impulso que llevo hasta ella, ambos sobre la ventana reciente y sin
    # contar la vela actual.
    window_high = high.iloc[-(SWING_LOOKBACK + 1):-1]
    window_low = low.iloc[-(SWING_LOOKBACK + 1):-1]
    swing_high = float(window_high.max())
    swing_low = float(window_low.min())
    impulse = swing_high - swing_low
    if impulse <= 0:
        return None
    target = swing_high + impulse

    return build_signal(
        ctx,
        NAME,
        target=target,
        reasons=(
            f"tendencia alcista con ADX {ctx.regime.adx:.1f}",
            f"retroceso hasta la EMA20 ({ema20_now:.6g}), a "
            f"{distance_to_ema20 / ctx.atr:+.2f} ATR de la minima",
            f"estructura intacta: precio por encima de la EMA50 ({ema50_now:.6g})",
            f"RSI {rsi_now:.0f}: descanso, no vuelta",
            f"objetivo por movimiento medido: maxima {swing_high:.6g} mas el "
            f"impulso {impulse:.6g}",
        ),
        features={
            "adx14": ctx.regime.adx,
            "rsi14": rsi_now,
            "atr_pct": ctx.atr_pct,
            "ema20": ema20_now,
            "ema50": ema50_now,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "impulse_atr": impulse / ctx.atr,
            "pullback_atr": distance_to_ema20 / ctx.atr,
        },
    )
