"""Acceso a las tablas de la fase 1.

Un repositorio por tabla. Sin logica de negocio: solo leer y escribir. Lo que
decide QUE se escribe vive en `data/ingest/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.clock import timeframe_ms, utcnow_ms
from core.events import Event
from core.modes import ModeChange
from data.store.db import Database


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    ts_open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool
    source: str

    @classmethod
    def from_ccxt(
        cls, symbol: str, timeframe: str, row: list[Any], closed: bool, source: str
    ) -> Candle:
        """ccxt devuelve [ts, open, high, low, close, volume]."""
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            ts_open_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            closed=closed,
            source=source,
        )

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.symbol,
            self.timeframe,
            self.ts_open_ms,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            int(self.closed),
            self.source,
            utcnow_ms(),
        )


@dataclass(frozen=True, slots=True)
class Gap:
    symbol: str
    timeframe: str
    ts_from_ms: int
    ts_to_ms: int
    missing_count: int


class CandleRepo:
    _UPSERT = """
        INSERT INTO candles
            (symbol, timeframe, ts_open_ms, open, high, low, close, volume,
             closed, source, ingested_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, timeframe, ts_open_ms) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            -- una vela cerrada nunca vuelve a abrirse
            closed = MAX(candles.closed, excluded.closed),
            source = excluded.source,
            ingested_ms = excluded.ingested_ms
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert_many(self, candles: list[Candle]) -> int:
        return await self.db.executemany(
            self._UPSERT, [c.as_row() for c in candles]
        )

    def upsert_many_sync(self, candles: list[Candle]) -> int:
        return self.db.executemany_sync(self._UPSERT, [c.as_row() for c in candles])

    def last_ts(self, symbol: str, timeframe: str, closed_only: bool = True) -> int | None:
        sql = "SELECT MAX(ts_open_ms) FROM candles WHERE symbol = ? AND timeframe = ?"
        if closed_only:
            sql += " AND closed = 1"
        return self.db.scalar(sql, (symbol, timeframe))

    def count(self, symbol: str, timeframe: str, closed_only: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM candles WHERE symbol = ? AND timeframe = ?"
        if closed_only:
            sql += " AND closed = 1"
        return int(self.db.scalar(sql, (symbol, timeframe)) or 0)

    def range(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int | None = None
    ) -> list[dict[str, Any]]:
        until = until_ms if until_ms is not None else utcnow_ms()
        rows = self.db.query(
            """
            SELECT * FROM candles
            WHERE symbol = ? AND timeframe = ? AND closed = 1
              AND ts_open_ms >= ? AND ts_open_ms <= ?
            ORDER BY ts_open_ms
            """,
            (symbol, timeframe, since_ms, until),
        )
        return [dict(r) for r in rows]

    def find_gaps(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int | None = None
    ) -> list[Gap]:
        """Huecos entre velas cerradas consecutivas.

        Es la medida del criterio de avance de la fase 1. No usa el reloj para
        nada mas que acotar la ventana: compara timestamps almacenados.
        """
        step = timeframe_ms(timeframe)
        until = until_ms if until_ms is not None else utcnow_ms()
        rows = self.db.query(
            """
            SELECT ts_open_ms FROM candles
            WHERE symbol = ? AND timeframe = ? AND closed = 1
              AND ts_open_ms >= ? AND ts_open_ms <= ?
            ORDER BY ts_open_ms
            """,
            (symbol, timeframe, since_ms, until),
        )
        stamps = [int(r["ts_open_ms"]) for r in rows]
        gaps: list[Gap] = []
        for prev, nxt in zip(stamps, stamps[1:]):
            missing = (nxt - prev) // step - 1
            if missing > 0:
                gaps.append(
                    Gap(symbol, timeframe, prev + step, nxt - step, int(missing))
                )
        return gaps


class L1Repo:
    _INSERT = """
        INSERT INTO l1_snapshots (symbol, ts_ms, bid, bid_size, ask, ask_size)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, ts_ms) DO NOTHING
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def insert_many(self, rows: list[tuple[Any, ...]]) -> int:
        return await self.db.executemany(self._INSERT, rows)

    def latest(self, symbol: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM l1_snapshots WHERE symbol = ? ORDER BY ts_ms DESC LIMIT 1",
            (symbol,),
        )
        return dict(row) if row else None


class BookMetricsRepo:
    _INSERT = """
        INSERT INTO book_metrics
            (symbol, ts_ms, mid, spread_pct, imbalance,
             depth_bid_05pct, depth_ask_05pct, depth_bid_01pct, depth_ask_01pct, levels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, ts_ms) DO NOTHING
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def insert_many(self, rows: list[tuple[Any, ...]]) -> int:
        return await self.db.executemany(self._INSERT, rows)

    def stats(self, symbol: str, since_ms: int) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT COUNT(*) AS n,
                   AVG(spread_pct) AS spread_avg,
                   MAX(spread_pct) AS spread_max,
                   AVG(MIN(depth_bid_05pct, depth_ask_05pct)) AS depth_avg
            FROM book_metrics WHERE symbol = ? AND ts_ms >= ?
            """,
            (symbol, since_ms),
        )
        return dict(row) if row and row["n"] else None


class HealthRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def touch(self, source: str, symbol: str, ts_ms: int) -> None:
        await self.db.execute(
            """
            INSERT INTO source_health
                (source, symbol, last_update_ms, state, reason, since_ms, updates)
            VALUES (?, ?, ?, 'OK', NULL, ?, 1)
            ON CONFLICT (source, symbol) DO UPDATE SET
                last_update_ms = excluded.last_update_ms,
                state = 'OK',
                reason = NULL,
                since_ms = CASE WHEN source_health.state != 'OK'
                                THEN excluded.last_update_ms ELSE source_health.since_ms END,
                updates = source_health.updates + 1
            """,
            (source, symbol, ts_ms, ts_ms),
        )

    async def mark_stale(
        self, source: str, symbol: str, reason: str, ts_ms: int
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO source_health
                (source, symbol, last_update_ms, state, reason, since_ms, stale_events)
            VALUES (?, ?, NULL, 'STALE', ?, ?, 1)
            ON CONFLICT (source, symbol) DO UPDATE SET
                state = 'STALE',
                reason = excluded.reason,
                since_ms = CASE WHEN source_health.state != 'STALE'
                                THEN excluded.since_ms ELSE source_health.since_ms END,
                stale_events = source_health.stale_events + 1
            """,
            (source, symbol, reason, ts_ms),
        )

    def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM source_health")]

    def stale(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query("SELECT * FROM source_health WHERE state = 'STALE'")
        ]


class GapRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, gap: Gap) -> None:
        await self.db.execute(
            """
            INSERT INTO data_gaps
                (symbol, timeframe, ts_from_ms, ts_to_ms, missing_count, detected_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, timeframe, ts_from_ms) DO UPDATE SET
                ts_to_ms = excluded.ts_to_ms,
                missing_count = excluded.missing_count
            """,
            (
                gap.symbol,
                gap.timeframe,
                gap.ts_from_ms,
                gap.ts_to_ms,
                gap.missing_count,
                utcnow_ms(),
            ),
        )

    async def mark_filled(self, gap: Gap, source: str = "rest") -> None:
        await self.db.execute(
            """
            UPDATE data_gaps SET filled_ms = ?, fill_source = ?
            WHERE symbol = ? AND timeframe = ? AND ts_from_ms = ?
            """,
            (utcnow_ms(), source, gap.symbol, gap.timeframe, gap.ts_from_ms),
        )

    def unfilled(self, since_ms: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM data_gaps WHERE filled_ms IS NULL"
        params: tuple[Any, ...] = ()
        if since_ms is not None:
            sql += " AND ts_from_ms >= ?"
            params = (since_ms,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY ts_from_ms", params)]


class InstrumentRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert_many(self, rows: list[tuple[Any, ...]]) -> int:
        return await self.db.executemany(
            """
            INSERT INTO instruments
                (symbol, base, quote, active, tick_size, lot_size, min_amount,
                 min_cost, maker_fee, taker_fee, raw, fetched_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol) DO UPDATE SET
                base = excluded.base, quote = excluded.quote, active = excluded.active,
                tick_size = excluded.tick_size, lot_size = excluded.lot_size,
                min_amount = excluded.min_amount, min_cost = excluded.min_cost,
                maker_fee = excluded.maker_fee, taker_fee = excluded.taker_fee,
                raw = excluded.raw, fetched_ms = excluded.fetched_ms
            """,
            rows,
        )

    def get(self, symbol: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM instruments WHERE symbol = ?", (symbol,))
        return dict(row) if row else None

    def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM instruments")]


class EventRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, event: Event) -> None:
        row = event.to_row()
        await self.db.execute(
            """
            INSERT INTO events (ts, kind, symbol, decision_id, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["ts"], row["kind"], row["symbol"], row["decision_id"], row["payload"]),
        )

    def recent(self, limit: int = 100, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query(
                "SELECT * FROM events WHERE kind = ? ORDER BY id DESC LIMIT ?",
                (kind, limit),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in rows]

    def count(self, kind: str | None = None) -> int:
        if kind:
            return int(
                self.db.scalar("SELECT COUNT(*) FROM events WHERE kind = ?", (kind,)) or 0
            )
        return int(self.db.scalar("SELECT COUNT(*) FROM events") or 0)


class ModeRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, change: ModeChange) -> None:
        await self.db.execute(
            """
            INSERT INTO mode_changes
                (ts, mode, activated, reason, effective_before, effective_after)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                change.ts.isoformat(),
                str(change.mode),
                int(change.activated),
                change.reason,
                str(change.effective_before),
                str(change.effective_after),
            ),
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                "SELECT * FROM mode_changes ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]
