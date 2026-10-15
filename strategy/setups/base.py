"""Contrato comun de los setups (informe seccion 1.3[5]).

"Reglas explicitas y pocas." Tres setups, cada uno con sus condiciones escritas
en codigo, no en prosa. La IA elige ENTRE candidatos ya construidos; no inventa
setups ni mueve sus umbrales (PRD seccion 6).

DOS DECISIONES QUE DAN FORMA A TODO LO DEMAS:

1. **El stop por defecto es `multiplo_atr x ATR` para todos**, porque ese
   multiplo es el que se midio el 22/09/2026 para que las posiciones salgan de
   ~15 $ con 0,50 $ de riesgo. Si cada setup pusiera el stop donde le
   apeteciera, el tamanyo de posicion dejaria de ser predecible.

   **Un setup PUEDE pedir otro stop, pero tiene que justificarlo**, y solo hay
   uno que lo hace: `mean_reversion`, porque su stop natural es el suelo del
   rango y no una distancia en ATR (decision del propietario del 22/09/2026, tomada
   despues de medir que con el stop uniforme ese setup no producia ni un
   candidato en 285 velas en rango).

   Que esto no rompa nada tiene un motivo concreto: `risk/sizing.py` calcula
   el nocional a partir del stop REAL, sea cual sea, y el riesgo nunca pasa
   del permitido. Un stop mas estrecho da una posicion mayor, topada en
   `max_notional_usd`. La aritmetica del PRD sigue cuadrando.

2. **El objetivo es un NIVEL REAL del grafico, no `entrada + 2R`.** Si el
   objetivo se fabricase multiplicando el riesgo por 2, el R:R seria siempre 2
   por construccion y `min_reward_risk` no comprobaria nada: seria un numero
   que se cumple solo. Cada setup dice a donde cree que va el precio y por que
   (la ultima maxima del swing, la altura del rango proyectada, la banda
   central), y DESPUES se mira si eso da un R:R aceptable. Muchos candidatos
   mueren ahi, y eso es la comprobacion funcionando, no fallando.

Todos los setups son SOLO LARGOS: es spot sin apalancamiento (regla 1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from features.regime import Regime, RegimeReading


@dataclass(frozen=True, slots=True)
class SetupContext:
    """Todo lo que un setup puede mirar. Ni una cosa mas.

    Sin I/O, sin reloj y sin estado de cartera: un setup responde "hay senyal
    en este grafico", no "conviene abrirla". Lo segundo es del motor de riesgo.
    """

    symbol: str
    timeframe: str
    # SOLO velas cerradas, en orden ascendente, con open/high/low/close/volume.
    candles: pd.DataFrame
    regime: RegimeReading
    # ATR en unidades de precio y en %, de la ultima vela cerrada.
    atr: float
    atr_pct: float
    # Multiplo medido para este timeframe (`strategy.atr_multiple`).
    atr_multiple: float

    @property
    def close(self) -> float:
        return float(self.candles["close"].iloc[-1])

    @property
    def stop_distance(self) -> float:
        """La distancia al stop, igual para los tres setups."""
        return self.atr * self.atr_multiple


@dataclass(frozen=True, slots=True)
class SetupSignal:
    """Una senyal con precios propuestos. Todavia NO es un candidato.

    Le falta pasar por el coste (3x, regla 16) y por el R:R minimo, que es cosa
    de `strategy/candidates.py`.
    """

    setup: str
    entry: float
    stop: float
    target: float
    reasons: tuple[str, ...] = ()
    features: dict[str, float] = field(default_factory=dict)

    @property
    def risk(self) -> float:
        return self.entry - self.stop

    @property
    def reward_risk(self) -> float:
        if self.risk <= 0:
            return 0.0
        return (self.target - self.entry) / self.risk

    @property
    def stop_pct(self) -> float:
        return (self.entry - self.stop) / self.entry * 100.0

    @property
    def target_pct(self) -> float:
        return (self.target - self.entry) / self.entry * 100.0


SetupFn = Callable[[SetupContext], SetupSignal | None]

# (nombre, regimenes permitidos, funcion)
_REGISTRY: list[tuple[str, frozenset[Regime], SetupFn]] = []


def setup(name: str, regimes: set[Regime]):
    """Registra un setup y el regimen en el que tiene sentido.

    El regimen es parte de la DEFINICION del setup, no un filtro externo: una
    reversion a la media en tendencia fuerte no es "una reversion con mala
    suerte", es otra cosa que casualmente se parece (informe seccion 2.3[5]).
    """

    def decorator(fn: SetupFn) -> SetupFn:
        _REGISTRY.append((name, frozenset(regimes), fn))
        return fn

    return decorator


def all_setups() -> list[tuple[str, frozenset[Regime], SetupFn]]:
    return sorted(_REGISTRY, key=lambda item: item[0])


def setup_names() -> list[str]:
    return [name for name, _regimes, _fn in all_setups()]


def regimes_for(name: str) -> frozenset[Regime]:
    for setup_name, regimes, _fn in _REGISTRY:
        if setup_name == name:
            return regimes
    raise KeyError(f"setup desconocido: {name}")


def build_signal(
    ctx: SetupContext,
    name: str,
    target: float,
    reasons: tuple[str, ...],
    features: dict[str, float],
    *,
    stop: float | None = None,
) -> SetupSignal | None:
    """Monta la senyal. Sin `stop`, usa el comun de `multiplo_atr x ATR`.

    `stop` explicito solo para el setup que tenga un motivo escrito (hoy,
    `mean_reversion`). No es una puerta abierta: pasarlo sin justificarlo en
    el docstring del setup deja el dimensionado impredecible.

    Devuelve `None` si el objetivo no esta por encima de la entrada: un setup
    largo cuyo nivel objetivo ya ha quedado por debajo del precio no tiene
    nada que ofrecer, y forzarlo seria fabricar un objetivo.
    """
    entry = ctx.close
    if stop is None:
        stop = entry - ctx.stop_distance
    if stop <= 0 or stop >= entry or target <= entry:
        return None
    return SetupSignal(
        setup=name,
        entry=entry,
        stop=stop,
        target=target,
        reasons=reasons,
        features=features,
    )
