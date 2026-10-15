"""Filtros deterministas, antes de gastar una llamada a la IA (informe 1.3[4]).

PARA QUE SIRVE ESTA CAPA. La regla 18 da 40 llamadas a Claude al dia y 8 por
ventana de 5 h. Con 8 monedas y varios setups, preguntarle por todo agotaria la
cuota en una manyana y la mayoria de las preguntas serian sobre monedas que el
motor de riesgo iba a vetar de todos modos. Estos filtros tiran esas monedas
antes, con codigo y sin gastar nada.

**ESTO NO ES UNA CAPA DE SEGURIDAD, Y ES IMPORTANTE NO CONFUNDIRLO.** La
autoridad es `risk/engine.py` y solo el. Un fallo aqui puede costar
oportunidades (descartar algo que era bueno), nunca dinero: lo que pase este
filtro vuelve a pasar por las 19 reglas enteras. Por eso aqui se puede ser
aproximado donde alli hay que ser exacto. Si algun dia alguien quiere mover una
comprobacion de riesgo a este modulo "para no repetirla", la respuesta es no:
la defensa en profundidad del PRD seccion 13 pide justo lo contrario.

Se evaluan TODOS los filtros, sin cortocircuito, por el mismo motivo que en el
motor de riesgo: cuando una moneda no genera candidatos en todo el dia, quieres
ver las cuatro razones, no la primera.

LOS DOS UMBRALES DE ATR NO SON NUMEROS A OJO, SE DEDUCEN:

  * **Suelo** (demasiado quieta): el objetivo de un setup es
    `multiplo_atr x ATR% x R:R`. Si eso no llega a 3x el coste de ida y vuelta,
    la operacion no paga sus comisiones ni saliendo bien, asi que la moneda no
    sirve *hoy*. El suelo sale de despejar ATR% de esa desigualdad.
  * **Techo** (demasiado violenta): con riesgo fijo, un stop mas ancho da una
    posicion mas pequenya (`nocional = riesgo / distancia_al_stop`). Pasado
    cierto ATR la posicion cae por debajo del minimo por orden del instrumento
    y la orden no existe. En BTC ese minimo son 8,58 $ (medido el 22/09/2026),
    el mas alto de la whitelist con diferencia, asi que BTC es el primero al
    que le aprieta.

Los dos dependen del simbolo, del precio y del spread del momento, que es por
lo que se calculan en cada pasada en vez de vivir en `settings.yaml`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.config import Settings
from risk.limits import Limits
from risk.state import RiskState
from risk.types import Instrument
from strategy.costs import CostModel, MissingFeeError

# Profundidad minima hasta 0,5 % del precio, en veces el tamanyo de la orden
# (informe seccion 1.3[4]). Es tambien lo que sostiene la suposicion de impacto
# cero de `strategy/costs.py`: si se baja este numero, aquel modelo se queda
# corto.
DEPTH_MULTIPLE = 20.0


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Lo que hace falta saber de un simbolo para decidir si merece mirarlo.

    Sin I/O y sin reloj, igual que `RiskState`: quien lo construye ya ha leido
    la base de datos y el libro. Asi los filtros se prueban con cualquier
    situacion sin montar nada.
    """

    symbol: str
    price: float
    spread_pct: float
    # Profundidad hasta 0,5 % del medio, en dolares, por el lado que peor este.
    depth_usd: float
    # ATR% del timeframe primario, ya calculado sobre velas CERRADAS.
    atr_pct: float
    timeframe: str = "4h"
    # Si las fuentes de datos de este simbolo estan frescas (`source_health`).
    data_fresh: bool = True
    stale_reason: str = ""


@dataclass(frozen=True, slots=True)
class FilterResult:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "OK " if self.passed else "NO "
        return f"[{mark}] {self.name}: {self.detail}"


@dataclass(frozen=True, slots=True)
class Screening:
    """Resultado completo de pasar un simbolo por todos los filtros."""

    symbol: str
    results: tuple[FilterResult, ...]
    atr_min_pct: float = 0.0
    atr_max_pct: float = 0.0

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def rejections(self) -> tuple[FilterResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def reason(self) -> str:
        if self.passed:
            return "apto"
        return "; ".join(f"{r.name}: {r.detail}" for r in self.rejections)

    def __str__(self) -> str:
        head = "APTO" if self.passed else "DESCARTADO"
        lines = [f"{self.symbol}: {head}"]
        lines += [f"  {r}" for r in self.results if not r.passed]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Los umbrales de ATR, deducidos
# --------------------------------------------------------------------------


def atr_floor_pct(
    snapshot: MarketSnapshot,
    cost: CostModel,
    lim: Limits,
    cfg: Settings,
) -> float:
    """ATR% minimo para que el objetivo del setup pague 3x el coste.

        objetivo = multiplo_atr x ATR% x R:R  >=  ratio x coste
        ATR%     >= objetivo_minimo / (multiplo_atr x R:R)
    """
    minimum_target = cost.min_target_pct(
        snapshot.symbol, snapshot.spread_pct, ratio=lim.min_target_cost_ratio
    )
    multiple = cfg.strategy.stop_multiple(snapshot.timeframe)
    return minimum_target / (multiple * cfg.strategy.min_reward_risk)


def atr_ceiling_pct(
    snapshot: MarketSnapshot,
    instrument: Instrument,
    lim: Limits,
    cfg: Settings,
) -> float:
    """ATR% maximo antes de que la posicion no llegue al minimo por orden.

        nocional = riesgo / (stop% / 100)  >=  minimo_por_orden
        stop%    <= 100 x riesgo / minimo_por_orden
        ATR%     <= stop% / multiplo_atr
    """
    minimum_notional = instrument.min_notional_usd(snapshot.price)
    if minimum_notional <= 0:
        return float("inf")
    widest_stop_pct = 100.0 * lim.risk_per_trade_usd / minimum_notional
    return widest_stop_pct / cfg.strategy.stop_multiple(snapshot.timeframe)


# --------------------------------------------------------------------------
# Los filtros
# --------------------------------------------------------------------------

FilterFn = Callable[..., FilterResult]
_REGISTRY: list[tuple[str, FilterFn]] = []


def _filter(name: str):
    def decorator(fn: FilterFn) -> FilterFn:
        _REGISTRY.append((name, fn))
        return fn

    return decorator


def all_filters() -> list[tuple[str, FilterFn]]:
    return list(_REGISTRY)


def _ok(name: str, detail: str = "") -> FilterResult:
    return FilterResult(name, True, detail)


def _no(name: str, detail: str) -> FilterResult:
    return FilterResult(name, False, detail)


@dataclass(frozen=True, slots=True)
class _Context:
    """Todo lo que un filtro puede mirar. Ni una cosa mas."""

    snapshot: MarketSnapshot
    state: RiskState
    limits: Limits
    settings: Settings
    cost: CostModel
    instrument: Instrument | None = None
    atr_min_pct: float = 0.0
    atr_max_pct: float = float("inf")
    cost_known: bool = True
    cost_error: str = ""


@_filter("whitelist")
def filter_whitelist(ctx: _Context) -> FilterResult:
    """Regla 3, punto de validacion 2 de 5: el generador de candidatos."""
    if ctx.snapshot.symbol not in ctx.settings.whitelist:
        return _no("whitelist", f"{ctx.snapshot.symbol} no esta en la whitelist")
    return _ok("whitelist", ctx.snapshot.symbol)


@_filter("modo")
def filter_mode(ctx: _Context) -> FilterResult:
    """Solo `NORMAL` abre (PRD seccion 5).

    Se comprueba aqui ademas de en el motor para no gastar cuota de Claude
    analizando candidatos que no se podrian abrir de ninguna manera.
    """
    if not ctx.state.mode.can_open:
        return _no("modo", f"en {ctx.state.mode} no se abren posiciones")
    return _ok("modo", str(ctx.state.mode))


@_filter("frescura")
def filter_freshness(ctx: _Context) -> FilterResult:
    """Sin datos frescos no se decide nada (informe seccion 1.3[1]).

    Un ATR o un spread calculados sobre datos viejos no describen el mercado de
    ahora, y un candidato construido con ellos es peor que ningun candidato.
    """
    if not ctx.snapshot.data_fresh:
        return _no("frescura", ctx.snapshot.stale_reason or "fuentes no frescas")
    if ctx.snapshot.atr_pct != ctx.snapshot.atr_pct:  # NaN
        return _no("frescura", "ATR sin calentamiento suficiente (NaN)")
    if ctx.snapshot.price <= 0:
        return _no("frescura", f"precio no valido: {ctx.snapshot.price}")
    return _ok("frescura", "datos al dia")


@_filter("coste conocido")
def filter_cost_known(ctx: _Context) -> FilterResult:
    """Sin comisiones no hay candidato (ver `strategy/costs.py`)."""
    if not ctx.cost_known:
        return _no("coste conocido", ctx.cost_error)
    return _ok("coste conocido", "comisiones leidas del exchange")


@_filter("spread")
def filter_spread(ctx: _Context) -> FilterResult:
    """Regla 16, primera mitad. El spread es el coste dominante con 15 $."""
    spread = ctx.snapshot.spread_pct
    if spread > ctx.limits.max_entry_spread_pct:
        return _no(
            "spread",
            f"{spread:.4f} % > {ctx.limits.max_entry_spread_pct} %",
        )
    return _ok("spread", f"{spread:.4f} %")


@_filter("profundidad")
def filter_depth(ctx: _Context) -> FilterResult:
    """Profundidad hasta 0,5 % >= 20x el tamanyo de la orden (informe 1.3[4]).

    Se mide contra el nocional OBJETIVO, no contra el real: el real depende del
    stop del candidato, que todavia no existe cuando corre este filtro.
    """
    needed = DEPTH_MULTIPLE * ctx.limits.target_notional_usd
    if ctx.snapshot.depth_usd < needed:
        return _no(
            "profundidad",
            f"{ctx.snapshot.depth_usd:.0f} $ hasta 0,5 %, hacen falta "
            f"{needed:.0f} $ ({DEPTH_MULTIPLE:.0f}x "
            f"{ctx.limits.target_notional_usd:.0f} $)",
        )
    return _ok(
        "profundidad",
        f"{ctx.snapshot.depth_usd:.0f} $ = "
        f"{ctx.snapshot.depth_usd / ctx.limits.target_notional_usd:.0f}x la orden",
    )


@_filter("atr")
def filter_atr(ctx: _Context) -> FilterResult:
    """Ni demasiado quieta para pagar comisiones ni demasiado violenta."""
    if not ctx.cost_known:
        return _no("atr", "sin coste no se puede calcular el suelo de ATR")
    atr = ctx.snapshot.atr_pct
    if atr < ctx.atr_min_pct:
        return _no(
            "atr",
            f"ATR {atr:.3f} % demasiado bajo: con el multiplo de "
            f"{ctx.settings.strategy.stop_multiple(ctx.snapshot.timeframe)}x y "
            f"R:R {ctx.settings.strategy.min_reward_risk}, el objetivo no "
            f"llegaria a {ctx.limits.min_target_cost_ratio}x el coste "
            f"(minimo {ctx.atr_min_pct:.3f} %)",
        )
    if atr > ctx.atr_max_pct:
        return _no(
            "atr",
            f"ATR {atr:.3f} % demasiado alto: el stop dejaria la posicion por "
            f"debajo del minimo por orden (maximo {ctx.atr_max_pct:.3f} %)",
        )
    return _ok(
        "atr",
        f"{atr:.3f} % dentro de [{ctx.atr_min_pct:.3f} %, {ctx.atr_max_pct:.3f} %]",
    )


@_filter("evento")
def filter_event(ctx: _Context) -> FilterResult:
    """Noticia critica, listado/deslistado, hackeo (informe secciones 1.3[4] y 3.4).

    Las banderas las pone quien lea las noticias: `features.news.event_flags`
    (docs/diseno-noticias.md), que se enchufa entre la fase 3 y la 6. Sin fuente
    de noticias, este filtro no ve nada y deja pasar: NO equivale a "no hay
    eventos", equivale a "no nos hemos enterado". En cuanto el bucle le pase
    las flags, empieza a morder solo (tests/unit/test_news_filtro.py).
    """
    flags = ctx.state.event_flags.get(ctx.snapshot.symbol, ())
    if flags:
        return _no("evento", f"eventos activos: {', '.join(flags)}")
    return _ok("evento", "sin eventos conocidos")


@_filter("hueco libre")
def filter_slot(ctx: _Context) -> FilterResult:
    """Regla 4: maximo 3 posiciones contando pendientes, y 1 por simbolo."""
    if ctx.snapshot.symbol in ctx.state.symbols_in_use:
        return _no("hueco libre", "ya hay posicion o entrada pendiente en el simbolo")
    if ctx.state.occupied_slots >= ctx.limits.max_positions:
        return _no(
            "hueco libre",
            f"{ctx.state.occupied_slots}/{ctx.limits.max_positions} huecos ocupados "
            f"(pendientes incluidas)",
        )
    return _ok(
        "hueco libre",
        f"{ctx.state.occupied_slots}/{ctx.limits.max_positions} ocupados",
    )


@_filter("correlacion")
def filter_correlation(ctx: _Context) -> FilterResult:
    """Regla 15: maximo 2 posiciones correlacionadas mas de 0,8 entre si."""
    correlated = ctx.state.correlated_with(
        ctx.snapshot.symbol, ctx.limits.correlation_threshold
    )
    if len(correlated) >= ctx.limits.max_correlated_positions:
        return _no(
            "correlacion",
            f"ya hay {len(correlated)} posiciones correlacionadas "
            f"(> {ctx.limits.correlation_threshold}) con {ctx.snapshot.symbol}: "
            f"{', '.join(correlated)}",
        )
    return _ok("correlacion", f"{len(correlated)} correlacionadas en cartera")


@_filter("cooldown")
def filter_cooldown(ctx: _Context) -> FilterResult:
    """Regla 14: 2 h de cooldown tras un stop, 4 h de pausa tras 3 perdidas."""
    until = ctx.state.cooldown_until(
        ctx.snapshot.symbol, ctx.limits.cooldown_after_stop_hours
    )
    if until is not None and ctx.state.now < until:
        return _no("cooldown", f"en cooldown tras un stop hasta {until:%H:%M} UTC")

    paused = ctx.state.paused_until(
        ctx.limits.consecutive_losses_for_pause, ctx.limits.pause_after_losses_hours
    )
    if paused is not None and ctx.state.now < paused:
        return _no(
            "cooldown",
            f"pausa global por {ctx.state.consecutive_losses()} perdidas seguidas "
            f"hasta {paused:%H:%M} UTC",
        )
    return _ok("cooldown", "sin cooldown")


@_filter("cupo diario")
def filter_daily_quota(ctx: _Context) -> FilterResult:
    """Reglas 10 y 11: 6 operaciones y 3 $ de perdida al dia."""
    if ctx.state.trades_today >= ctx.limits.max_trades_per_day:
        return _no(
            "cupo diario",
            f"{ctx.state.trades_today}/{ctx.limits.max_trades_per_day} operaciones hoy",
        )
    loss = -ctx.state.pnl_today_usd
    if loss >= ctx.limits.daily_loss_limit_usd:
        return _no(
            "cupo diario",
            f"perdida del dia {loss:.2f} $ >= {ctx.limits.daily_loss_limit_usd} $",
        )
    return _ok(
        "cupo diario",
        f"{ctx.state.trades_today}/{ctx.limits.max_trades_per_day} operaciones, "
        f"P&L {ctx.state.pnl_today_usd:+.2f} $",
    )


@_filter("paridad de usdc")
def filter_depeg(ctx: _Context) -> FilterResult:
    """Regla 17: operando contra USDC, tu efectivo ES USDC."""
    if ctx.state.usdc_deviation_pct is None:
        return _no("paridad de usdc", "paridad de USDC desconocida")
    deviation = abs(ctx.state.usdc_deviation_pct)
    if deviation > ctx.limits.usdc_depeg_pct:
        return _no(
            "paridad de usdc",
            f"USDC desviado {ctx.state.usdc_deviation_pct:+.2f} %",
        )
    return _ok("paridad de usdc", f"desviacion {ctx.state.usdc_deviation_pct:+.3f} %")


# --------------------------------------------------------------------------
# La pasada completa
# --------------------------------------------------------------------------


def screen(
    snapshot: MarketSnapshot,
    state: RiskState,
    limits: Limits,
    settings: Settings,
    cost: CostModel,
    instrument: Instrument | None = None,
) -> Screening:
    """Pasa un simbolo por todos los filtros. No corta en el primero que falla."""
    cost_known = True
    cost_error = ""
    atr_min = 0.0
    atr_max = float("inf")

    try:
        atr_min = atr_floor_pct(snapshot, cost, limits, settings)
    except MissingFeeError as exc:
        cost_known = False
        cost_error = str(exc)
    except ValueError as exc:
        # Timeframe sin multiplo de ATR medido: es un error de configuracion,
        # no del mercado, pero tampoco se puede decidir con el.
        cost_known = False
        cost_error = str(exc)

    if instrument is not None and cost_known:
        atr_max = atr_ceiling_pct(snapshot, instrument, limits, settings)

    ctx = _Context(
        snapshot=snapshot,
        state=state,
        limits=limits,
        settings=settings,
        cost=cost,
        instrument=instrument,
        atr_min_pct=atr_min,
        atr_max_pct=atr_max,
        cost_known=cost_known,
        cost_error=cost_error,
    )

    results = tuple(fn(ctx) for _name, fn in _REGISTRY)
    return Screening(
        symbol=snapshot.symbol,
        results=results,
        atr_min_pct=atr_min,
        atr_max_pct=atr_max,
    )


def screen_all(
    snapshots: list[MarketSnapshot],
    state: RiskState,
    limits: Limits,
    settings: Settings,
    cost: CostModel,
    instruments: dict[str, Instrument] | None = None,
) -> list[Screening]:
    """Criba de una tanda. Devuelve TODOS, aptos y descartados.

    Tambien los descartados, porque el panel del PRD seccion 10 tiene que poder
    ensenyar por que una moneda lleva un dia sin generar nada.
    """
    table = instruments or {}
    return [
        screen(s, state, limits, settings, cost, table.get(s.symbol))
        for s in snapshots
    ]


def eligible(screenings: list[Screening]) -> list[str]:
    return [s.symbol for s in screenings if s.passed]
