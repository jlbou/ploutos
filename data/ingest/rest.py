"""Ingesta por REST: backfill inicial y relleno de huecos.

El WebSocket es la fuente principal, pero:
  * al arrancar no hay historia y los indicadores la necesitan (backfill);
  * si el WebSocket se cae y vuelve, quedan huecos que hay que cerrar.

Informe seccion 1.3[1]: el REST es respaldo y reconciliacion, no la via normal.
"""

from __future__ import annotations

import asyncio

from core.clock import candle_is_closed, timeframe_ms, utcnow_ms
from core.config import Settings
from core.events import EventBus, EventKind
from core.logging import get_logger
from data.exchange import Exchange
from data.store.repos import Candle, CandleRepo, Gap, GapRepo
from data.validate import validate_candle

log = get_logger(__name__)

# OKX devuelve como mucho 100 velas por peticion en el endpoint estandar.
MAX_PER_REQUEST = 100


class RestIngestor:
    def __init__(
        self,
        settings: Settings,
        exchange: Exchange,
        candles: CandleRepo,
        gaps: GapRepo,
        bus: EventBus | None = None,
    ) -> None:
        self.settings = settings
        self.exchange = exchange
        self.candles = candles
        self.gaps = gaps
        self.bus = bus

    async def _fetch_valid(
        self, symbol: str, timeframe: str, since_ms: int | None, limit: int
    ) -> list[Candle]:
        """Pide velas, descarta las invalidas y las no cerradas."""
        raw = await self.exchange.fetch_ohlcv(symbol, timeframe, since_ms, limit)
        now = utcnow_ms()
        reference = None
        last = self.candles.last_ts(symbol, timeframe)
        if last is not None:
            rows = self.candles.range(symbol, timeframe, last, last)
            if rows:
                reference = rows[0]["close"]

        out: list[Candle] = []
        for row in raw:
            candle = Candle.from_ccxt(
                symbol,
                timeframe,
                row,
                closed=candle_is_closed(int(row[0]), timeframe, now),
                source="rest",
            )
            if not candle.closed:
                continue  # informe 1.3[1]: solo velas cerradas
            verdict = validate_candle(candle, now_ms=now, reference_price=reference)
            if not verdict.ok:
                log.warning(
                    "vela descartada %s %s %s: %s",
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
                        source="rest",
                    )
                continue
            reference = candle.close
            out.append(candle)
        return out

    async def backfill(self, symbol: str, timeframe: str, count: int) -> int:
        """Trae las ultimas `count` velas cerradas. Idempotente."""
        step = timeframe_ms(timeframe)
        since = utcnow_ms() - (count + 2) * step
        total = 0
        cursor = since

        while True:
            batch = await self._fetch_valid(
                symbol, timeframe, cursor, min(MAX_PER_REQUEST, count)
            )
            if not batch:
                break
            total += await self.candles.upsert_many(batch)
            last_ts = batch[-1].ts_open_ms
            if last_ts <= cursor:
                break  # sin avance: evitamos el bucle infinito
            cursor = last_ts + step
            if cursor >= utcnow_ms() - step:
                break
            await asyncio.sleep(self.exchange.client.rateLimit / 1000)

        log.info("backfill %s %s: %d velas", symbol, timeframe, total)
        return total

    async def backfill_all(self) -> dict[str, int]:
        """Backfill de toda la whitelist y todos los timeframes."""
        results: dict[str, int] = {}
        for symbol in self.settings.whitelist:
            for timeframe in self.settings.data.timeframes:
                key = f"{symbol}|{timeframe}"
                try:
                    results[key] = await self.backfill(
                        symbol, timeframe, self.settings.data.backfill_candles
                    )
                except Exception as exc:
                    log.error("fallo el backfill de %s: %s", key, exc)
                    results[key] = -1
        return results

    async def fill_gap(self, gap: Gap) -> int:
        """Rellena un hueco concreto por REST."""
        step = timeframe_ms(gap.timeframe)
        needed = gap.missing_count
        filled = 0
        cursor = gap.ts_from_ms

        while filled < needed:
            batch = await self._fetch_valid(
                gap.symbol,
                gap.timeframe,
                cursor,
                min(MAX_PER_REQUEST, needed - filled + 2),
            )
            if not batch:
                break
            inside = [c for c in batch if gap.ts_from_ms <= c.ts_open_ms <= gap.ts_to_ms]
            if inside:
                await self.candles.upsert_many(inside)
                filled += len(inside)
            last_ts = batch[-1].ts_open_ms
            if last_ts < cursor:
                break
            cursor = last_ts + step
            if cursor > gap.ts_to_ms:
                break
            await asyncio.sleep(self.exchange.client.rateLimit / 1000)

        if filled:
            await self.gaps.mark_filled(gap)
            if self.bus:
                self.bus.emit(
                    EventKind.GAP_FILLED,
                    symbol=gap.symbol,
                    timeframe=gap.timeframe,
                    ts_from_ms=gap.ts_from_ms,
                    filled=filled,
                    expected=needed,
                )
            log.info(
                "hueco rellenado %s %s desde %d: %d/%d velas",
                gap.symbol,
                gap.timeframe,
                gap.ts_from_ms,
                filled,
                needed,
            )
        return filled

    async def scan_and_fill(self, window_ms: int | None = None) -> dict[str, int]:
        """Busca huecos en toda la whitelist y los rellena.

        Se ejecuta al arrancar y luego periodicamente. Es el mecanismo que hace
        alcanzable el criterio de avance de la fase 1 (72 h sin huecos): una
        caida breve del WebSocket no cuenta si se rellena despues.
        """
        window = window_ms or 72 * 3600 * 1000
        since = utcnow_ms() - window
        summary: dict[str, int] = {"detected": 0, "filled": 0, "candles": 0}

        for symbol in self.settings.whitelist:
            for timeframe in self.settings.data.timeframes:
                for gap in self.candles.find_gaps(symbol, timeframe, since):
                    summary["detected"] += 1
                    await self.gaps.record(gap)
                    if self.bus:
                        self.bus.emit(
                            EventKind.GAP_DETECTED,
                            symbol=symbol,
                            timeframe=timeframe,
                            ts_from_ms=gap.ts_from_ms,
                            missing=gap.missing_count,
                        )
                    got = await self.fill_gap(gap)
                    summary["candles"] += got
                    if got >= gap.missing_count:
                        summary["filled"] += 1
        return summary
