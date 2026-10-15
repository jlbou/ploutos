-- Ploutos 001: esquema de la fase 1 (ingesta de datos).
--
-- Reglas transversales (PRD seccion 13):
--   * todo timestamp es UTC, en milisegundos desde epoch (ts_ms) o ISO-8601 (ts).
--   * lo que forme parte de la cadena de decision lleva decision_id.
--
-- Las tablas de las fases 2+ (features, candidates, risk_verdicts, orders,
-- fills, positions, equity_snapshots, llm_calls, hypotheses) llegan en sus
-- migraciones. Aqui solo lo que la fase 1 necesita de verdad.

-- Velas OHLCV. Fuente de todo lo demas.
-- `closed` distingue la vela en curso de la cerrada: los indicadores solo usan
-- las cerradas (informe seccion 1.3[1], evita look-ahead bias).
CREATE TABLE IF NOT EXISTS candles (
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    ts_open_ms  INTEGER NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0,
    source      TEXT    NOT NULL,            -- 'ws' | 'rest'
    ingested_ms INTEGER NOT NULL,
    PRIMARY KEY (symbol, timeframe, ts_open_ms)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_candles_lookup
    ON candles (symbol, timeframe, closed, ts_open_ms DESC);

-- Mejor bid/ask. Persistido cada N s (data.persist.l1_interval_seconds); en
-- memoria se actualiza a la velocidad del WebSocket.
-- Es la fuente del equity (regla 6: cantidad x mejor bid).
CREATE TABLE IF NOT EXISTS l1_snapshots (
    symbol    TEXT    NOT NULL,
    ts_ms     INTEGER NOT NULL,
    bid       REAL    NOT NULL,
    bid_size  REAL    NOT NULL,
    ask       REAL    NOT NULL,
    ask_size  REAL    NOT NULL,
    PRIMARY KEY (symbol, ts_ms)
) WITHOUT ROWID;

-- Metricas derivadas del libro. Guardamos los numeros, no el libro entero:
-- 72 h de libros completos de 8 monedas no caben comodamente en SQLite y no
-- aportan nada que estas columnas no digan.
CREATE TABLE IF NOT EXISTS book_metrics (
    symbol          TEXT    NOT NULL,
    ts_ms           INTEGER NOT NULL,
    mid             REAL    NOT NULL,
    spread_pct      REAL    NOT NULL,   -- (ask - bid) / mid * 100
    imbalance       REAL    NOT NULL,   -- (bid_vol - ask_vol) / (bid_vol + ask_vol) top-10
    depth_bid_05pct REAL    NOT NULL,   -- $ hasta 0,5 % por debajo del mid
    depth_ask_05pct REAL    NOT NULL,   -- $ hasta 0,5 % por encima del mid
    depth_bid_01pct REAL    NOT NULL,
    depth_ask_01pct REAL    NOT NULL,
    levels          INTEGER NOT NULL,
    PRIMARY KEY (symbol, ts_ms)
) WITHOUT ROWID;

-- Estado de frescura por (fuente, simbolo). Informe seccion 1.3[1].
-- Una fila por combinacion; se actualiza en sitio.
CREATE TABLE IF NOT EXISTS source_health (
    source          TEXT    NOT NULL,   -- 'candles:1m' | 'ticker' | 'orderbook'
    symbol          TEXT    NOT NULL,
    last_update_ms  INTEGER,
    state           TEXT    NOT NULL DEFAULT 'UNKNOWN',  -- OK | STALE | UNKNOWN
    reason          TEXT,
    since_ms        INTEGER,
    updates         INTEGER NOT NULL DEFAULT 0,
    stale_events    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, symbol)
) WITHOUT ROWID;

-- Huecos de velas detectados. ES EL CRITERIO DE AVANCE DE LA FASE 1:
-- 72 h sin huecos sin rellenar.
CREATE TABLE IF NOT EXISTS data_gaps (
    symbol         TEXT    NOT NULL,
    timeframe      TEXT    NOT NULL,
    ts_from_ms     INTEGER NOT NULL,   -- primera vela que falta
    ts_to_ms       INTEGER NOT NULL,   -- ultima vela que falta
    missing_count  INTEGER NOT NULL,
    detected_ms    INTEGER NOT NULL,
    filled_ms      INTEGER,            -- NULL = sigue sin rellenar
    fill_source    TEXT,
    PRIMARY KEY (symbol, timeframe, ts_from_ms)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_gaps_unfilled
    ON data_gaps (filled_ms, detected_ms);

-- Filtros del instrumento leidos al arrancar (informe seccion 1.6).
-- El redondeo de cantidad SIEMPRE va hacia abajo usando lot_size.
CREATE TABLE IF NOT EXISTS instruments (
    symbol           TEXT PRIMARY KEY,
    base             TEXT    NOT NULL,
    quote            TEXT    NOT NULL,
    active           INTEGER NOT NULL,
    tick_size        REAL,
    lot_size         REAL,
    min_amount       REAL,
    min_cost         REAL,
    maker_fee        REAL,
    taker_fee        REAL,
    raw              TEXT,
    fetched_ms       INTEGER NOT NULL
) WITHOUT ROWID;

-- Log general de eventos. Todo lo que pase queda aqui.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    symbol      TEXT,
    decision_id TEXT,
    payload     TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_decision ON events (decision_id)
    WHERE decision_id IS NOT NULL;

-- Cambios de modo (PRD seccion 5). Se notifican por Telegram desde la fase 5.
CREATE TABLE IF NOT EXISTS mode_changes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT    NOT NULL,
    mode             TEXT    NOT NULL,
    activated        INTEGER NOT NULL,
    reason           TEXT    NOT NULL,
    effective_before TEXT    NOT NULL,
    effective_after  TEXT    NOT NULL
);
