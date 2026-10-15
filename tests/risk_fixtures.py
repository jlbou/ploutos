"""Constructores para los tests del motor de riesgo.

Un estado sano por defecto, y cada test rompe SOLO lo que quiere probar. Asi,
cuando un test falla, la causa es lo que el test tocó y no el andamiaje.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.modes import Mode
from risk.state import ClosedTrade, PendingEntry, Position, RiskState
from risk.types import EntryRequest, Instrument

NOW = datetime(2026, 9, 22, 14, 0, 0, tzinfo=UTC)

# Parametros reales de OKX medidos el 22/09/2026, incluidas las comisiones que
# devolvio ccxt para los 8 pares: maker 0,10 %, taker 0,15 %.
#
# Estos son los mismos numeros que hay en la tabla `instruments` del servidor.
# Se repiten aqui, y no se leen de la base de datos, para que los tests del
# motor de riesgo no dependan de que exista una base de datos.
MAKER = 0.0010
TAKER = 0.0015

INSTRUMENTS = {
    "BTC/USDC":  Instrument("BTC/USDC",  0.1,    1e-8,   0.0001, MAKER, TAKER),
    "ETH/USDC":  Instrument("ETH/USDC",  0.01,   1e-6,   0.001,  MAKER, TAKER),
    "SOL/USDC":  Instrument("SOL/USDC",  0.01,   1e-5,   0.01,   MAKER, TAKER),
    "XRP/USDC":  Instrument("XRP/USDC",  0.0001, 0.001,  1.0,    MAKER, TAKER),
    "DOGE/USDC": Instrument("DOGE/USDC", 1e-5,   0.01,   10.0,   MAKER, TAKER),
    "AVAX/USDC": Instrument("AVAX/USDC", 0.001,  0.0001, 0.1,    MAKER, TAKER),
    "TRX/USDC":  Instrument("TRX/USDC",  1e-5,   0.01,   1.0,    MAKER, TAKER),
    "NEAR/USDC": Instrument("NEAR/USDC", 0.001,  1e-8,   1.0,    MAKER, TAKER),
}

# Precios aproximados del 22/09/2026, para que los nocionales sean realistas.
PRICES = {
    "BTC/USDC": 86000.0,
    "ETH/USDC": 2744.0,
    "SOL/USDC": 116.0,
    "XRP/USDC": 1.52,
    "DOGE/USDC": 0.0976,
    "AVAX/USDC": 10.84,
    "TRX/USDC": 0.347,
    "NEAR/USDC": 4.42,
}


def make_request(
    symbol: str = "ETH/USDC",
    *,
    entry: float | None = None,
    stop_pct: float = 3.33,
    target_pct: float = 6.66,
    spread_pct: float = 0.01,
    size_multiplier: float = 1.0,
    setup: str = "pullback_trend",
    decision_id: str = "d-test-1",
    instrument: Instrument | None = None,
) -> EntryRequest:
    """Un candidato sano.

    Los valores por defecto son los de la decision del 22/09/2026: stop del
    3,33 %, que con 0,50 $ de riesgo da una posicion de ~15 $.
    """
    price = entry if entry is not None else PRICES[symbol]
    return EntryRequest(
        symbol=symbol,
        entry_price=price,
        stop_price=price * (1 - stop_pct / 100),
        target_price=price * (1 + target_pct / 100),
        setup=setup,
        instrument=instrument or INSTRUMENTS[symbol],
        decision_id=decision_id,
        spread_pct=spread_pct,
        size_multiplier=size_multiplier,
    )


def make_position(
    symbol: str = "BTC/USDC",
    *,
    notional: float = 15.0,
    stop_pct: float = 3.33,
    opened_minutes_ago: int = 60,
    decision_id: str = "d-pos",
) -> Position:
    price = PRICES[symbol]
    return Position(
        symbol=symbol,
        qty=notional / price,
        entry_price=price,
        stop_price=price * (1 - stop_pct / 100),
        target_price=price * (1 + stop_pct * 2 / 100),
        opened_at=NOW - timedelta(minutes=opened_minutes_ago),
        decision_id=decision_id,
    )


def make_pending(
    symbol: str = "SOL/USDC",
    *,
    notional: float = 15.0,
    stop_pct: float = 3.33,
    decision_id: str = "d-pend",
) -> PendingEntry:
    price = PRICES[symbol]
    return PendingEntry(
        symbol=symbol,
        qty=notional / price,
        limit_price=price,
        stop_price=price * (1 - stop_pct / 100),
        created_at=NOW - timedelta(minutes=5),
        decision_id=decision_id,
    )


def make_trade(
    symbol: str = "BTC/USDC",
    *,
    pnl: float = -0.50,
    hit_stop: bool = True,
    minutes_ago: int = 30,
    decision_id: str = "d-closed",
) -> ClosedTrade:
    return ClosedTrade(
        symbol=symbol,
        closed_at=NOW - timedelta(minutes=minutes_ago),
        pnl_usd=pnl,
        hit_stop=hit_stop,
        decision_id=decision_id,
    )


def independent_pairs() -> dict[tuple[str, str], float]:
    """Todas las parejas de la whitelist, medidas y a 0,0."""
    simbolos = sorted(INSTRUMENTS)
    return {
        (a, b): 0.0 for i, a in enumerate(simbolos) for b in simbolos[i + 1:]
    }


def make_state(
    *,
    equity: float = 50.0,
    free_quote: float | None = None,
    mode: Mode = Mode.NORMAL,
    positions: tuple[Position, ...] = (),
    pending: tuple[PendingEntry, ...] = (),
    closed_today: tuple[ClosedTrade, ...] = (),
    recent_closed: tuple[ClosedTrade, ...] = (),
    marks: dict[str, float] | None = None,
    # None = todas las parejas MEDIDAS e independientes (0,0), para que los
    # tests que no van de correlacion no choquen con la regla 15. Un dict =
    # exactamente eso, y las parejas que no esten quedan SIN MEDIR.
    correlations: dict[tuple[str, str], float] | None = None,
    usdc_deviation_pct: float = 0.0,
    now: datetime = NOW,
) -> RiskState:
    """Un estado sano. Por defecto: 50 $, sin posiciones, todo en orden."""
    if marks is None:
        marks = {p.symbol: PRICES[p.symbol] for p in positions}
    if free_quote is None:
        used = sum(p.qty * p.entry_price for p in positions)
        used += sum(p.notional() for p in pending)
        free_quote = max(0.0, equity - used)
    return RiskState(
        now=now,
        equity_usd=equity,
        free_quote_usd=free_quote,
        mode=mode,
        positions=positions,
        pending_entries=pending,
        closed_today=closed_today,
        recent_closed=recent_closed,
        marks=marks,
        correlations=independent_pairs() if correlations is None else correlations,
        usdc_deviation_pct=usdc_deviation_pct,
    )
