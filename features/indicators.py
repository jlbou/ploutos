"""Indicadores tecnicos (informe seccion 1.3).

POR QUE ESCRITOS A MANO Y NO CON UNA LIBRERIA: `ta-lib` obliga a compilar C, y
`pandas-ta` arrastra problemas de mantenimiento. Estos son ~10 indicadores de
unas pocas lineas cada uno, se prueban contra valores calculados a mano y no
dependen de nadie. Para el VPS, una dependencia menos que pueda romperse.

DOS REGLAS QUE SE APLICAN EN TODO EL MODULO:

1. **Solo velas cerradas.** Quien llama garantiza que no hay vela en curso. Usar
   la vela viva es la causa mas comun de look-ahead bias: en el backtest la
   senyal existe y en vivo desaparece (informe seccion 1.3[1]).

2. **Devolver NaN, nunca un numero inventado.** Un indicador sin datos
   suficientes devuelve NaN y el generador de candidatos descarta el simbolo.
   Rellenar con ceros o con el primer valor produce senyales fantasma en las
   primeras velas despues de cada arranque.

SUAVIZADO DE WILDER: RSI, ATR y ADX lo usan (alpha = 1/n). Se implementa con
`ewm(alpha=1/n, adjust=False)`, que es equivalente salvo en el arranque: Wilder
siembra con una media simple de los primeros n valores y `ewm` arranca del
primero. Convergen rapido, pero por eso estos indicadores exigen un calentamiento
de 3n velas antes de dar un valor por bueno.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Multiplo de periodos que hay que tener antes de fiarse de un indicador de
# Wilder. Con menos, el valor arrastra el sesgo del arranque.
WILDER_WARMUP_FACTOR = 3


def _as_series(values: pd.Series | np.ndarray | list[float]) -> pd.Series:
    if isinstance(values, pd.Series):
        return values.astype("float64")
    return pd.Series(np.asarray(values, dtype="float64"))


def _nan_like(series: pd.Series) -> pd.Series:
    return pd.Series(np.full(len(series), np.nan), index=series.index)


# --------------------------------------------------------------------------
# Tendencia
# --------------------------------------------------------------------------


def ema(close, period: int) -> pd.Series:
    """Media movil exponencial."""
    s = _as_series(close)
    if period < 1:
        raise ValueError(f"periodo invalido: {period}")
    if len(s) < period:
        return _nan_like(s)
    out = s.ewm(span=period, adjust=False).mean()
    # Antes de `period` velas el valor arrastra demasiado el arranque.
    out.iloc[: period - 1] = np.nan
    return out


def sma(close, period: int) -> pd.Series:
    s = _as_series(close)
    return s.rolling(window=period, min_periods=period).mean()


def ema_slope_pct(close, period: int, lookback: int = 5) -> pd.Series:
    """Pendiente de la EMA, en % por vela.

    En % y no en valor absoluto para que sea comparable entre monedas: una
    pendiente de 10 $ significa cosas muy distintas en BTC y en DOGE.
    """
    line = ema(close, period)
    previous = line.shift(lookback)
    return (line - previous) / previous * 100.0 / lookback


def adx(high, low, close, period: int = 14) -> pd.Series:
    """Indice direccional medio: FUERZA de la tendencia, no su direccion.

    Es el indicador mas facil de implementar mal. El orden importa: primero los
    movimientos direccionales crudos, luego el suavizado de Wilder, luego los DI,
    luego el DX y por ultimo el suavizado del DX.
    """
    h, low_s, c = _as_series(high), _as_series(low), _as_series(close)
    n = len(h)
    if n < period * WILDER_WARMUP_FACTOR:
        return _nan_like(h)

    up = h.diff()
    down = -low_s.diff()

    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=h.index)

    tr = true_range(h, low_s, c)
    alpha = 1.0 / period
    atr_s = tr.ewm(alpha=alpha, adjust=False).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s
        minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s
        total = plus_di + minus_di
        dx = 100.0 * (plus_di - minus_di).abs() / total

    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out = dx.ewm(alpha=alpha, adjust=False).mean()
    out.iloc[: period * WILDER_WARMUP_FACTOR] = np.nan
    return out


# --------------------------------------------------------------------------
# Momentum
# --------------------------------------------------------------------------


def rsi(close, period: int = 14) -> pd.Series:
    """RSI de Wilder. Siempre en [0, 100]."""
    s = _as_series(close)
    if len(s) < period * WILDER_WARMUP_FACTOR:
        return _nan_like(s)

    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100.0 - (100.0 / (1.0 + rs))

    # Sin perdidas en toda la ventana, RS es infinito y el RSI vale 100.
    out = out.where(avg_loss != 0, 100.0)
    # Sin ganancias, vale 0.
    out = out.where(avg_gain != 0, 0.0)
    out.iloc[: period * WILDER_WARMUP_FACTOR] = np.nan
    return out.clip(0.0, 100.0)


def macd_histogram(
    close, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.Series:
    """Histograma del MACD: linea menos senyal.

    Se devuelve solo el histograma porque es lo unico que el generador de
    candidatos usa; las otras dos lineas solo anyaden columnas y tokens al
    prompt de la IA.
    """
    s = _as_series(close)
    if len(s) < slow + signal:
        return _nan_like(s)
    line = ema(s, fast) - ema(s, slow)
    signal_line = line.ewm(span=signal, adjust=False).mean()
    out = line - signal_line
    out.iloc[: slow + signal - 1] = np.nan
    return out


def roc(close, period: int = 10) -> pd.Series:
    """Tasa de cambio en %."""
    s = _as_series(close)
    previous = s.shift(period)
    return (s - previous) / previous * 100.0


# --------------------------------------------------------------------------
# Volatilidad
# --------------------------------------------------------------------------


def true_range(high, low, close) -> pd.Series:
    """Rango verdadero: tiene en cuenta los huecos entre velas."""
    h, low_s, c = _as_series(high), _as_series(low), _as_series(close)
    previous_close = c.shift(1)
    ranges = pd.concat(
        [
            h - low_s,
            (h - previous_close).abs(),
            (low_s - previous_close).abs(),
        ],
        axis=1,
    )
    out = ranges.max(axis=1)
    out.iloc[0] = h.iloc[0] - low_s.iloc[0] if len(h) else np.nan
    return out


def atr(high, low, close, period: int = 14) -> pd.Series:
    """Rango verdadero medio (Wilder). En unidades de precio."""
    h = _as_series(high)
    if len(h) < period * WILDER_WARMUP_FACTOR:
        return _nan_like(h)
    tr = true_range(high, low, close)
    out = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    out.iloc[: period * WILDER_WARMUP_FACTOR] = np.nan
    return out


def atr_pct(high, low, close, period: int = 14) -> pd.Series:
    """ATR en % del precio. Es lo que se usa para colocar el stop.

    En % y no en valor absoluto por el mismo motivo que la pendiente: un ATR de
    50 $ es enorme en SOL y ruido en BTC.
    """
    c = _as_series(close)
    return atr(high, low, close, period) / c * 100.0


def bollinger_width_pct(close, period: int = 20, deviations: float = 2.0) -> pd.Series:
    """Anchura de las bandas de Bollinger en % del precio medio.

    Estrecha = compresion de volatilidad; ancha = expansion. Es una de las tres
    piezas del clasificador de regimen.
    """
    s = _as_series(close)
    middle = s.rolling(window=period, min_periods=period).mean()
    std = s.rolling(window=period, min_periods=period).std(ddof=0)
    return (2.0 * deviations * std) / middle * 100.0


def realized_volatility_pct(close, periods: int) -> pd.Series:
    """Volatilidad realizada: desviacion tipica de los rendimientos logaritmicos.

    `periods` son velas, no horas: con velas de 1 h, 24 h son 24 periodos.
    """
    s = _as_series(close)
    returns = np.log(s / s.shift(1))
    return returns.rolling(window=periods, min_periods=periods).std(ddof=0) * 100.0


# --------------------------------------------------------------------------
# Volumen
# --------------------------------------------------------------------------


def volume_zscore(volume, period: int = 20) -> pd.Series:
    """Cuantas desviaciones tipicas se sale el volumen de su media.

    Confirma rupturas: una ruptura sin volumen suele ser una trampa.
    """
    v = _as_series(volume)
    mean = v.rolling(window=period, min_periods=period).mean()
    std = v.rolling(window=period, min_periods=period).std(ddof=0)
    out = (v - mean) / std
    # Volumen constante: desviacion cero, z indefinido. Es 0, no infinito.
    return out.replace([np.inf, -np.inf], np.nan).where(std != 0, 0.0)


def vwap(high, low, close, volume) -> pd.Series:
    """VWAP acumulado desde el principio de la serie.

    Quien llama decide donde empieza la sesion: se le pasa solo el trozo de
    velas de esa sesion. Hacerlo aqui obligaria a este modulo a saber de husos
    horarios y de dias UTC, que no es su asunto.
    """
    h, low_s, c, v = (
        _as_series(high), _as_series(low), _as_series(close), _as_series(volume)
    )
    typical = (h + low_s + c) / 3.0
    cumulative_volume = v.cumsum()
    out = (typical * v).cumsum() / cumulative_volume
    return out.where(cumulative_volume > 0, np.nan)


def obv(close, volume) -> pd.Series:
    """On-Balance Volume: acumula el volumen con el signo del movimiento."""
    c, v = _as_series(close), _as_series(volume)
    direction = np.sign(c.diff()).fillna(0.0)
    return (direction * v).cumsum()
