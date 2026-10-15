"""Ingesta por WebSocket: fuente principal de datos (informe seccion 1.3[1]).

Una tarea por (simbolo, timeframe) para velas y una por simbolo para el libro.
Cada tarea se reconecta sola con backoff exponencial; si una moneda se cae, las
demas siguen.

Dos reglas que se aplican aqui y no mas adelante:
  * solo se persisten velas CERRADAS (evita look-ahead bias);
  * cada mensaje toca el detector de datos obsoletos, este o no valido el dato.
"""

from __future__ import annotations

import asyncio
import random

from core.clock import utcnow_ms
from core.config import Settings
from core.events import EventBus, EventKind
from core.logging import get_logger
from data.exchange import Exchange
from data.ingest.sequencer import CandleSequencer
from data.ingest.staleness import SOURCE_ORDERBOOK, StalenessMonitor, candle_source
from data.store.repos import BookMetricsRepo, Candle, CandleRepo, L1Repo
from data.validate import validate_candle, validate_orderbook

log = get_logger(__name__)

RECONNECT_BASE_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 60.0


def _backoff(attempt: int) -> float:
    """Backoff exponencial con jitter, para no reconectar todos a la vez."""
    delay = min(RECONNECT_BASE_SECONDS * (2 ** attempt), RECONNECT_MAX_SECONDS)
    return delay * (0.5 + random.random() * 0.5)


def book_metrics(
    bids: list[tuple[float, float]], asks: list[tuple[float, float]]
) -> dict[str, float]:
    """Metricas derivadas del libro (informe seccion 1.3, microestructura)."""
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0

    top = 10
    bid_vol = sum(q for _, q in bids[:top])
    ask_vol = sum(q for _, q in asks[:top])
    total = bid_vol + ask_vol
    imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0

    def depth(levels: list[tuple[float, float]], lo: float, hi: float) -> float:
        return sum(p * q for p, q in levels if lo <= p <= hi)

    return {
        "mid": mid,
        "spread_pct": (best_ask - best_bid) / mid * 100.0,
        "imbalance": imbalance,
        "depth_bid_05pct": depth(bids, mid * 0.995, mid),
        "depth_ask_05pct": depth(asks, mid, mid * 1.005),
        "depth_bid_01pct": depth(bids, mid * 0.999, mid),
        "depth_ask_01pct": depth(asks, mid, mid * 1.001),
        "levels": float(min(len(bids), len(asks))),
    }


class WsIngestor:
    """Orquesta las tareas de WebSocket de toda la whitelist."""

    def __init__(
        self,
        settings: Settings,
        exchange: Exchange,
        candles: CandleRepo,
        l1: L1Repo,
        books: BookMetricsRepo,
        staleness: StalenessMonitor,
        bus: EventBus | None = None,
    ) -> None:
        self.settings = settings
        self.exchange = exchange
        self.candles = candles
        self.l1 = l1
        self.books = books
        self.staleness = staleness
        self.bus = bus
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._last_close: dict[str, float] = {}
        self._sequencers: dict[str, CandleSequencer] = {}

    # --- ciclo de vida ---

    def start(self) -> None:
        for symbol in self.settings.whitelist:
            for timeframe in self.settings.data.timeframes:
                self._tasks.append(
                    asyncio.create_task(
                        self._candle_loop(symbol, timeframe),
                        name=f"ws-candles-{symbol}-{timeframe}",
                    )
                )
            self._tasks.append(
                asyncio.create_task(
                    self._book_loop(symbol), name=f"ws-book-{symbol}"
                )
            )
        log.info("WebSocket: %d tareas arrancadas", len(self._tasks))

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # --- bucles ---

    async def _candle_loop(self, symbol: str, timeframe: str) -> None:
        source = candle_source(timeframe)
        attempt = 0
        while not self._stopping.is_set():
            try:
                rows = await self.exchange.watch_ohlcv(symbol, timeframe)
                if attempt:
                    log.info("WS reconectado: %s %s", symbol, timeframe)
                    if self.bus:
                        self.bus.emit(
                            EventKind.WS_CONNECTED, symbol=symbol, source=source
                        )
                attempt = 0
                await self._handle_candles(symbol, timeframe, source, rows)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = _backoff(attempt)
                log.warning(
                    "WS %s %s cayo (intento %d, reintento en %.1fs): %s",
                    symbol,
                    timeframe,
                    attempt,
                    delay,
                    exc,
                )
                if self.bus:
                    self.bus.emit(
                        EventKind.WS_DISCONNECTED,
                        symbol=symbol,
                        source=source,
                        error=str(exc),
                        attempt=attempt,
                    )
                await asyncio.sleep(delay)

    async def _handle_candles(
        self, symbol: str, timeframe: str, source: str, rows: list[list[float]]
    ) -> None:
        now = utcnow_ms()
        self.staleness.touch(source, symbol, now)

        key = f"{symbol}|{timeframe}"
        sequencer = self._sequencers.setdefault(key, CandleSequencer(timeframe))

        # La secuencia del exchange decide que esta cerrado, no nuestro reloj:
        # `watch_ohlcv` solo devuelve la vela en curso, asi que la unica senyal
        # fiable de cierre es que llegue la siguiente. Ver sequencer.py.
        closed_rows = sequencer.feed(rows)
        stale = sequencer.flush_if_stale(now)
        if stale is not None:
            closed_rows.append(stale)

        to_store: list[Candle] = []
        for row in closed_rows:
            candle = Candle.from_ccxt(
                symbol, timeframe, row, closed=True, source="ws"
            )
            reference = self._last_close.get(key)
            verdict = validate_candle(candle, now_ms=now, reference_price=reference)
            if not verdict.ok:
                log.warning(
                    "vela WS descartada %s %s %s: %s",
                    symbol,
                    timeframe,
                    candle.ts_open_ms,
                    verdict.reason,
                )
                if self.bus:
                    self.bus.emit(
                        EventKind.CANDLE_REJECTED,
                        symbol=symbol,
                        timeframe=timeframe,
                        ts_open_ms=candle.ts_open_ms,
                        reason=verdict.reason,
                        source="ws",
                    )
                continue
            self._last_close[key] = candle.close
            to_store.append(candle)

        if to_store:
            await self.candles.upsert_many(to_store)
            if self.bus:
                for candle in to_store:
                    self.bus.emit(
                        EventKind.CANDLE_CLOSED,
                        symbol=symbol,
                        timeframe=timeframe,
                        ts_open_ms=candle.ts_open_ms,
                        close=candle.close,
                    )

    async def _book_loop(self, symbol: str) -> None:
        attempt = 0
        depth = self.settings.data.orderbook_depth
        persist = self.settings.data.persist
        next_l1 = 0.0
        next_metrics = 0.0

        while not self._stopping.is_set():
            try:
                book = await self.exchange.watch_order_book(symbol, depth)
                if attempt:
                    log.info("WS libro reconectado: %s", symbol)
                    if self.bus:
                        self.bus.emit(
                            EventKind.WS_CONNECTED,
                            symbol=symbol,
                            source=SOURCE_ORDERBOOK,
                        )
                attempt = 0
                now = utcnow_ms()
                self.staleness.touch(SOURCE_ORDERBOOK, symbol, now)

                bids = [(float(p), float(q)) for p, q, *_ in book.get("bids", [])]
                asks = [(float(p), float(q)) for p, q, *_ in book.get("asks", [])]
                verdict = validate_orderbook(bids, asks)
                if not verdict.ok:
                    log.warning("libro descartado %s: %s", symbol, verdict.reason)
                    continue

                if now >= next_l1:
                    await self.l1.insert_many(
                        [(symbol, now, bids[0][0], bids[0][1], asks[0][0], asks[0][1])]
                    )
                    next_l1 = now + persist.l1_interval_seconds * 1000

                if now >= next_metrics:
                    m = book_metrics(bids, asks)
                    await self.books.insert_many(
                        [
                            (
                                symbol,
                                now,
                                m["mid"],
                                m["spread_pct"],
                                m["imbalance"],
                                m["depth_bid_05pct"],
                                m["depth_ask_05pct"],
                                m["depth_bid_01pct"],
                                m["depth_ask_01pct"],
                                int(m["levels"]),
                            )
                        ]
                    )
                    next_metrics = now + persist.book_metrics_interval_seconds * 1000

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = _backoff(attempt)
                log.warning(
                    "WS libro %s cayo (intento %d, reintento en %.1fs): %s",
                    symbol,
                    attempt,
                    delay,
                    exc,
                )
                if self.bus:
                    self.bus.emit(
                        EventKind.WS_DISCONNECTED,
                        symbol=symbol,
                        source=SOURCE_ORDERBOOK,
                        error=str(exc),
                        attempt=attempt,
                    )
                await asyncio.sleep(delay)
