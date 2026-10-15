"""Carga y validacion de la configuracion (PRD seccion 4).

Principio: `config/settings.yaml` solo puede ser MAS conservador que las reglas
duras del PRD. Nunca mas laxo. Si se intenta lo contrario, el bot NO ARRANCA.

Los topes del PRD viven aqui como constantes `HARD_*` y no se leen del YAML,
precisamente para que editar el YAML no pueda relajarlos.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Topes del PRD seccion 4. No configurables. Defensa en profundidad. ---
HARD_MAX_POSITIONS = 3            # regla 4
HARD_MAX_TRADES_PER_DAY = 6       # regla 11
HARD_MAX_EXPOSURE_PCT = 90.0      # regla 15
HARD_DAILY_LOSS_LIMIT_USD = 3.0   # regla 10
HARD_FLOOR_USD = 25.0             # reglas 5 y 7
HARD_INITIAL_CAPITAL_USD = 50.0   # regla 5
HARD_RISK_MIN_PCT = 0.5           # regla 12
HARD_RISK_MAX_PCT = 1.5           # regla 12
HARD_MAX_ENTRY_SPREAD_PCT = 0.10  # regla 16
HARD_MIN_TARGET_COST_RATIO = 3.0  # regla 16
HARD_WHITELIST_SIZE = 8           # regla 3
HARD_CLAUDE_CALLS_PER_DAY = 40    # regla 18
HARD_CLAUDE_CALLS_PER_5H = 8      # regla 18
HARD_QUOTE = "USDC"               # regla 3
HARD_EQUITY_INTERVAL_SECONDS = 15.0  # regla 6

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}/USDC$")

Positive = Annotated[float, Field(gt=0)]


class ConfigError(Exception):
    """Configuracion invalida. El bot no debe arrancar."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FeesConfig(_Frozen):
    """Las comisiones de la cuenta, en %. Decision del propietario del 23/09/2026.

    Las que trae ccxt (y copia la tabla `instruments`) son GENERICAS para todos
    los mercados de OKX, no las de una cuenta: 0,10 % / 0,15 %. Las de una cuenta
    solo spot de la UE, nivel Regular, son 0,10 % / 0,20 % desde el 25/09/2026
    (anuncio oficial, ver docs/hallazgos-fase-0-1.md). Con las de ccxt el coste
    de la regla 16 salia mas barato de lo real.

    Tope del 1 %: una comision de mas de eso es una errata (20 en vez de 0,20),
    no una tarifa. Y el taker nunca por debajo del maker: el modelo cuenta las
    salidas por stop como taker precisamente porque son las caras.
    """

    maker_pct: float = Field(default=0.10, gt=0, le=1.0)
    taker_pct: float = Field(default=0.20, gt=0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> FeesConfig:
        if self.taker_pct < self.maker_pct:
            raise ValueError(
                f"comisiones: taker {self.taker_pct} % por debajo del maker "
                f"{self.maker_pct} %; seria una errata"
            )
        return self

    def apply(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Las filas de `instruments` con ESTAS comisiones en vez de las de ccxt.

        El UNICO sitio por el que pasan las comisiones antes de llegar al motor
        de riesgo (`Instrument.from_row`), al modelo de costes
        (`CostModel.from_repo`) y al juez: los tres ven la misma cifra.
        """
        return [
            {**r, "maker_fee": self.maker_pct / 100, "taker_fee": self.taker_pct / 100}
            for r in rows
        ]


class ExchangeConfig(_Frozen):
    id: str = "okx"
    quote: str = HARD_QUOTE
    demo: bool = True
    # Los datos PUBLICOS son identicos en todos los hosts de OKX, pero las
    # peticiones AUTENTICADAS de una cuenta europea solo las reconoce el host
    # de la entidad europea. Con el `www.okx.com` que ccxt usa por defecto, la
    # clave responde 50119 "API key doesn't exist", un error que no da ninguna
    # pista del problema real. Medido el 22/09/2026.
    hostname: str = "eea.okx.com"
    fees: FeesConfig = FeesConfig()

    @model_validator(mode="after")
    def _check(self) -> ExchangeConfig:
        if self.id != "okx":
            raise ValueError("regla 2: el exchange debe ser okx, no " + repr(self.id))
        if self.quote != HARD_QUOTE:
            raise ValueError(
                f"regla 3: la quote debe ser {HARD_QUOTE}, no {self.quote!r}"
            )
        return self


class CapitalConfig(_Frozen):
    initial_capital_usd: Positive = HARD_INITIAL_CAPITAL_USD
    floor_usd: Positive = HARD_FLOOR_USD
    preventive_buffer_usd: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> CapitalConfig:
        if self.floor_usd >= self.initial_capital_usd:
            raise ValueError(
                f"el suelo ({self.floor_usd}) debe ser menor que el capital inicial "
                f"({self.initial_capital_usd})"
            )
        # Mas conservador = suelo mas ALTO. Nunca mas bajo que el del PRD.
        if self.floor_usd < HARD_FLOOR_USD:
            raise ValueError(
                f"regla 5/7: el suelo no puede bajar de {HARD_FLOOR_USD} $ "
                f"(se intento {self.floor_usd})"
            )
        if self.initial_capital_usd > HARD_INITIAL_CAPITAL_USD:
            raise ValueError(
                f"regla 5: el capital inicial no puede superar {HARD_INITIAL_CAPITAL_USD} $ "
                f"(se intento {self.initial_capital_usd})"
            )
        return self


class RiskConfig(_Frozen):
    risk_per_trade_pct: Positive = 1.0
    risk_per_trade_min_pct: Positive = HARD_RISK_MIN_PCT
    risk_per_trade_max_pct: Positive = HARD_RISK_MAX_PCT
    target_notional_usd: Positive = 15.0
    max_notional_usd: Positive = 20.0
    max_positions: int = Field(default=HARD_MAX_POSITIONS, ge=1)
    max_positions_per_symbol: int = Field(default=1, ge=1)
    max_trades_per_day: int = Field(default=HARD_MAX_TRADES_PER_DAY, ge=1)
    max_exposure_pct: Positive = HARD_MAX_EXPOSURE_PCT
    daily_loss_limit_usd: Positive = HARD_DAILY_LOSS_LIMIT_USD
    max_entry_spread_pct: Positive = HARD_MAX_ENTRY_SPREAD_PCT
    min_target_cost_ratio: Positive = HARD_MIN_TARGET_COST_RATIO
    max_correlated_positions: int = Field(default=2, ge=1)
    correlation_threshold: float = Field(default=0.8, gt=0, le=1)
    correlation_window_days: int = Field(default=7, ge=1)
    cooldown_after_stop_hours: float = Field(default=2.0, ge=0)
    consecutive_losses_for_pause: int = Field(default=3, ge=1)
    pause_after_losses_hours: float = Field(default=4.0, ge=0)
    usdc_depeg_pct: Positive = 1.5

    @model_validator(mode="after")
    def _check(self) -> RiskConfig:
        errors: list[str] = []
        if self.max_positions > HARD_MAX_POSITIONS:
            errors.append(
                f"regla 4: max_positions no puede pasar de {HARD_MAX_POSITIONS} "
                f"(se intento {self.max_positions})"
            )
        if self.max_positions_per_symbol > 1:
            errors.append(
                "regla 4: max_positions_per_symbol debe ser 1 (prohibido promediar a la baja)"
            )
        if self.max_trades_per_day > HARD_MAX_TRADES_PER_DAY:
            errors.append(
                f"regla 11: max_trades_per_day no puede pasar de {HARD_MAX_TRADES_PER_DAY} "
                f"(se intento {self.max_trades_per_day})"
            )
        if self.max_exposure_pct > HARD_MAX_EXPOSURE_PCT:
            errors.append(
                f"regla 15: max_exposure_pct no puede pasar de {HARD_MAX_EXPOSURE_PCT} "
                f"(se intento {self.max_exposure_pct})"
            )
        if self.daily_loss_limit_usd > HARD_DAILY_LOSS_LIMIT_USD:
            errors.append(
                f"regla 10: daily_loss_limit_usd no puede pasar de "
                f"{HARD_DAILY_LOSS_LIMIT_USD} $ (se intento {self.daily_loss_limit_usd})"
            )
        if self.max_entry_spread_pct > HARD_MAX_ENTRY_SPREAD_PCT:
            errors.append(
                f"regla 16: max_entry_spread_pct no puede pasar de "
                f"{HARD_MAX_ENTRY_SPREAD_PCT} (se intento {self.max_entry_spread_pct})"
            )
        if self.min_target_cost_ratio < HARD_MIN_TARGET_COST_RATIO:
            errors.append(
                f"regla 16: min_target_cost_ratio no puede bajar de "
                f"{HARD_MIN_TARGET_COST_RATIO} (se intento {self.min_target_cost_ratio})"
            )
        if self.risk_per_trade_min_pct < HARD_RISK_MIN_PCT:
            errors.append(
                f"regla 12: el riesgo minimo no puede bajar de {HARD_RISK_MIN_PCT} %"
            )
        if self.risk_per_trade_max_pct > HARD_RISK_MAX_PCT:
            errors.append(
                f"regla 12: el riesgo maximo no puede pasar de {HARD_RISK_MAX_PCT} %"
            )
        if self.risk_per_trade_min_pct > self.risk_per_trade_max_pct:
            errors.append("regla 12: el riesgo minimo no puede superar al maximo")
        elif not (
            self.risk_per_trade_min_pct
            <= self.risk_per_trade_pct
            <= self.risk_per_trade_max_pct
        ):
            errors.append(
                f"regla 12: risk_per_trade_pct ({self.risk_per_trade_pct}) fuera del rango "
                f"[{self.risk_per_trade_min_pct}, {self.risk_per_trade_max_pct}]"
            )
        if self.target_notional_usd > self.max_notional_usd:
            errors.append(
                f"target_notional_usd ({self.target_notional_usd}) no puede superar "
                f"max_notional_usd ({self.max_notional_usd})"
            )
        if self.max_correlated_positions > self.max_positions:
            errors.append("max_correlated_positions no puede superar max_positions")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class DrawdownTier(_Frozen):
    """Regla 9. Un escalon: por debajo de X $ se aplican estos limites."""

    equity_below_usd: Positive
    risk_multiplier: float = Field(default=1.0, gt=0, le=1.0)
    max_positions: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> DrawdownTier:
        if self.max_positions is not None and self.max_positions > HARD_MAX_POSITIONS:
            raise ValueError(
                f"reglas 4 y 9: max_positions del escalon no puede pasar de "
                f"{HARD_MAX_POSITIONS}"
            )
        return self


class ClaudeConfig(_Frozen):
    max_calls_per_day: int = Field(default=HARD_CLAUDE_CALLS_PER_DAY, ge=1)
    max_calls_per_5h_window: int = Field(default=HARD_CLAUDE_CALLS_PER_5H, ge=1)
    timeout_seconds: Positive = 90.0
    model: str = "sonnet"
    # Cuando caduca el token (CLAUDE_CODE_OAUTH_TOKEN) para avisar 14 dias antes
    # (PRD seccion 6). El token no lo dice: sale de cuando se genero mas un anyo.
    # None = no se avisa.
    token_expires_on: date | None = None

    @model_validator(mode="after")
    def _check(self) -> ClaudeConfig:
        if self.max_calls_per_day > HARD_CLAUDE_CALLS_PER_DAY:
            raise ValueError(
                f"regla 18: max_calls_per_day no puede pasar de {HARD_CLAUDE_CALLS_PER_DAY}"
            )
        if self.max_calls_per_5h_window > HARD_CLAUDE_CALLS_PER_5H:
            raise ValueError(
                f"regla 18: max_calls_per_5h_window no puede pasar de "
                f"{HARD_CLAUDE_CALLS_PER_5H}"
            )
        if self.max_calls_per_5h_window > self.max_calls_per_day:
            raise ValueError(
                "regla 18: el tope por ventana de 5 h no puede superar al diario"
            )
        return self


class StalenessConfig(_Frozen):
    """Informe seccion 1.3[1]: umbrales del detector de datos obsoletos."""

    ticker_seconds: Positive = 30.0
    candle_1m_seconds: Positive = 90.0
    orderbook_seconds: Positive = 60.0


class PersistConfig(_Frozen):
    l1_interval_seconds: Positive = 5.0
    book_metrics_interval_seconds: Positive = 10.0


class DataConfig(_Frozen):
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")
    feature_timeframes: tuple[str, ...] = ("5m", "15m", "1h", "4h")
    primary_timeframe: str = "4h"
    backfill_candles: int = Field(default=300, ge=1, le=1500)
    orderbook_depth: int = Field(default=20, ge=5, le=400)
    staleness: StalenessConfig = StalenessConfig()
    persist: PersistConfig = PersistConfig()
    equity_interval_seconds: Positive = HARD_EQUITY_INTERVAL_SECONDS
    reconcile_interval_seconds: Positive = 300.0
    clock_skew_max_seconds: Positive = 2.0

    @model_validator(mode="after")
    def _check(self) -> DataConfig:
        if not self.timeframes:
            raise ValueError("data.timeframes no puede estar vacio")
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError("data.timeframes tiene duplicados")
        missing = set(self.feature_timeframes) - set(self.timeframes)
        if missing:
            raise ValueError(
                f"feature_timeframes que no se ingieren: {sorted(missing)}"
            )
        if self.primary_timeframe not in self.feature_timeframes:
            raise ValueError(
                f"primary_timeframe {self.primary_timeframe!r} no esta en feature_timeframes"
            )
        # regla 6: el equity se calcula cada 15 s. Mas lento la incumple.
        if self.equity_interval_seconds > HARD_EQUITY_INTERVAL_SECONDS:
            raise ValueError(
                f"regla 6: el equity debe calcularse al menos cada "
                f"{HARD_EQUITY_INTERVAL_SECONDS} s (se intento "
                f"{self.equity_interval_seconds})"
            )
        return self


class StrategyConfig(_Frozen):
    """Parametros de los setups. El multiplo de ATR esta MEDIDO, no elegido."""

    atr_multiple: dict[str, float] = Field(default_factory=lambda: {"4h": 1.9, "1h": 3.3})
    min_reward_risk: Positive = 2.0

    @model_validator(mode="after")
    def _check(self) -> StrategyConfig:
        if not self.atr_multiple:
            raise ValueError("strategy.atr_multiple no puede estar vacio")
        for timeframe, multiple in self.atr_multiple.items():
            if multiple <= 0:
                raise ValueError(
                    f"multiplo de ATR no positivo en {timeframe}: {multiple}"
                )
        return self

    def stop_multiple(self, timeframe: str) -> float:
        try:
            return self.atr_multiple[timeframe]
        except KeyError:
            raise ValueError(
                f"sin multiplo de ATR para {timeframe!r}; medidos: "
                f"{sorted(self.atr_multiple)}"
            ) from None


class StorageConfig(_Frozen):
    db_path: str = "var/ploutos.db"


class LoggingConfig(_Frozen):
    level: str = "INFO"
    file: str | None = "var/ploutos.log"


class Settings(_Frozen):
    whitelist: tuple[str, ...]
    exchange: ExchangeConfig = ExchangeConfig()
    capital: CapitalConfig = CapitalConfig()
    risk: RiskConfig = RiskConfig()
    drawdown_tiers: tuple[DrawdownTier, ...] = ()
    claude: ClaudeConfig = ClaudeConfig()
    data: DataConfig = DataConfig()
    strategy: StrategyConfig = StrategyConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()

    @model_validator(mode="after")
    def _check(self) -> Settings:
        errors: list[str] = []
        errors += self._check_whitelist()
        errors += self._check_coherence()
        errors += self._check_drawdown_tiers()
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def _check_whitelist(self) -> list[str]:
        """Regla 3, punto de validacion 1 de 4: al arrancar."""
        errors: list[str] = []
        if len(self.whitelist) != HARD_WHITELIST_SIZE:
            errors.append(
                f"regla 3: la whitelist debe tener exactamente {HARD_WHITELIST_SIZE} "
                f"simbolos, tiene {len(self.whitelist)}"
            )
        dupes = sorted({s for s in self.whitelist if self.whitelist.count(s) > 1})
        if dupes:
            errors.append(f"regla 3: simbolos duplicados en la whitelist: {dupes}")
        bad = [s for s in self.whitelist if not SYMBOL_RE.match(s)]
        if bad:
            errors.append(f"regla 3: simbolos que no son X/{HARD_QUOTE}: {bad}")
        return errors

    def _check_coherence(self) -> list[str]:
        """Los limites tienen que ser compatibles entre si, no solo validos por separado."""
        errors: list[str] = []
        max_exposure = (
            self.capital.initial_capital_usd * self.risk.max_exposure_pct / 100.0
        )
        planned = self.risk.max_positions * self.risk.target_notional_usd
        if planned > max_exposure + 1e-9:
            errors.append(
                f"incoherencia: {self.risk.max_positions} posiciones x "
                f"{self.risk.target_notional_usd} $ = {planned} $ supera la exposicion "
                f"maxima ({max_exposure} $ = {self.risk.max_exposure_pct} % de "
                f"{self.capital.initial_capital_usd} $)"
            )
        floor_plus_buffer = self.capital.floor_usd + self.capital.preventive_buffer_usd
        if floor_plus_buffer >= self.capital.initial_capital_usd:
            errors.append(
                f"incoherencia: suelo + colchon preventivo ({floor_plus_buffer} $) no deja "
                f"margen bajo el capital inicial ({self.capital.initial_capital_usd} $)"
            )
        return errors

    def _check_drawdown_tiers(self) -> list[str]:
        """Regla 9: escalones monotonos, por encima del suelo y que nunca relajen."""
        errors: list[str] = []
        levels = [t.equity_below_usd for t in self.drawdown_tiers]
        if levels != sorted(levels, reverse=True):
            errors.append(
                f"regla 9: los escalones deben ir de mayor a menor equity, son {levels}"
            )
        for tier in self.drawdown_tiers:
            if tier.equity_below_usd <= self.capital.floor_usd:
                errors.append(
                    f"regla 9: el escalon de {tier.equity_below_usd} $ esta en o por debajo "
                    f"del suelo ({self.capital.floor_usd} $), seria inalcanzable"
                )
        prev_positions = HARD_MAX_POSITIONS
        prev_multiplier = 1.0
        for tier in self.drawdown_tiers:
            if tier.max_positions is not None:
                if tier.max_positions > prev_positions:
                    errors.append(
                        f"regla 9: el escalon de {tier.equity_below_usd} $ RELAJA el limite "
                        f"de posiciones ({prev_positions} -> {tier.max_positions})"
                    )
                prev_positions = tier.max_positions
            if tier.risk_multiplier > prev_multiplier:
                errors.append(
                    f"regla 9: el escalon de {tier.equity_below_usd} $ RELAJA el riesgo "
                    f"({prev_multiplier} -> {tier.risk_multiplier})"
                )
            prev_multiplier = tier.risk_multiplier
        return errors

    # --- utilidades ---

    def is_whitelisted(self, symbol: str) -> bool:
        """Regla 3. Se llama desde los 4 puntos de validacion."""
        return symbol in self.whitelist

    def base_of(self, symbol: str) -> str:
        return symbol.split("/")[0]

    def limits_for_equity(self, equity_usd: float) -> tuple[int, float]:
        """Regla 9: limites efectivos para un equity dado.

        Devuelve (max_positions, risk_multiplier), aplicando el escalon mas
        restrictivo que ese equity active.
        """
        max_positions = self.risk.max_positions
        risk_multiplier = 1.0
        for tier in self.drawdown_tiers:
            if equity_usd < tier.equity_below_usd:
                if tier.max_positions is not None:
                    max_positions = min(max_positions, tier.max_positions)
                risk_multiplier = min(risk_multiplier, tier.risk_multiplier)
        return max_positions, risk_multiplier


# Ruta por defecto ABSOLUTA, sacada de donde vive este fichero.
#
# Antes era relativa ("config/settings.yaml") y por tanto dependia del
# directorio desde el que se lanzara el proceso. Con systemd no se notaba
# porque la unidad fija `WorkingDirectory`, pero cualquier invocacion manual
# desde otro sitio fallaba con un `PermissionError` sobre una ruta relativa,
# que no dice nada de la causa real. La configuracion del bot no deberia
# depender de desde donde lo arranques.
DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"


def load_settings(path: str | Path | None = None) -> Settings:
    """Carga y valida la configuracion. Lanza ConfigError si es invalida.

    Que esto lance significa que el bot NO ARRANCA. Es deliberado (PRD seccion 4).
    """
    p = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
    if not p.is_file():
        raise ConfigError(f"no existe el fichero de configuracion: {p}")
    try:
        raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalido en {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{p} debe contener un mapa en la raiz, contiene {type(raw).__name__}"
        )
    try:
        return Settings.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"configuracion invalida en {p}: {exc}") from exc
