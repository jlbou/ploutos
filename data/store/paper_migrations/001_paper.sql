-- Estado del bucle de papel. BASE DE DATOS SEPARADA, y es deliberado.
--
-- Durante las 72 h del criterio de avance de la fase 1, el proceso de ingesta
-- es lo que se esta midiendo. SQLite en WAL admite un escritor y varios
-- lectores: si el bucle de papel escribiera en la MISMA base, sus escrituras
-- competirian con las de la ingesta por el bloqueo de escritura. Con
-- `busy_timeout=5000`, una transaccion larga del bucle podria hacer que la
-- ingesta esperase 5 s y fallara una escritura, perdiendo una vela y creando
-- un hueco. O sea: poniendo en riesgo justo lo que se esta midiendo.
--
-- Leer de la base principal NO tiene ese problema (en WAL los lectores nunca
-- bloquean al escritor), asi que el bucle lee velas de alli y escribe aqui.
--
-- CONSECUENCIA: la cadena del `decision_id` (PRD seccion 13) vive repartida en
-- dos ficheros. Se consulta con ATTACH. Cuando las 72 h esten cerradas, esto
-- se puede unificar en una migracion; mientras tanto, la separacion vale mas
-- que la comodidad.

-- Ordenes de entrada limit, pendientes o resueltas.
CREATE TABLE IF NOT EXISTS paper_orders (
    decision_id  TEXT PRIMARY KEY,
    symbol       TEXT    NOT NULL,
    qty          REAL    NOT NULL,
    limit_price  REAL    NOT NULL,
    stop_price   REAL    NOT NULL,
    target_price REAL    NOT NULL,
    setup        TEXT    NOT NULL,
    created_ts_ms INTEGER NOT NULL,
    state        TEXT    NOT NULL,
    bars_waited  INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;

-- Posiciones abiertas. Una por simbolo como mucho (regla 4).
CREATE TABLE IF NOT EXISTS paper_positions (
    symbol        TEXT PRIMARY KEY,
    decision_id   TEXT    NOT NULL,
    qty           REAL    NOT NULL,
    entry_price   REAL    NOT NULL,
    stop_price    REAL    NOT NULL,
    target_price  REAL    NOT NULL,
    setup         TEXT    NOT NULL,
    opened_ts_ms  INTEGER NOT NULL,
    entry_fee_usd REAL    NOT NULL,
    worst_price   REAL    NOT NULL,
    best_price    REAL    NOT NULL
) WITHOUT ROWID;

-- Operaciones cerradas. Es la unidad de medida de la fase 6.
CREATE TABLE IF NOT EXISTS paper_trades (
    decision_id    TEXT PRIMARY KEY,
    symbol         TEXT    NOT NULL,
    setup          TEXT    NOT NULL,
    decider        TEXT    NOT NULL,   -- 'baseline' | 'ai', para comparar
    qty            REAL    NOT NULL,
    entry_price    REAL    NOT NULL,
    exit_price     REAL    NOT NULL,
    stop_price     REAL    NOT NULL,
    target_price   REAL    NOT NULL,
    opened_ts_ms   INTEGER NOT NULL,
    closed_ts_ms   INTEGER NOT NULL,
    reason         TEXT    NOT NULL,   -- 'stop' | 'target'
    entry_fee_usd  REAL    NOT NULL,
    exit_fee_usd   REAL    NOT NULL,
    exit_was_maker INTEGER NOT NULL,
    mae_pct        REAL    NOT NULL,
    mfe_pct        REAL    NOT NULL,
    net_pnl_usd    REAL    NOT NULL,
    r_multiple     REAL    NOT NULL
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_paper_trades_cierre
    ON paper_trades (closed_ts_ms DESC);

-- Equity vela a vela, para la curva y el drawdown.
CREATE TABLE IF NOT EXISTS paper_equity (
    ts_ms      INTEGER PRIMARY KEY,
    equity_usd REAL    NOT NULL,
    positions  INTEGER NOT NULL,
    pending    INTEGER NOT NULL
) WITHOUT ROWID;

-- HASTA QUE VELA SE HA PROCESADO. Sin esto, un reinicio volveria a procesar
-- velas ya vistas y duplicaria decisiones.
CREATE TABLE IF NOT EXISTS paper_cursor (
    timeframe  TEXT PRIMARY KEY,
    last_ts_ms INTEGER NOT NULL
) WITHOUT ROWID;

-- Journal de decisiones: candidatos, vetos y descartes. Es lo que alimenta el
-- panel "que esta pensando" del PRD seccion 10 y lo que permite responder
-- "por que esta moneda lleva un dia sin producir nada".
CREATE TABLE IF NOT EXISTS paper_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    decision_id  TEXT,
    symbol       TEXT,
    setup        TEXT,
    kind         TEXT    NOT NULL,   -- 'candidate' | 'submitted' | 'vetoed' | 'filtered'
    detail       TEXT
);

CREATE INDEX IF NOT EXISTS idx_paper_decisions_ts
    ON paper_decisions (ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_paper_decisions_id
    ON paper_decisions (decision_id) WHERE decision_id IS NOT NULL;
