"""Limites efectivos en un instante dado (PRD seccion 4).

`Settings` dice cuales son los limites nominales. `Limits` dice cuales estan
VIGENTES ahora mismo, que no es lo mismo: los escalones de drawdown (regla 9)
y el slider de agresividad los modulan.

Es un objeto congelado y sin I/O: se construye, se lee y se tira. Eso permite
testear el motor de riesgo con cualquier combinacion de limites sin montar nada.

IMPORTANTE: este modulo no importa nada de `ai/`. El motor de riesgo tiene que
seguir funcionando cuando la IA no esta (PRD seccion 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import Settings

# Setups del informe seccion 1.3[5]. Van como TEXTO, no importando
# `strategy.setups`: el motor de riesgo no depende de la capa de estrategia,
# igual que no depende de la IA. Un test comprueba que estos nombres siguen
# coincidiendo con los setups que existen de verdad, que es lo que hace segura
# la duplicacion.
SETUP_PULLBACK = "pullback_trend"
SETUP_MEAN_REVERSION = "mean_reversion"
SETUP_BREAKOUT = "range_breakout"

# Niveles del slider de agresividad (informe seccion 4.6), RECORTADOS a los
# topes duros del PRD: el informe daba 7 y 8 operaciones/dia en los niveles 4
# y 5, y la regla 11 dice 6. Manda el PRD.
#
# La columna "setups permitidos" es tambien del informe seccion 4.6: el nivel 1
# solo opera pullbacks en tendencia, el 2 anyade la reversion en rango y del 3
# en adelante estan los tres. Tiene logica: la ruptura de rango es el setup que
# mas depende de una lectura discutible del regimen (ver
# `strategy/setups/range_breakout.py`), asi que es el ultimo en entrar.
SLIDER_LEVELS: dict[int, dict[str, Any]] = {
    1: {"risk_pct": 0.50, "min_confidence": 0.70, "max_trades": 3,
        "setups": frozenset({SETUP_PULLBACK})},
    2: {"risk_pct": 0.75, "min_confidence": 0.65, "max_trades": 4,
        "setups": frozenset({SETUP_PULLBACK, SETUP_MEAN_REVERSION})},
    3: {"risk_pct": 1.00, "min_confidence": 0.60, "max_trades": 6,
        "setups": frozenset({SETUP_PULLBACK, SETUP_MEAN_REVERSION, SETUP_BREAKOUT})},
    4: {"risk_pct": 1.25, "min_confidence": 0.57, "max_trades": 6,
        "setups": frozenset({SETUP_PULLBACK, SETUP_MEAN_REVERSION, SETUP_BREAKOUT})},
    5: {"risk_pct": 1.50, "min_confidence": 0.55, "max_trades": 6,
        "setups": frozenset({SETUP_PULLBACK, SETUP_MEAN_REVERSION, SETUP_BREAKOUT})},
}


@dataclass(frozen=True, slots=True)
class Limits:
    """Los limites que aplican AHORA, ya modulados por drawdown y slider."""

    # --- capital ---
    floor_usd: float                 # regla 5 y 7
    preventive_buffer_usd: float     # regla 8

    # --- posiciones ---
    max_positions: int               # reglas 4 y 9
    max_positions_per_symbol: int    # regla 4

    # --- tamanyo ---
    risk_per_trade_pct: float        # reglas 12 y 9
    target_notional_usd: float
    max_notional_usd: float

    # --- frecuencia ---
    max_trades_per_day: int          # reglas 11 y slider
    daily_loss_limit_usd: float      # regla 10

    # --- exposicion ---
    max_exposure_pct: float          # regla 15
    max_correlated_positions: int    # regla 15
    correlation_threshold: float     # regla 15

    # --- coste ---
    max_entry_spread_pct: float      # regla 16
    min_target_cost_ratio: float     # regla 16

    # --- tiempo ---
    cooldown_after_stop_hours: float      # regla 14
    consecutive_losses_for_pause: int     # regla 14
    pause_after_losses_hours: float       # regla 14

    # --- stablecoin ---
    usdc_depeg_pct: float            # regla 17

    # --- estrategia ---
    # Que setups puede proponer el generador de candidatos hoy (informe 4.6).
    allowed_setups: frozenset[str]

    # --- trazabilidad de como se llego aqui ---
    slider_level: int
    drawdown_multiplier: float
    equity_usd: float

    @classmethod
    def for_state(
        cls, settings: Settings, equity_usd: float, slider_level: int = 3
    ) -> Limits:
        """Construye los limites vigentes para un equity y un nivel de slider.

        El orden importa: primero el slider, luego el drawdown. El drawdown solo
        puede APRETAR lo que el slider haya puesto, nunca aflojarlo, porque el
        multiplicador es <= 1 y `min()` manda.
        """
        if slider_level not in SLIDER_LEVELS:
            raise ValueError(
                f"nivel de slider invalido: {slider_level} (validos: "
                f"{sorted(SLIDER_LEVELS)})"
            )
        level = SLIDER_LEVELS[slider_level]
        risk = settings.risk

        # Regla 9: escalones de drawdown.
        tier_positions, drawdown_multiplier = settings.limits_for_equity(equity_usd)

        # Regla 12: el slider mueve el riesgo dentro de [0,5 %; 1,5 %], y la
        # configuracion ya ha validado que ese rango no se sale del PRD.
        risk_pct = level["risk_pct"]
        risk_pct = min(risk_pct, risk.risk_per_trade_max_pct)
        risk_pct = max(risk_pct, risk.risk_per_trade_min_pct)
        # Regla 9: por debajo de 45 $, el riesgo a la mitad.
        risk_pct *= drawdown_multiplier

        # Regla 11: el slider NUNCA sube el tope diario del PRD.
        max_trades = min(int(level["max_trades"]), risk.max_trades_per_day)

        return cls(
            floor_usd=settings.capital.floor_usd,
            preventive_buffer_usd=settings.capital.preventive_buffer_usd,
            max_positions=min(risk.max_positions, tier_positions),
            max_positions_per_symbol=risk.max_positions_per_symbol,
            risk_per_trade_pct=risk_pct,
            target_notional_usd=risk.target_notional_usd,
            max_notional_usd=risk.max_notional_usd,
            max_trades_per_day=max_trades,
            daily_loss_limit_usd=risk.daily_loss_limit_usd,
            max_exposure_pct=risk.max_exposure_pct,
            max_correlated_positions=risk.max_correlated_positions,
            correlation_threshold=risk.correlation_threshold,
            max_entry_spread_pct=risk.max_entry_spread_pct,
            min_target_cost_ratio=risk.min_target_cost_ratio,
            cooldown_after_stop_hours=risk.cooldown_after_stop_hours,
            consecutive_losses_for_pause=risk.consecutive_losses_for_pause,
            pause_after_losses_hours=risk.pause_after_losses_hours,
            usdc_depeg_pct=risk.usdc_depeg_pct,
            allowed_setups=level["setups"],
            slider_level=slider_level,
            drawdown_multiplier=drawdown_multiplier,
            equity_usd=equity_usd,
        )

    # --- derivados ---

    @property
    def risk_per_trade_usd(self) -> float:
        """Cuanto se pierde si la operacion salta a su stop (regla 12)."""
        return self.equity_usd * self.risk_per_trade_pct / 100.0

    @property
    def max_exposure_usd(self) -> float:
        """Regla 15."""
        return self.equity_usd * self.max_exposure_pct / 100.0

    @property
    def min_equity_after_stops_usd(self) -> float:
        """Regla 8: suelo mas colchon."""
        return self.floor_usd + self.preventive_buffer_usd
