"""Generador de candidatos (informe seccion 1.3[5]).

Es la pieza que convierte "hay una senyal en este grafico" en "esto es una
operacion concreta con entrada, stop y objetivo, y merece que alguien la mire".

CUATRO PUERTAS, EN ESTE ORDEN, y cada una descarta por su cuenta:

  1. **Whitelist** (regla 3, punto de validacion 2 de 5). Se repite aunque los
     filtros ya lo comprobaran: defensa en profundidad del PRD seccion 13.
  2. **Regimen.** Cada setup declara en que regimen tiene sentido. Una
     reversion en tendencia fuerte no es una reversion con mala suerte, es otra
     cosa (informe seccion 2.3[5]).
  3. **R:R minimo.** El objetivo lo pone el setup mirando el grafico; aqui se
     comprueba si la cuenta sale. Como el objetivo NO se fabrica multiplicando
     el riesgo, esta puerta descarta de verdad.
  4. **Coste** (regla 16). El objetivo tiene que valer al menos 3x el coste de
     ida y vuelta. "Asi la IA solo ve oportunidades que al menos podrian pagar
     sus comisiones."

**LOS DESCARTES SE DEVUELVEN, NO SE TIRAN.** El panel del PRD seccion 10 tiene
que poder ensenyar por que una moneda lleva un dia sin producir nada, y en la
fase 6 la lista de descartes es tan informativa como la de candidatos: si el
90 % mueren en el R:R, el problema no es la seleccion, es el disenyo.

ESTO NO DECIDE NADA. Un candidato es una propuesta. Quien decide es
`risk/engine.py`, y antes puede opinar la IA (que solo puede reducir el
tamanyo, PRD seccion 6). Aqui no se mira la cartera, ni el equity, ni los
huecos libres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from core.config import Settings
from features.indicators import atr, atr_pct
from features.regime import Regime, RegimeReading, classify
from risk.limits import Limits
from risk.types import EntryRequest, Instrument
from strategy.costs import CostModel, MissingFeeError
from strategy.setups import SetupContext, all_setups

# Abreviaturas para el `decision_id`, que tiene que caber en un log y en un
# mensaje de Telegram sin ocupar tres lineas.
_SETUP_TAG = {
    "pullback_trend": "pb",
    "range_breakout": "bo",
    "mean_reversion": "mr",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    """Una operacion propuesta, completa y trazable.

    `decision_id` nace AQUI y acompanya a esta idea hasta que se cierre la
    posicion o se descarte: candidato -> IA -> veredicto -> orden -> fill ->
    cierre (PRD seccion 13).
    """

    cid: str
    decision_id: str
    symbol: str
    setup: str
    timeframe: str
    entry: float
    stop: float
    target: float
    reward_risk: float
    cost_rt_pct: float
    spread_pct: float
    regime: Regime
    bar_ts_ms: int
    created_at: datetime
    reasons: tuple[str, ...] = ()
    features: dict[str, float] = field(default_factory=dict)

    @property
    def stop_pct(self) -> float:
        return (self.entry - self.stop) / self.entry * 100.0

    @property
    def target_pct(self) -> float:
        return (self.target - self.entry) / self.entry * 100.0

    @property
    def target_cost_ratio(self) -> float:
        if self.cost_rt_pct <= 0:
            return 0.0
        return self.target_pct / self.cost_rt_pct

    def to_entry_request(self, instrument: Instrument) -> EntryRequest:
        """Lo que el motor de riesgo necesita para juzgarlo.

        El motor NO recibe las razones ni las features: no decide con
        argumentos, decide con reglas.
        """
        return EntryRequest(
            symbol=self.symbol,
            entry_price=self.entry,
            stop_price=self.stop,
            target_price=self.target,
            setup=self.setup,
            instrument=instrument,
            decision_id=self.decision_id,
            spread_pct=self.spread_pct,
        )

    def to_prompt_dict(self) -> dict[str, Any]:
        """El bloque `candidates` del JSON que ve la IA (informe seccion 1.5).

        Numeros redondeados a proposito: el prompt gasta cuota (regla 18) y
        seis decimales de RSI no ayudan a decidir nada.
        """
        return {
            "cid": self.cid,
            "symbol": self.symbol,
            "setup": self.setup,
            "tf": self.timeframe,
            "entry": round(self.entry, 8),
            "stop": round(self.stop, 8),
            "target": round(self.target, 8),
            "rr": round(self.reward_risk, 2),
            "cost_rt_pct": round(self.cost_rt_pct, 4),
            "regime": str(self.regime),
            "reasons": list(self.reasons),
            "features": {k: round(v, 4) for k, v in self.features.items()},
        }

    def __str__(self) -> str:
        return (
            f"{self.cid} {self.symbol} {self.setup} ({self.timeframe}): "
            f"entrada {self.entry:.6g}, stop {self.stop:.6g} "
            f"(-{self.stop_pct:.2f} %), objetivo {self.target:.6g} "
            f"(+{self.target_pct:.2f} %), R:R {self.reward_risk:.2f}, "
            f"coste {self.cost_rt_pct:.3f} % = {self.target_cost_ratio:.1f}x"
        )


@dataclass(frozen=True, slots=True)
class Rejection:
    """Un setup que no llego a candidato, y por que."""

    symbol: str
    setup: str
    gate: str
    reason: str

    def __str__(self) -> str:
        return f"{self.symbol} {self.setup}: [{self.gate}] {self.reason}"


@dataclass(frozen=True, slots=True)
class Generation:
    """El resultado completo de una pasada: lo que sale y lo que no."""

    candidates: tuple[Candidate, ...] = ()
    rejections: tuple[Rejection, ...] = ()

    def best(self) -> Candidate | None:
        """El de mejor R:R. Es lo que usa el baseline sin IA."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.reward_risk)


def make_decision_id(symbol: str, setup: str, bar_ts_ms: int) -> str:
    """Identificador estable de una idea.

    Sale de (vela, simbolo, setup) y no de un aleatorio ni del reloj: un setup
    produce como mucho una senyal por simbolo y por vela, asi que la
    combinacion ya es unica, y ademas se puede reconstruir a mano mirando el
    grafico. Si el proceso se reinicia y vuelve a mirar la misma vela, sale el
    mismo id en vez de duplicar la idea con otro nombre.
    """
    moment = datetime.fromtimestamp(bar_ts_ms / 1000, tz=UTC)
    stamp = moment.strftime("%Y%m%dT%H%M")
    base = symbol.split("/")[0].lower()
    tag = _SETUP_TAG.get(setup, setup[:2])
    return f"d-{stamp}-{base}-{tag}"


def generate_for_symbol(
    symbol: str,
    timeframe: str,
    candles: pd.DataFrame,
    spread_pct: float,
    cost: CostModel,
    limits: Limits,
    settings: Settings,
    *,
    now: datetime,
    regime: RegimeReading | None = None,
) -> Generation:
    """Pasa un simbolo por los tres setups y devuelve lo que sobreviva.

    `candles` trae SOLO velas cerradas del timeframe pedido, en orden.
    """
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []

    def reject(setup_name: str, gate: str, reason: str) -> None:
        rejections.append(Rejection(symbol, setup_name, gate, reason))

    # Puerta 1: regla 3, segundo punto de validacion.
    if symbol not in settings.whitelist:
        reject("*", "whitelist", f"{symbol} no esta en la whitelist")
        return Generation(rejections=tuple(rejections))

    try:
        multiple = settings.strategy.stop_multiple(timeframe)
    except ValueError as exc:
        reject("*", "configuracion", str(exc))
        return Generation(rejections=tuple(rejections))

    reading = regime if regime is not None else classify(candles)
    if not reading.is_known:
        reject("*", "regimen", f"regimen no clasificable: {reading.detail}")
        return Generation(rejections=tuple(rejections))

    atr_now = float(atr(candles["high"], candles["low"], candles["close"]).iloc[-1])
    atr_pct_now = float(
        atr_pct(candles["high"], candles["low"], candles["close"]).iloc[-1]
    )
    if atr_now != atr_now or atr_now <= 0:
        reject("*", "datos", "ATR sin calentamiento suficiente")
        return Generation(rejections=tuple(rejections))

    # El coste se pide una vez por simbolo, no una por setup.
    try:
        minimum_target_pct = cost.min_target_pct(
            symbol, spread_pct, ratio=limits.min_target_cost_ratio
        )
    except MissingFeeError as exc:
        reject("*", "coste", str(exc))
        return Generation(rejections=tuple(rejections))

    bar_ts_ms = int(candles["ts_open_ms"].iloc[-1]) if "ts_open_ms" in candles else 0

    ctx = SetupContext(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        regime=reading,
        atr=atr_now,
        atr_pct=atr_pct_now,
        atr_multiple=multiple,
    )

    for name, regimes, detect in all_setups():
        # Puerta 2a: el slider decide que setups estan disponibles hoy.
        if name not in limits.allowed_setups:
            reject(
                name, "slider",
                f"el nivel {limits.slider_level} del slider solo permite "
                f"{sorted(limits.allowed_setups)}",
            )
            continue

        # Puerta 2b: el regimen en el que este setup tiene sentido.
        if reading.regime not in regimes:
            reject(
                name, "regimen",
                f"regimen {reading.regime}, y este setup solo opera en "
                f"{sorted(str(r) for r in regimes)}",
            )
            continue

        signal = detect(ctx)
        if signal is None:
            reject(name, "senyal", "no se cumplen las condiciones del setup")
            continue

        # Puerta 3: R:R minimo, contra un objetivo que sale del grafico.
        if signal.reward_risk < settings.strategy.min_reward_risk:
            reject(
                name, "R:R",
                f"objetivo a {signal.target_pct:.2f} % con stop a "
                f"{signal.stop_pct:.2f} % da R:R {signal.reward_risk:.2f}, "
                f"y hace falta {settings.strategy.min_reward_risk}",
            )
            continue

        # Puerta 4: regla 16. El objetivo tiene que pagar 3x el coste.
        if signal.target_pct < minimum_target_pct:
            breakdown = cost.round_trip(
                symbol, spread_pct, exit_move_pct=signal.target_pct
            )
            reject(
                name, "coste",
                f"objetivo {signal.target_pct:.3f} % no llega a "
                f"{limits.min_target_cost_ratio}x el coste "
                f"({breakdown.total_pct:.3f} %); hacen falta "
                f"{minimum_target_pct:.3f} %",
            )
            continue

        breakdown = cost.round_trip(
            symbol, spread_pct, exit_move_pct=signal.target_pct
        )
        decision_id = make_decision_id(symbol, name, bar_ts_ms)
        candidates.append(
            Candidate(
                cid=decision_id,
                decision_id=decision_id,
                symbol=symbol,
                setup=name,
                timeframe=timeframe,
                entry=signal.entry,
                stop=signal.stop,
                target=signal.target,
                reward_risk=signal.reward_risk,
                cost_rt_pct=breakdown.total_pct,
                spread_pct=spread_pct,
                regime=reading.regime,
                bar_ts_ms=bar_ts_ms,
                created_at=now,
                reasons=signal.reasons,
                features={**signal.features, "spread_pct": spread_pct},
            )
        )

    return Generation(tuple(candidates), tuple(rejections))


def generate_all(
    market: dict[str, pd.DataFrame],
    spreads: dict[str, float],
    timeframe: str,
    cost: CostModel,
    limits: Limits,
    settings: Settings,
    *,
    now: datetime,
) -> Generation:
    """Una pasada sobre varios simbolos. `market` ya viene cribado por filtros."""
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []
    for symbol in sorted(market):
        result = generate_for_symbol(
            symbol,
            timeframe,
            market[symbol],
            spreads.get(symbol, 0.0),
            cost,
            limits,
            settings,
            now=now,
        )
        candidates.extend(result.candidates)
        rejections.extend(result.rejections)
    return Generation(tuple(candidates), tuple(rejections))
