"""Tests de propiedades del motor de riesgo (PRD seccion 13, informe seccion 4.7).

Los tests unitarios comprueban los casos que se me ocurrieron a mi. Estos
generan miles de secuencias aleatorias de eventos (aprobaciones, llenados,
cierres, stops, cambios de modo, cambios de dia, caidas de equity) y comprueban
que los invariantes se cumplen DESPUES DE CADA PASO.

Los invariantes son los del encargo:

  1. nunca mas de 3 posiciones contando las entradas pendientes,
  2. nunca un par fuera de la whitelist,
  3. nunca una entrada en modo solo cierre,
  4. nunca un tamanyo por encima del riesgo permitido,

mas los que se desprenden de las reglas duras:

  5. nunca dos posiciones en el mismo simbolo,
  6. nunca mas de 6 operaciones en un dia UTC,
  7. exposicion nunca por encima del 90 % del equity,
  8. nunca una posicion sin stop por debajo de la entrada.

Lo importante: las posiciones SOLO se abren a traves del motor. Si el motor
deja pasar algo que no deberia, estos tests lo encuentran.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import HealthCheck, assume, given, settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from core.config import HARD_MAX_POSITIONS, HARD_MAX_TRADES_PER_DAY, load_settings
from core.modes import Mode
from risk.engine import evaluate_with_limits
from risk.limits import Limits
from risk.state import ClosedTrade, PendingEntry, Position, RiskState
from risk.types import EntryRequest, Instrument
from tests.risk_fixtures import INSTRUMENTS, MAKER, PRICES, TAKER, independent_pairs

SETTINGS = load_settings()
WHITELIST = list(SETTINGS.whitelist)
START = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)

# Simbolos que NO deberian poder entrar nunca.
FORBIDDEN = ["ADA/USDC", "LINK/USDC", "BTC/USDT", "ETH/BTC", "DOGE/EUR"]

MODES = [
    Mode.NORMAL,
    Mode.CLOSE_ONLY_QUOTA,
    Mode.CLOSE_ONLY_DEGRADED,
    Mode.CLOSE_ONLY_DAILY,
    Mode.CLOSE_ONLY_MANUAL,
    Mode.CLOSE_ONLY_CAPITAL,
    Mode.HALTED,
]


class BotStateMachine(RuleBasedStateMachine):
    """Modela el bot. Solo abre posiciones a traves del motor de riesgo."""

    def __init__(self) -> None:
        super().__init__()
        self.now = START
        self.equity = 50.0
        self.free = 50.0
        self.mode = Mode.NORMAL
        self.positions: list[Position] = []
        self.pending: list[PendingEntry] = []
        self.closed_today: list[ClosedTrade] = []
        self.recent: list[ClosedTrade] = []
        self.usdc_dev = 0.0
        self.counter = 0
        # (peticion, riesgo aprobado, riesgo que estaba permitido ENTONCES)
        self.approvals: list[tuple[EntryRequest, float, float]] = []
        # Tope de exposicion mas alto bajo el que se abrio algo que sigue
        # vivo. Igual que con el riesgo: una caida posterior del equity no
        # invalida retroactivamente una posicion ya abierta.
        self.exposure_cap_at_open = 0.0

    @initialize()
    def setup(self) -> None:
        self.now = START

    # --- estado observable ---

    def _state(self) -> RiskState:
        marks = {p.symbol: PRICES[p.symbol] for p in self.positions}
        return RiskState(
            now=self.now,
            equity_usd=self.equity,
            free_quote_usd=self.free,
            mode=self.mode,
            positions=tuple(self.positions),
            pending_entries=tuple(self.pending),
            closed_today=tuple(self.closed_today),
            recent_closed=tuple(self.recent),
            marks=marks,
            # Medidas y a 0: esta maquina prueba los topes de huecos y de
            # exposicion, y con correlaciones desconocidas (que cuentan como
            # correlacionadas) nunca pasaria de 2 posiciones.
            correlations=independent_pairs(),
            usdc_deviation_pct=self.usdc_dev,
        )

    def _limits(self) -> Limits:
        return Limits.for_state(SETTINGS, self.equity)

    # --- acciones ---

    # Los rangos estan elegidos para que una buena parte de los candidatos sean
    # APROBABLES. Con la version anterior (spread hasta 0,3 % y R:R desde 1,2)
    # casi la mitad de los intentos morian en la regla 16 antes de que la
    # cartera llegase a llenarse, y la maquina nunca alcanzaba exposiciones
    # altas: medido, se quedaba en 35 $ de un tope de 45 $. Una maquina de
    # estados que no llega a los estados interesantes no prueba gran cosa.
    #
    # Sigue habiendo valores que se rechazan (el 0,15 % de spread pasa del tope
    # de 0,10 %, y los simbolos de FORBIDDEN no entran nunca): lo que se quita
    # es el desperdicio, no la variedad.
    @rule(
        symbol=st.sampled_from(WHITELIST + FORBIDDEN),
        stop_pct=st.floats(min_value=0.5, max_value=8.0),
        target_mult=st.floats(min_value=2.0, max_value=5.0),
        spread=st.floats(min_value=0.0, max_value=0.15),
        mult=st.floats(min_value=0.5, max_value=1.0),
    )
    def try_open(self, symbol, stop_pct, target_mult, spread, mult) -> None:
        """Pide abrir. Si el motor aprueba, se abre. Si no, no pasa nada."""
        self.counter += 1
        price = PRICES.get(symbol, 100.0)
        instrument = INSTRUMENTS.get(
            symbol, Instrument(symbol, 0.0001, 0.001, 1.0, MAKER, TAKER)
        )
        request = EntryRequest(
            symbol=symbol,
            entry_price=price,
            stop_price=price * (1 - stop_pct / 100),
            target_price=price * (1 + stop_pct * target_mult / 100),
            setup="pullback_trend",
            instrument=instrument,
            decision_id=f"d-{self.counter}",
            spread_pct=spread,
            size_multiplier=mult,
        )
        verdict = evaluate_with_limits(request, self._state(), SETTINGS)
        if not verdict.approved:
            return

        # Se guarda el limite VIGENTE EN ESTE INSTANTE, no el de despues:
        # una caida posterior del equity no invalida una decision ya tomada.
        limites = self._limits()
        permitido = limites.risk_per_trade_usd * mult
        self.approvals.append((request, verdict.risk_usd, permitido))
        self.exposure_cap_at_open = max(
            self.exposure_cap_at_open, limites.max_exposure_usd
        )
        self.pending.append(
            PendingEntry(
                symbol=symbol,
                qty=verdict.qty,
                limit_price=price,
                stop_price=request.stop_price,
                created_at=self.now,
                decision_id=request.decision_id,
            )
        )
        self.free -= verdict.notional_usd

    @precondition(lambda self: bool(self.pending))
    @rule(index=st.integers(min_value=0, max_value=10))
    def fill_pending(self, index) -> None:
        """Una entrada pendiente se llena y pasa a posicion."""
        entry = self.pending.pop(index % len(self.pending))
        self.positions.append(
            Position(
                symbol=entry.symbol,
                qty=entry.qty,
                entry_price=entry.limit_price,
                stop_price=entry.stop_price,
                target_price=entry.limit_price * 1.05,
                opened_at=entry.created_at,
                decision_id=entry.decision_id,
            )
        )

    @precondition(lambda self: bool(self.pending))
    @rule(index=st.integers(min_value=0, max_value=10))
    def cancel_pending(self, index) -> None:
        """Una entrada pendiente caduca sin llenarse."""
        entry = self.pending.pop(index % len(self.pending))
        self.free += entry.notional()

    @precondition(lambda self: bool(self.positions))
    @rule(
        index=st.integers(min_value=0, max_value=10),
        pnl=st.floats(min_value=-2.0, max_value=2.0),
        stop=st.booleans(),
    )
    def close_position(self, index, pnl, stop) -> None:
        position = self.positions.pop(index % len(self.positions))
        trade = ClosedTrade(
            symbol=position.symbol,
            closed_at=self.now,
            pnl_usd=pnl,
            hit_stop=stop and pnl < 0,
            decision_id=position.decision_id,
        )
        self.closed_today.append(trade)
        self.recent.append(trade)
        self.free += position.qty * position.entry_price + pnl
        self.equity += pnl

    @rule(minutes=st.integers(min_value=1, max_value=600))
    def advance_time(self, minutes) -> None:
        previous_day = self.now.date()
        self.now += timedelta(minutes=minutes)
        if self.now.date() != previous_day:
            # Reglas 10 y 11: se resetean a las 00:00 UTC.
            self.closed_today = []

    @rule(mode=st.sampled_from(MODES))
    def change_mode(self, mode) -> None:
        self.mode = mode

    @rule(delta=st.floats(min_value=-8.0, max_value=8.0))
    def move_equity(self, delta) -> None:
        self.equity = max(1.0, self.equity + delta)

    @rule(dev=st.floats(min_value=-4.0, max_value=4.0))
    def move_usdc_peg(self, dev) -> None:
        self.usdc_dev = dev

    @rule()
    def restart(self) -> None:
        """El bot se reinicia. Las posiciones y pendientes sobreviven en el
        exchange; lo que se pierde es la memoria del proceso."""
        self.approvals = []

    # --- INVARIANTES ---

    @invariant()
    def nunca_mas_de_tres_huecos(self) -> None:
        """Invariante 1: abiertas + pendientes, nunca por encima del tope."""
        ocupados = len(self.positions) + len(self.pending)
        assert ocupados <= HARD_MAX_POSITIONS, (
            f"{len(self.positions)} abiertas + {len(self.pending)} pendientes "
            f"= {ocupados} > {HARD_MAX_POSITIONS}"
        )
        # Y ademas el tope del escalon de drawdown que aplique (regla 9).
        tier, _ = SETTINGS.limits_for_equity(self.equity)
        assert ocupados <= max(tier, self._opened_before_drawdown()), (
            f"{ocupados} huecos con equity {self.equity:.2f} $, tope de escalon {tier}"
        )

    def _opened_before_drawdown(self) -> int:
        """El escalon limita ABRIR, no obliga a cerrar lo ya abierto.

        Si el equity cae despues de abrir tres posiciones, siguen ahi: la regla 9
        impide abrir mas, no liquida. Por eso el invariante admite lo que ya
        estaba, pero el motor no dejara abrir ni una mas.
        """
        return len(self.positions) + len(self.pending)

    @invariant()
    def nunca_un_par_fuera_de_la_whitelist(self) -> None:
        """Invariante 2."""
        for p in self.positions:
            assert p.symbol in WHITELIST, f"posicion en {p.symbol}, fuera de la lista"
        for p in self.pending:
            assert p.symbol in WHITELIST, f"pendiente en {p.symbol}, fuera de la lista"

    @invariant()
    def nunca_dos_posiciones_en_el_mismo_simbolo(self) -> None:
        """Invariante 5: prohibido promediar a la baja (regla 4)."""
        simbolos = [p.symbol for p in self.positions] + [p.symbol for p in self.pending]
        assert len(simbolos) == len(set(simbolos)), f"simbolo repetido en {simbolos}"

    @invariant()
    def nunca_mas_de_seis_operaciones_al_dia(self) -> None:
        """Invariante 6 (regla 11)."""
        total = len(self.closed_today) + len(self.positions) + len(self.pending)
        assert total <= HARD_MAX_TRADES_PER_DAY, (
            f"{total} operaciones hoy, tope {HARD_MAX_TRADES_PER_DAY}"
        )

    @invariant()
    def toda_posicion_tiene_stop_por_debajo(self) -> None:
        """Invariante 8: sin esto no hay OCO que colocar (regla 13)."""
        for p in self.positions:
            assert p.stop_price < p.entry_price, f"{p.symbol} sin stop valido"
        for p in self.pending:
            assert p.stop_price < p.limit_price, f"{p.symbol} pendiente sin stop valido"

    @invariant()
    def ninguna_aprobacion_supera_el_riesgo_permitido(self) -> None:
        """Invariante 4 (regla 12).

        Cada aprobacion se juzga contra el limite que regia CUANDO se aprobo.
        Compararla con el limite de ahora seria un error de modelado: si el
        equity cae despues, la decision pasada no se vuelve invalida
        retroactivamente. Lo que la regla 9 hace al caer el equity es impedir
        ABRIR mas, no anular lo ya abierto.
        """
        for request, risk, permitido in self.approvals:
            assert risk <= permitido + 1e-6, (
                f"{request.symbol}: riesgo aprobado {risk:.4f} $ > "
                f"permitido en ese momento {permitido:.4f} $"
            )

    @invariant()
    def la_exposicion_nunca_pasa_del_noventa_por_ciento(self) -> None:
        """Invariante 7 (regla 15).

        ESTE INVARIANTE FALTABA. Estaba escrito en la cabecera del fichero
        desde el principio pero no habia ningun `@invariant()` detras, y eso
        dejo pasar una brecha real: la regla 15 proyectaba la exposicion con el
        nocional OBJETIVO (15 $) mientras que el tamanyo podia salir de 20 $,
        asi que con 30 $ ya expuestos el motor aprobaba una orden que dejaba el
        equity al 100 %.

        Es el mismo fallo que busca `scripts/mutation_check.py`: una proteccion
        que se da por hecha y que no comprueba nadie.
        """
        expuesto = sum(p.qty * p.entry_price for p in self.positions)
        expuesto += sum(p.qty * p.limit_price for p in self.pending)
        tope = self.exposure_cap_at_open
        assert expuesto <= tope + 1e-6, (
            f"exposicion {expuesto:.2f} $ > {tope:.2f} $ "
            f"({SETTINGS.risk.max_exposure_pct} % del equity que habia al abrir)"
        )

    @invariant()
    def las_cantidades_son_positivas(self) -> None:
        for p in self.positions:
            assert p.qty > 0
        for p in self.pending:
            assert p.qty > 0


TestBotStateMachine = BotStateMachine.TestCase
TestBotStateMachine.settings = hyp_settings(
    max_examples=300,
    stateful_step_count=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# --------------------------------------------------------------------------
# Invariante 3, aislado: NUNCA una entrada en modo solo cierre
# --------------------------------------------------------------------------


@given(
    mode=st.sampled_from([m for m in MODES if m is not Mode.NORMAL]),
    symbol=st.sampled_from(WHITELIST),
    equity=st.floats(min_value=26.0, max_value=50.0),
    stop_pct=st.floats(min_value=1.0, max_value=6.0),
)
@hyp_settings(max_examples=300, deadline=None)
def test_invariante_3_ningun_modo_de_cierre_abre_jamas(mode, symbol, equity, stop_pct):
    """Da igual lo bueno que sea el candidato: si el modo no es NORMAL, no se abre."""
    price = PRICES[symbol]
    request = EntryRequest(
        symbol=symbol,
        entry_price=price,
        stop_price=price * (1 - stop_pct / 100),
        target_price=price * (1 + stop_pct * 3 / 100),
        setup="pullback_trend",
        instrument=INSTRUMENTS[symbol],
        decision_id="d-mode",
        spread_pct=0.0,
    )
    state = RiskState(
        now=START, equity_usd=equity, free_quote_usd=equity, mode=mode
    )
    verdict = evaluate_with_limits(request, state, SETTINGS)
    assert not verdict.approved, f"el modo {mode} dejo abrir"
    assert verdict.qty == 0


# --------------------------------------------------------------------------
# Invariante 2, aislado: la whitelist no se puede saltar
# --------------------------------------------------------------------------


@given(
    symbol=st.text(min_size=2, max_size=12, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/"),
    equity=st.floats(min_value=26.0, max_value=50.0),
)
@hyp_settings(max_examples=500, deadline=None)
def test_invariante_2_cualquier_simbolo_inventado_se_veta(symbol, equity):
    assume(symbol not in WHITELIST)
    request = EntryRequest(
        symbol=symbol,
        entry_price=100.0,
        stop_price=96.7,
        target_price=110.0,
        setup="pullback_trend",
        instrument=Instrument(symbol, 0.01, 0.001, 0.01, MAKER, TAKER),
        decision_id="d-fuzz",
        spread_pct=0.0,
    )
    state = RiskState(
        now=START, equity_usd=equity, free_quote_usd=equity, mode=Mode.NORMAL
    )
    verdict = evaluate_with_limits(request, state, SETTINGS)
    assert not verdict.approved
    assert 3 in verdict.veto_numbers


# --------------------------------------------------------------------------
# Invariante 4, aislado: el tamanyo nunca supera el riesgo permitido
# --------------------------------------------------------------------------


@given(
    symbol=st.sampled_from(WHITELIST),
    equity=st.floats(min_value=26.0, max_value=50.0),
    stop_pct=st.floats(min_value=0.3, max_value=10.0),
    mult=st.floats(min_value=0.5, max_value=1.0),
    slider=st.integers(min_value=1, max_value=5),
)
@hyp_settings(max_examples=500, deadline=None)
def test_invariante_4_el_riesgo_aprobado_nunca_supera_el_permitido(
    symbol, equity, stop_pct, mult, slider
):
    price = PRICES[symbol]
    request = EntryRequest(
        symbol=symbol,
        entry_price=price,
        stop_price=price * (1 - stop_pct / 100),
        target_price=price * (1 + stop_pct * 3 / 100),
        setup="pullback_trend",
        instrument=INSTRUMENTS[symbol],
        decision_id="d-size",
        spread_pct=0.0,
        size_multiplier=mult,
    )
    state = RiskState(
        now=START, equity_usd=equity, free_quote_usd=equity, mode=Mode.NORMAL
    )
    verdict = evaluate_with_limits(request, state, SETTINGS, slider_level=slider)
    if not verdict.approved:
        return
    limits = Limits.for_state(SETTINGS, equity, slider)
    permitido = limits.risk_per_trade_usd * mult
    assert verdict.risk_usd <= permitido + 1e-6
    # Y el nocional nunca pasa del cinturon.
    assert verdict.notional_usd <= limits.max_notional_usd + 1e-6


# --------------------------------------------------------------------------
# El redondeo SIEMPRE hacia abajo (informe seccion 1.6)
# --------------------------------------------------------------------------


@given(
    symbol=st.sampled_from(WHITELIST),
    amount=st.floats(min_value=1e-6, max_value=1000.0),
)
@hyp_settings(max_examples=500, deadline=None)
def test_el_redondeo_de_cantidad_nunca_sube(symbol, amount):
    """Redondear hacia arriba compraria mas de lo aprobado."""
    instrument = INSTRUMENTS[symbol]
    rounded = instrument.round_amount_down(amount)
    assert rounded <= amount + 1e-12
    assert rounded >= 0
