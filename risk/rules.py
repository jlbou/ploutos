"""Las 19 reglas duras del PRD seccion 4, una funcion por regla.

Cada funcion recibe la misma foto y devuelve un `RuleResult`. Ninguna hace I/O,
ninguna consulta el reloj, ninguna importa nada de `ai/`.

Se evaluan TODAS, siempre, sin cortocircuito: si una entrada viola cinco reglas,
queremos ver las cinco. El panel del PRD seccion 10 ensenya por que se bloqueo
algo, y "por la primera que fallo" no es la respuesta completa.

Las reglas que no se pueden juzgar desde una peticion de entrada (la 2 y la 19,
que son de configuracion y de credenciales) se comprueban en otro sitio y aqui
devuelven un resultado informativo, para que el recuento siga siendo 19 y no
haya que recordar cuales faltan.
"""

from __future__ import annotations

from collections.abc import Callable

from core.config import SYMBOL_RE, Settings
from core.modes import Mode
from risk.limits import Limits
from risk.state import RiskState
from risk.types import EntryRequest, RuleResult

RuleFn = Callable[[EntryRequest, RiskState, Limits, Settings], RuleResult]

_REGISTRY: list[tuple[int, str, RuleFn]] = []


def rule(number: int, name: str):
    """Registra una regla para que el motor las recorra todas."""

    def decorator(fn: RuleFn) -> RuleFn:
        _REGISTRY.append((number, name, fn))
        return fn

    return decorator


def all_rules() -> list[tuple[int, str, RuleFn]]:
    return sorted(_REGISTRY, key=lambda item: item[0])


def _ok(n: int, name: str, detail: str = "") -> RuleResult:
    return RuleResult(n, name, True, detail)


def _veto(n: int, name: str, detail: str) -> RuleResult:
    return RuleResult(n, name, False, detail)


# --------------------------------------------------------------------------
# 1. Sin apalancamiento
# --------------------------------------------------------------------------
@rule(1, "sin apalancamiento")
def rule_01(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Solo spot, solo largos. No hay forma de pedir corto en este motor
    (`Side` solo tiene LONG), asi que aqui se comprueba lo unico que podria
    colarse: que la entrada se pague con dinero que existe."""
    needed = req.entry_price * 1e-12  # coherencia minima
    if req.entry_price <= needed:
        return _veto(1, "sin apalancamiento", "precio de entrada invalido")
    if st.free_quote_usd < 0:
        return _veto(
            1, "sin apalancamiento",
            f"saldo libre negativo ({st.free_quote_usd:.2f} $): eso es deuda",
        )
    return _ok(1, "sin apalancamiento", "spot, solo largo")


# --------------------------------------------------------------------------
# 2. Exchange
# --------------------------------------------------------------------------
@rule(2, "exchange OKX")
def rule_02(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Se valida al arrancar en `core.config`. Aqui solo se confirma."""
    if cfg.exchange.id != "okx":
        return _veto(2, "exchange OKX", f"exchange {cfg.exchange.id!r}")
    return _ok(2, "exchange OKX", "okx")


# --------------------------------------------------------------------------
# 3. Whitelist de pares X/USDC  (punto de validacion 3 de 5)
# --------------------------------------------------------------------------
@rule(3, "whitelist X/USDC")
def rule_03(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if not SYMBOL_RE.match(req.symbol):
        return _veto(3, "whitelist X/USDC", f"{req.symbol} no tiene la forma X/USDC")
    if not cfg.is_whitelisted(req.symbol):
        return _veto(
            3, "whitelist X/USDC",
            f"{req.symbol} no esta en la whitelist de {len(cfg.whitelist)}",
        )
    if req.instrument.symbol != req.symbol:
        return _veto(
            3, "whitelist X/USDC",
            f"el instrumento es {req.instrument.symbol} y el simbolo {req.symbol}",
        )
    return _ok(3, "whitelist X/USDC", req.symbol)


# --------------------------------------------------------------------------
# 4. Maximo 3 posiciones, pendientes incluidas; 1 por simbolo
# --------------------------------------------------------------------------
@rule(4, "maximo de posiciones")
def rule_04(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if st.occupied_slots >= lim.max_positions:
        return _veto(
            4, "maximo de posiciones",
            f"{len(st.positions)} abiertas + {len(st.pending_entries)} pendientes "
            f"= {st.occupied_slots}, tope {lim.max_positions}",
        )
    if req.symbol in st.symbols_in_use:
        return _veto(
            4, "maximo de posiciones",
            f"ya hay posicion o pendiente en {req.symbol} "
            f"(prohibido promediar a la baja)",
        )
    return _ok(
        4, "maximo de posiciones",
        f"{st.occupied_slots}/{lim.max_positions} huecos ocupados",
    )


# --------------------------------------------------------------------------
# 5. Capital de referencia
# --------------------------------------------------------------------------
@rule(5, "capital de referencia")
def rule_05(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if lim.floor_usd < cfg.capital.floor_usd:
        return _veto(5, "capital de referencia", "el suelo vigente es menor que el configurado")
    return _ok(
        5, "capital de referencia",
        f"suelo {lim.floor_usd:.2f} $, capital inicial "
        f"{cfg.capital.initial_capital_usd:.2f} $",
    )


# --------------------------------------------------------------------------
# 6. Equity valido
# --------------------------------------------------------------------------
@rule(6, "equity valido")
def rule_06(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """El equity se calcula en `risk.equity` con datos del exchange. Aqui se
    comprueba que la foto trae un numero utilizable: decidir con un equity
    invalido es decidir a ciegas."""
    if st.equity_usd != st.equity_usd:  # NaN
        return _veto(6, "equity valido", "el equity es NaN")
    if st.equity_usd <= 0:
        return _veto(6, "equity valido", f"equity no positivo: {st.equity_usd:.2f} $")
    for symbol in (p.symbol for p in st.positions):
        if symbol not in st.marks:
            return _veto(
                6, "equity valido",
                f"sin precio de mercado para {symbol}: el equity no es fiable",
            )
    return _ok(6, "equity valido", f"{st.equity_usd:.2f} $")


# --------------------------------------------------------------------------
# 7. Suelo de 25 $ (enclavado)
# --------------------------------------------------------------------------
@rule(7, "suelo de capital")
def rule_07(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if st.mode is Mode.CLOSE_ONLY_CAPITAL:
        return _veto(
            7, "suelo de capital",
            "CLOSE_ONLY_CAPITAL activo (enclavado: solo sale con reset manual)",
        )
    if st.equity_usd <= lim.floor_usd:
        return _veto(
            7, "suelo de capital",
            f"equity {st.equity_usd:.2f} $ <= suelo {lim.floor_usd:.2f} $",
        )
    return _ok(
        7, "suelo de capital",
        f"{st.equity_usd - lim.floor_usd:.2f} $ por encima del suelo",
    )


# --------------------------------------------------------------------------
# 8. Regla preventiva
# --------------------------------------------------------------------------
@rule(8, "preventiva del suelo")
def rule_08(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """La importante: el suelo no deberia alcanzarse nunca por sorpresa.

    Se aprueba solo si, saltando TODOS los stops (los de ahora y el nuevo), el
    equity sigue por encima del suelo mas el colchon.

    El riesgo del candidato se calcula con el tamanyo que se le dara, que aun no
    esta decidido cuando corren las reglas. Se usa el maximo posible: el riesgo
    por operacion completo. Si con el peor caso cabe, con el real tambien.
    """
    # La comision de salida (revision del 15/10/2026): un stop que salta vende cruzando el libro (taker) y lo paga
    # cada posicion. La del candidato, con el nocional maximo, por el mismo motivo que su riesgo. El hueco del stop no
    # se cuenta: no tiene un numero exacto y lo cubre el colchon.
    exit_fees = cfg.exchange.fees.taker_pct / 100 * (st.notional_at_stops_usd() + lim.max_notional_usd)
    worst_case = (
        st.equity_usd
        - st.total_risk_to_stops_usd()
        - lim.risk_per_trade_usd
        - exit_fees
    )
    minimum = lim.min_equity_after_stops_usd
    if worst_case < minimum:
        return _veto(
            8, "preventiva del suelo",
            f"si saltaran todos los stops (con la comision de salida) quedarian {worst_case:.2f} $, "
            f"por debajo de {minimum:.2f} $ (suelo {lim.floor_usd:.2f} + "
            f"colchon {lim.preventive_buffer_usd:.2f})",
        )
    return _ok(
        8, "preventiva del suelo",
        f"peor caso {worst_case:.2f} $ >= {minimum:.2f} $",
    )


# --------------------------------------------------------------------------
# 9. Escalones de drawdown
# --------------------------------------------------------------------------
@rule(9, "escalones de drawdown")
def rule_09(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Los escalones ya estan aplicados dentro de `Limits`. Aqui se comprueba
    que efectivamente se aplicaron, que es lo que impide que un fallo al
    construir los limites pase desapercibido."""
    expected_positions, expected_multiplier = cfg.limits_for_equity(st.equity_usd)
    if lim.max_positions > expected_positions:
        return _veto(
            9, "escalones de drawdown",
            f"con {st.equity_usd:.2f} $ el tope son {expected_positions} posiciones "
            f"y los limites traen {lim.max_positions}",
        )
    if lim.drawdown_multiplier > expected_multiplier + 1e-9:
        return _veto(
            9, "escalones de drawdown",
            f"con {st.equity_usd:.2f} $ el multiplicador de riesgo deberia ser "
            f"{expected_multiplier} y es {lim.drawdown_multiplier}",
        )
    return _ok(
        9, "escalones de drawdown",
        f"max {lim.max_positions} posiciones, riesgo x{lim.drawdown_multiplier}",
    )


# --------------------------------------------------------------------------
# 10. Limite de perdida diaria
# --------------------------------------------------------------------------
@rule(10, "limite diario")
def rule_10(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if st.mode is Mode.CLOSE_ONLY_DAILY:
        return _veto(10, "limite diario", "CLOSE_ONLY_DAILY activo hasta las 00:00 UTC")
    loss = -st.pnl_today_usd
    if loss >= lim.daily_loss_limit_usd:
        return _veto(
            10, "limite diario",
            f"perdida de hoy {loss:.2f} $ >= limite {lim.daily_loss_limit_usd:.2f} $",
        )
    return _ok(
        10, "limite diario",
        f"PnL de hoy {st.pnl_today_usd:+.2f} $, quedan "
        f"{lim.daily_loss_limit_usd - loss:.2f} $",
    )


# --------------------------------------------------------------------------
# 11. Maximo de operaciones al dia
# --------------------------------------------------------------------------
@rule(11, "operaciones al dia")
def rule_11(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    if st.trades_today >= lim.max_trades_per_day:
        return _veto(
            11, "operaciones al dia",
            f"{st.trades_today} operaciones hoy (cerradas + vivas), "
            f"tope {lim.max_trades_per_day}",
        )
    return _ok(
        11, "operaciones al dia",
        f"{st.trades_today}/{lim.max_trades_per_day}",
    )


# --------------------------------------------------------------------------
# 12. Riesgo por operacion
# --------------------------------------------------------------------------
@rule(12, "riesgo por operacion")
def rule_12(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    risk = cfg.risk
    if not (risk.risk_per_trade_min_pct - 1e-9
            <= lim.risk_per_trade_pct
            <= risk.risk_per_trade_max_pct + 1e-9):
        return _veto(
            12, "riesgo por operacion",
            f"riesgo vigente {lim.risk_per_trade_pct:.3f} % fuera de "
            f"[{risk.risk_per_trade_min_pct}, {risk.risk_per_trade_max_pct}]",
        )
    if req.stop_price >= req.entry_price:
        return _veto(
            12, "riesgo por operacion",
            f"el stop {req.stop_price} no esta por debajo de la entrada "
            f"{req.entry_price}",
        )
    if not (0.5 - 1e-9 <= req.size_multiplier <= 1.0 + 1e-9):
        return _veto(
            12, "riesgo por operacion",
            f"la IA pidio multiplicador {req.size_multiplier}, fuera de [0,5; 1,0]. "
            f"Solo puede REDUCIR el tamanyo",
        )
    return _ok(
        12, "riesgo por operacion",
        f"{lim.risk_per_trade_pct:.2f} % = {lim.risk_per_trade_usd:.2f} $ "
        f"(x{req.size_multiplier})",
    )


# --------------------------------------------------------------------------
# 13. Stop y objetivo definidos
# --------------------------------------------------------------------------
@rule(13, "stop y objetivo")
def rule_13(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """El stop y el objetivo se colocan EN EL EXCHANGE al abrir (OCO). Aqui se
    exige que vengan definidos y sean coherentes: sin ellos no hay OCO que
    colocar, y una posicion sin stop en el exchange es exactamente lo que el
    informe seccion 2.5 llama "stop mental"."""
    if req.stop_price <= 0 or req.target_price <= 0:
        return _veto(13, "stop y objetivo", "faltan stop u objetivo")
    if req.stop_price >= req.entry_price:
        return _veto(
            13, "stop y objetivo",
            f"stop {req.stop_price} no esta por debajo de la entrada {req.entry_price}",
        )
    if req.target_price <= req.entry_price:
        return _veto(
            13, "stop y objetivo",
            f"objetivo {req.target_price} no esta por encima de la entrada "
            f"{req.entry_price}",
        )
    return _ok(
        13, "stop y objetivo",
        f"stop -{req.stop_distance_pct:.2f} %, objetivo "
        f"+{req.target_distance_pct:.2f} %, R:R {req.reward_risk:.2f}",
    )


# --------------------------------------------------------------------------
# 14. Cooldowns
# --------------------------------------------------------------------------
@rule(14, "cooldown y pausa")
def rule_14(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    until = st.cooldown_until(req.symbol, lim.cooldown_after_stop_hours)
    if until is not None and st.now < until:
        return _veto(
            14, "cooldown y pausa",
            f"{req.symbol} en cooldown tras un stop hasta {until:%Y-%m-%d %H:%M} UTC",
        )
    paused = st.paused_until(
        lim.consecutive_losses_for_pause, lim.pause_after_losses_hours
    )
    if paused is not None and st.now < paused:
        return _veto(
            14, "cooldown y pausa",
            f"{st.consecutive_losses()} perdidas seguidas: pausa hasta "
            f"{paused:%Y-%m-%d %H:%M} UTC",
        )
    return _ok(14, "cooldown y pausa", "sin cooldown ni pausa activos")


# --------------------------------------------------------------------------
# 15. Exposicion y correlacion
# --------------------------------------------------------------------------
@rule(15, "exposicion y correlacion")
def rule_15(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Tres altcoins largas con correlacion 0,9 no son tres apuestas: son una
    sola, apalancada (informe seccion 2.4)."""
    # OJO: aqui todavia no se sabe el tamanyo (se calcula despues de aprobar),
    # asi que esta comprobacion NO puede ser la que garantiza el 90 %. Lo que
    # hace es vetar cuando no cabe NINGUNA orden valida. Que la que si quepa se
    # ajuste al margen es cosa de `risk/sizing.py`, y que el resultado final
    # respete el tope lo vuelve a comprobar el motor con el tamanyo real.
    #
    # La version anterior proyectaba `exposicion + target_notional` (15 $) y
    # daba el visto bueno; luego el tamanyo podia salir de 20 $ y la exposicion
    # acababa por encima del 90 %. Medido: 30 $ expuestos + una orden de 20 $
    # dejaban el equity al 100 %.
    headroom = lim.max_exposure_usd - st.exposure_usd
    minimum = req.instrument.min_notional_usd(req.entry_price)
    if headroom < minimum:
        return _veto(
            15, "exposicion y correlacion",
            f"solo quedan {headroom:.2f} $ de margen de exposicion "
            f"({lim.max_exposure_usd:.2f} $ menos {st.exposure_usd:.2f} $ ya "
            f"expuestos) y la orden mas pequenya posible en {req.symbol} son "
            f"{minimum:.2f} $",
        )
    # Una pareja sin correlacion medida cuenta como correlacionada (decision
    # del propietario del 22/09/2026): ver `RiskState.correlated_with`.
    correlated = st.correlated_with(req.symbol, lim.correlation_threshold)
    if len(correlated) >= lim.max_correlated_positions:
        sin_medir = st.unmeasured_with(req.symbol)
        detalle = f" (sin medir: {sin_medir})" if sin_medir else ""
        return _veto(
            15, "exposicion y correlacion",
            f"{req.symbol} correlaciona > {lim.correlation_threshold} con "
            f"{correlated}{detalle}, y el tope son {lim.max_correlated_positions}",
        )
    return _ok(
        15, "exposicion y correlacion",
        f"exposicion {st.exposure_usd:.2f}/{lim.max_exposure_usd:.2f} $ "
        f"({headroom:.2f} $ de margen), {len(correlated)} correlacionadas",
    )


# --------------------------------------------------------------------------
# 16. Spread y coste
# --------------------------------------------------------------------------
@rule(16, "spread y coste")
def rule_16(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """El coste mueve la vara mas que cualquier indicador (informe seccion 2.2).

    El coste se calcula con entrada maker y salida TAKER. El stop-loss esta en
    el exchange (regla 13) y cuando salta cruza el libro: una salida urgente no
    puede ser maker. Suponer maker en las dos patas abarataba el coste y dejaba
    pasar objetivos que no llegan a pagar 3x lo que cuesta la operacion.
    """
    if req.spread_pct > lim.max_entry_spread_pct:
        return _veto(
            16, "spread y coste",
            f"spread {req.spread_pct:.4f} % > {lim.max_entry_spread_pct} %",
        )
    cost_pct = req.instrument.round_trip_cost_pct(
        req.spread_pct, exit_move_pct=req.target_distance_pct
    )
    if cost_pct <= 0:
        return _veto(16, "spread y coste", "coste de ida y vuelta no calculable")
    ratio = req.target_distance_pct / cost_pct
    if ratio < lim.min_target_cost_ratio:
        return _veto(
            16, "spread y coste",
            f"objetivo {req.target_distance_pct:.3f} % solo es {ratio:.2f}x el coste "
            f"({cost_pct:.3f} %), y hace falta {lim.min_target_cost_ratio}x",
        )
    return _ok(
        16, "spread y coste",
        f"spread {req.spread_pct:.4f} %, objetivo {ratio:.1f}x el coste",
    )


# --------------------------------------------------------------------------
# 17. Despegue de USDC
# --------------------------------------------------------------------------
@rule(17, "paridad de USDC")
def rule_17(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Operando contra USDC, tu "efectivo" ES USDC. En marzo de 2023 llego a
    0,88 $ un fin de semana (informe seccion 2.4)."""
    if st.usdc_deviation_pct is None:
        return _veto(
            17, "paridad de USDC",
            "paridad de USDC desconocida: no hay lectura fiable (ver features/usdc.py)",
        )
    deviation = abs(st.usdc_deviation_pct)
    if deviation > lim.usdc_depeg_pct:
        return _veto(
            17, "paridad de USDC",
            f"USDC desviado {st.usdc_deviation_pct:+.2f} % de la paridad, "
            f"tope {lim.usdc_depeg_pct} %",
        )
    return _ok(17, "paridad de USDC", f"desviacion {st.usdc_deviation_pct:+.3f} %")


# --------------------------------------------------------------------------
# 18. Presupuesto de llamadas a Claude
# --------------------------------------------------------------------------
@rule(18, "presupuesto de Claude")
def rule_18(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """El presupuesto lo controla el invocador ANTES de llamar; si se agota, el
    modo pasa a CLOSE_ONLY_QUOTA y esta regla lo ve reflejado aqui.

    El motor de riesgo NO importa nada de `ai/`: solo mira el modo."""
    if st.mode is Mode.CLOSE_ONLY_QUOTA:
        return _veto(
            18, "presupuesto de Claude",
            "CLOSE_ONLY_QUOTA: sin cuota de Claude o login caducado",
        )
    return _ok(
        18, "presupuesto de Claude",
        f"tope {cfg.claude.max_calls_per_day}/dia, "
        f"{cfg.claude.max_calls_per_5h_window}/ventana",
    )


# --------------------------------------------------------------------------
# 19. Credenciales
# --------------------------------------------------------------------------
@rule(19, "credenciales")
def rule_19(req: EntryRequest, st: RiskState, lim: Limits, cfg: Settings) -> RuleResult:
    """Los permisos de la clave se fijan en OKX y se verifican con
    `scripts/verify_okx_key.py`. El motor de riesgo NUNCA ve credenciales: que
    no pueda comprobarlas es, precisamente, la regla cumpliendose."""
    return _ok(
        19, "credenciales",
        "el motor de riesgo no ve claves ni variables de entorno",
    )


# --------------------------------------------------------------------------
# Regla transversal de modo: solo NORMAL abre (PRD seccion 5)
# --------------------------------------------------------------------------
def check_mode(st: RiskState) -> RuleResult:
    """No es una de las 19, pero veta antes que todas ellas."""
    if not st.mode.can_open:
        return RuleResult(
            0, "modo de operacion", False,
            f"modo {st.mode}: no se abren posiciones",
        )
    return RuleResult(0, "modo de operacion", True, str(st.mode))
