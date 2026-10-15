"""El bucle de una pasada: filtros -> candidatos (informe seccion 1.3).

POR QUE ESTE MODULO EXISTE, y por que faltaba:

`strategy/filters.py` estaba escrito y probado, pero **no lo llamaba nadie**.
El recorrido historico iba directo al generador de candidatos y se saltaba la
capa entera. No era un agujero de seguridad —el motor de riesgo es la autoridad
y vuelve a comprobar todo lo que importa— pero si tres cosas:

  * el **filtro de profundidad** no corria nunca, y ese filtro es justamente lo
    que sostiene la suposicion de impacto de mercado cero de
    `strategy/costs.py`. Sin el, esa suposicion no la respaldaba nada;
  * el **guardian de frescura** tampoco, asi que `data_fresh` no lo ponia nadie;
  * cuando en la fase 3 entre la IA, los filtros son lo que evita quemar el
    presupuesto de llamadas de la regla 18.

Un modulo probado que no esta enchufado es peor que uno que falta: parece que
esta hecho.

EL ORDEN IMPORTA Y ES BARATO PRIMERO. Se criba con lo que cuesta poco (spread,
profundidad, huecos libres, cooldown) antes de calcular indicadores y buscar
setups, que es lo caro. Una moneda descartada por spread no necesita que se le
calcule el ADX.

**ESTO SIGUE SIN DECIDIR NADA.** Devuelve candidatos y descartes. Quien elige
es el baseline o la IA, y quien decide de verdad es `risk/engine.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from core.config import Settings
from features.context import CorrelationMatrix
from features.indicators import atr_pct
from features.regime import RegimeReading, classify
from risk.limits import Limits
from risk.state import RiskState
from risk.types import Instrument
from strategy.candidates import Candidate, Generation, Rejection, generate_for_symbol
from strategy.costs import CostModel
from strategy.filters import MarketSnapshot, Screening, screen


@dataclass(frozen=True, slots=True)
class MarketData:
    """Lo que la ingesta sabe de un simbolo en este instante.

    Es el unico punto donde entra el mundo exterior. Todo lo que hay debajo
    (filtros, regimen, setups) es funcion pura de esto.
    """

    symbol: str
    candles: pd.DataFrame        # SOLO velas cerradas, en orden
    spread_pct: float
    depth_usd: float
    data_fresh: bool = True
    stale_reason: str = ""


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Todo lo que paso en una pasada, incluido lo que no paso.

    Los descartes de las DOS capas se devuelven por separado porque responden a
    preguntas distintas: "por que no miramos esta moneda" (filtros) y "por que
    esta moneda no dio nada" (candidatos). El panel del PRD seccion 10 necesita
    poder contestar las dos.
    """

    candidates: tuple[Candidate, ...] = ()
    screenings: tuple[Screening, ...] = ()
    rejections: tuple[Rejection, ...] = ()
    regimes: dict[str, RegimeReading] = field(default_factory=dict)

    @property
    def eligible(self) -> tuple[str, ...]:
        return tuple(s.symbol for s in self.screenings if s.passed)

    @property
    def filtered_out(self) -> tuple[Screening, ...]:
        return tuple(s for s in self.screenings if not s.passed)

    def generation(self) -> Generation:
        """Lo que el baseline o la IA reciben."""
        return Generation(self.candidates, self.rejections)

    def summary(self) -> str:
        return (
            f"{len(self.eligible)}/{len(self.screenings)} monedas pasan los "
            f"filtros, {len(self.candidates)} candidato(s), "
            f"{len(self.rejections)} descarte(s)"
        )


def run(
    market: dict[str, MarketData],
    state: RiskState,
    limits: Limits,
    settings: Settings,
    cost: CostModel,
    instruments: dict[str, Instrument],
    *,
    timeframe: str,
    now: datetime,
    correlations: CorrelationMatrix | None = None,
) -> PipelineResult:
    """Una pasada completa sobre todas las monedas.

    `correlations` es opcional solo para poder probar el resto sin montarlo;
    en produccion se pasa SIEMPRE, porque sin el la mitad de correlacion de la
    regla 15 no tiene datos con los que vetar.
    """
    if correlations is not None:
        state = _with_correlations(state, correlations)

    candidates: list[Candidate] = []
    screenings: list[Screening] = []
    rejections: list[Rejection] = []
    regimes: dict[str, RegimeReading] = {}

    for symbol in sorted(market):
        data = market[symbol]
        snapshot = _snapshot(data, timeframe)
        screening = screen(
            snapshot, state, limits, settings, cost, instruments.get(symbol)
        )
        screenings.append(screening)

        # Lo caro solo se calcula para lo que ha pasado la criba barata.
        if not screening.passed:
            continue

        reading = classify(data.candles)
        regimes[symbol] = reading

        result = generate_for_symbol(
            symbol,
            timeframe,
            data.candles,
            data.spread_pct,
            cost,
            limits,
            settings,
            now=now,
            regime=reading,
        )
        candidates.extend(result.candidates)
        rejections.extend(result.rejections)

    return PipelineResult(
        candidates=tuple(candidates),
        screenings=tuple(screenings),
        rejections=tuple(rejections),
        regimes=regimes,
    )


def _snapshot(data: MarketData, timeframe: str) -> MarketSnapshot:
    """Convierte lo que sabe la ingesta en lo que miran los filtros.

    El ATR se calcula aqui y no en los filtros porque los filtros no leen
    velas: reciben numeros. Mantenerlos asi es lo que permite probarlos con
    cualquier situacion sin montar una serie de precios.
    """
    candles = data.candles
    if candles.empty:
        return MarketSnapshot(
            symbol=data.symbol,
            price=0.0,
            spread_pct=data.spread_pct,
            depth_usd=data.depth_usd,
            atr_pct=float("nan"),
            timeframe=timeframe,
            data_fresh=False,
            stale_reason="sin velas cerradas",
        )

    serie = atr_pct(candles["high"], candles["low"], candles["close"])
    return MarketSnapshot(
        symbol=data.symbol,
        price=float(candles["close"].iloc[-1]),
        spread_pct=data.spread_pct,
        depth_usd=data.depth_usd,
        atr_pct=float(serie.iloc[-1]),
        timeframe=timeframe,
        data_fresh=data.data_fresh,
        stale_reason=data.stale_reason,
    )


def _with_correlations(state: RiskState, matrix: CorrelationMatrix) -> RiskState:
    """Devuelve la misma foto con las correlaciones puestas.

    `RiskState` es inmutable a proposito, asi que se reconstruye. Es barato y
    mantiene la garantia de que nadie muta la foto que el motor esta mirando.
    """
    campos = {name: getattr(state, name) for name in state.__slots__}
    campos["correlations"] = dict(matrix.values)
    return RiskState(**campos)


# --- Por que una moneda que paso los filtros no dio candidato (panel, vista por moneda) ---------------------------

REGIMEN_CORTO = {"trend_up": "tendencia alcista", "trend_down": "tendencia bajista", "range": "mercado de lado",
                 "transition": "cambiando de tendencia", "high_vol": "muy volátil", "unknown": "sin clasificar"}
SENYAL_CORTA = {"pullback_trend": "sin retroceso a la media",
                "range_breakout": "sin ruptura del rango",
                "mean_reversion": "precio lejos del suelo del rango"}
SETUP_CORTO = {"pullback_trend": "pullback", "range_breakout": "ruptura", "mean_reversion": "reversión"}


def motivo_sin_senyal(regime: RegimeReading | None, rejections: tuple[Rejection, ...] | list[Rejection]) -> str:
    """Una frase CORTA para el panel (el propietario, 29/09): el regimen y, si algun setup opera en el, por que no dio senyal.
    Con acentos: la lee el propietario tal cual.

    Solo describe lo que ya se calculo: no cambia ninguna decision.
    """
    mercado = REGIMEN_CORTO.get(str(regime.regime), str(regime.regime)) if regime is not None else "sin régimen"
    aplicables = [r for r in rejections if r.gate != "regimen"]
    if not aplicables:
        return f"{mercado}: ningún setup opera así"
    r = aplicables[0]
    if r.gate == "senyal":
        return f"{mercado}: {SENYAL_CORTA.get(r.setup, 'sin señal')}"
    return f"{mercado}: {SETUP_CORTO.get(r.setup, r.setup)} no pasa ({r.gate})"


def filas_sin_senyal(result: PipelineResult) -> list[tuple[str, str]]:
    """(simbolo, frase) de cada moneda que paso los filtros y no dio candidato en esta pasada."""
    con_candidato = {c.symbol for c in result.candidates}
    return [(s, motivo_sin_senyal(result.regimes.get(s), [r for r in result.rejections if r.symbol == s]))
            for s in result.eligible if s not in con_candidato]
