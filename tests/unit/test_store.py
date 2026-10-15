"""Almacenamiento: WAL, migraciones, upsert idempotente y deteccion de huecos."""

from __future__ import annotations

import pytest

from core.clock import timeframe_ms, utcnow_ms
from data.store.db import Database, applied_versions, migrate, open_database
from data.store.repos import Candle, CandleRepo, EventRepo, GapRepo, HealthRepo

STEP = timeframe_ms("1m")
BASE = 1_790_000_000_000 - (1_790_000_000_000 % STEP)


def make_candle(i: int, symbol: str = "BTC/USDC", **kwargs) -> Candle:
    base = {
        "symbol": symbol,
        "timeframe": "1m",
        "ts_open_ms": BASE + i * STEP,
        "open": 100.0 + i,
        "high": 101.0 + i,
        "low": 99.0 + i,
        "close": 100.5 + i,
        "volume": 10.0,
        "closed": True,
        "source": "ws",
    }
    base.update(kwargs)
    return Candle(**base)


# --- conexion y WAL ---


def test_wal_esta_activo(db):
    mode = db.scalar("PRAGMA journal_mode")
    assert mode.lower() == "wal"


def test_foreign_keys_activas(db):
    assert db.scalar("PRAGMA foreign_keys") == 1


def test_usar_sin_conectar_falla(tmp_path):
    database = Database(tmp_path / "x.db")
    with pytest.raises(RuntimeError, match="no esta conectada"):
        _ = database.conn


def test_context_manager(tmp_path):
    with Database(tmp_path / "x.db") as database:
        assert database.scalar("SELECT 1") == 1


# --- migraciones ---


def test_la_migracion_crea_las_tablas(db):
    tables = {
        row["name"]
        for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in (
        "candles", "l1_snapshots", "book_metrics", "source_health",
        "data_gaps", "instruments", "events", "mode_changes", "schema_version",
    ):
        assert expected in tables


def test_migrar_dos_veces_es_idempotente(db):
    before = applied_versions(db)
    applied = migrate(db)
    assert applied == []
    assert applied_versions(db) == before


def test_open_database_migra(tmp_path):
    database = open_database(tmp_path / "nueva.db")
    try:
        assert 1 in applied_versions(database)
    finally:
        database.close()


# --- velas ---


async def test_upsert_y_lectura(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i) for i in range(5)])
    assert repo.count("BTC/USDC", "1m") == 5
    assert repo.last_ts("BTC/USDC", "1m") == BASE + 4 * STEP


async def test_upsert_es_idempotente(db):
    """Reingerir las mismas velas no las duplica. Importa porque el relleno de
    huecos por REST solapa a proposito con lo que ya hay."""
    repo = CandleRepo(db)
    candles = [make_candle(i) for i in range(5)]
    await repo.upsert_many(candles)
    await repo.upsert_many(candles)
    await repo.upsert_many(candles)
    assert repo.count("BTC/USDC", "1m") == 5


async def test_upsert_actualiza_los_valores(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(0, close=100.0)])
    await repo.upsert_many([make_candle(0, close=999.0)])
    rows = repo.range("BTC/USDC", "1m", BASE, BASE)
    assert rows[0]["close"] == 999.0


async def test_una_vela_cerrada_nunca_vuelve_a_abrirse(db):
    """El WebSocket puede reenviar la vela en curso despues de que cerrase.
    Si eso la marcase como abierta, saldria del calculo de indicadores."""
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(0, closed=True)])
    await repo.upsert_many([make_candle(0, closed=False)])
    assert repo.count("BTC/USDC", "1m", closed_only=True) == 1


async def test_las_velas_abiertas_no_cuentan(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(0, closed=False)])
    assert repo.count("BTC/USDC", "1m", closed_only=True) == 0
    assert repo.count("BTC/USDC", "1m", closed_only=False) == 1


async def test_los_simbolos_no_se_mezclan(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i, symbol="BTC/USDC") for i in range(3)])
    await repo.upsert_many([make_candle(i, symbol="ETH/USDC") for i in range(5)])
    assert repo.count("BTC/USDC", "1m") == 3
    assert repo.count("ETH/USDC", "1m") == 5


async def test_sin_datos_last_ts_es_none(db):
    assert CandleRepo(db).last_ts("BTC/USDC", "1m") is None


# --- huecos: el criterio de avance de la fase 1 ---


async def test_serie_continua_no_tiene_huecos(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i) for i in range(30)])
    assert repo.find_gaps("BTC/USDC", "1m", BASE) == []


async def test_una_vela_que_falta_es_un_hueco(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i) for i in range(10) if i != 5])
    gaps = repo.find_gaps("BTC/USDC", "1m", BASE)
    assert len(gaps) == 1
    assert gaps[0].missing_count == 1
    assert gaps[0].ts_from_ms == BASE + 5 * STEP
    assert gaps[0].ts_to_ms == BASE + 5 * STEP


async def test_varias_velas_seguidas_son_un_solo_hueco(db):
    repo = CandleRepo(db)
    keep = [i for i in range(20) if i not in (5, 6, 7, 8)]
    await repo.upsert_many([make_candle(i) for i in keep])
    gaps = repo.find_gaps("BTC/USDC", "1m", BASE)
    assert len(gaps) == 1
    assert gaps[0].missing_count == 4


async def test_dos_huecos_separados(db):
    repo = CandleRepo(db)
    keep = [i for i in range(20) if i not in (3, 10, 11)]
    await repo.upsert_many([make_candle(i) for i in keep])
    gaps = repo.find_gaps("BTC/USDC", "1m", BASE)
    assert len(gaps) == 2
    assert [g.missing_count for g in gaps] == [1, 2]


async def test_las_velas_abiertas_no_tapan_un_hueco(db):
    """Una vela sin cerrar no cuenta como dato: el hueco sigue ahi."""
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i) for i in range(10) if i != 5])
    await repo.upsert_many([make_candle(5, closed=False)])
    gaps = repo.find_gaps("BTC/USDC", "1m", BASE)
    assert len(gaps) == 1


async def test_rellenar_el_hueco_lo_hace_desaparecer(db):
    repo = CandleRepo(db)
    await repo.upsert_many([make_candle(i) for i in range(10) if i != 5])
    assert len(repo.find_gaps("BTC/USDC", "1m", BASE)) == 1
    await repo.upsert_many([make_candle(5, source="rest")])
    assert repo.find_gaps("BTC/USDC", "1m", BASE) == []


# --- registro de huecos ---


async def test_registrar_y_marcar_un_hueco_como_relleno(db):
    candles, gaps_repo = CandleRepo(db), GapRepo(db)
    await candles.upsert_many([make_candle(i) for i in range(10) if i != 5])
    gap = candles.find_gaps("BTC/USDC", "1m", BASE)[0]

    await gaps_repo.record(gap)
    assert len(gaps_repo.unfilled()) == 1

    await gaps_repo.mark_filled(gap)
    assert gaps_repo.unfilled() == []


async def test_registrar_el_mismo_hueco_dos_veces_no_duplica(db):
    candles, gaps_repo = CandleRepo(db), GapRepo(db)
    await candles.upsert_many([make_candle(i) for i in range(10) if i != 5])
    gap = candles.find_gaps("BTC/USDC", "1m", BASE)[0]
    await gaps_repo.record(gap)
    await gaps_repo.record(gap)
    assert len(gaps_repo.unfilled()) == 1


# --- salud de las fuentes ---


async def test_touch_marca_ok(db):
    repo = HealthRepo(db)
    await repo.touch("ticker", "BTC/USDC", utcnow_ms())
    rows = repo.all()
    assert rows[0]["state"] == "OK"
    assert rows[0]["updates"] == 1


async def test_touch_acumula_actualizaciones(db):
    repo = HealthRepo(db)
    for _ in range(5):
        await repo.touch("ticker", "BTC/USDC", utcnow_ms())
    assert repo.all()[0]["updates"] == 5


async def test_marcar_stale_y_recuperar(db):
    repo = HealthRepo(db)
    now = utcnow_ms()
    await repo.touch("ticker", "BTC/USDC", now)
    await repo.mark_stale("ticker", "BTC/USDC", "sin actualizar", now)
    assert len(repo.stale()) == 1
    await repo.touch("ticker", "BTC/USDC", now + 1000)
    assert repo.stale() == []


# --- eventos ---


async def test_los_eventos_se_guardan(db):
    from core.events import Event, EventKind

    repo = EventRepo(db)
    await repo.record(Event(kind=EventKind.GAP_DETECTED, symbol="BTC/USDC",
                            payload={"missing": 3}))
    assert repo.count() == 1
    assert repo.recent()[0]["kind"] == EventKind.GAP_DETECTED


async def test_el_decision_id_se_conserva(db):
    """PRD seccion 13: la cadena candidato -> IA -> veredicto -> orden."""
    from core.events import Event

    repo = EventRepo(db)
    await repo.record(Event(kind="candidate", decision_id="d-123"))
    assert repo.recent()[0]["decision_id"] == "d-123"
