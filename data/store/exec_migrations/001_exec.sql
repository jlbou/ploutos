-- La base del ejecutor (fase 4, `ploutos-exec`): var/ploutos-exec.db. UN escritor: el ejecutor.
-- Lee la cartera de la IA (var/ploutos-paper-ai.db), la ingesta (var/ploutos.db), las noticias y el control en
-- `mode=ro`; escribe solo aqui. El estado verdadero es el del EXCHANGE: esto es lo que el ejecutor sabe de el, y la
-- conciliacion lo corrige (gana el exchange).

-- La FOTO del saldo al arrancar por primera vez (saldo virtual, decision del propietario del 02/10): lo que no es del bot.
CREATE TABLE IF NOT EXISTS exec_foto (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    ts_ms       INTEGER NOT NULL,       -- desde aqui se copian decisiones (las de antes, no)
    capital_usd REAL    NOT NULL,       -- capital.initial_capital_usd de entonces
    datos       TEXT    NOT NULL        -- execution.equity.Foto.a_dict() en JSON
);

-- Cada decision de la cartera de la IA, tratada UNA vez: copiada u omitida (y por que).
CREATE TABLE IF NOT EXISTS exec_tratadas (
    decision_id    TEXT PRIMARY KEY,
    ts_ms          INTEGER NOT NULL,
    que            TEXT    NOT NULL,    -- copiada | omitida
    motivo         TEXT    NOT NULL,
    cantidad_papel REAL,
    cantidad       REAL                 -- la que se mando (min(papel, motor) al lote del demo)
) WITHOUT ROWID;

-- Entradas enviadas a OKX y aun no resueltas.
CREATE TABLE IF NOT EXISTS exec_entradas (
    decision_id TEXT PRIMARY KEY,
    simbolo     TEXT    NOT NULL,
    cantidad    REAL    NOT NULL,
    limite      REAL    NOT NULL,
    stop        REAL    NOT NULL,
    objetivo    REAL    NOT NULL,
    creada_ms   INTEGER NOT NULL,       -- la de la orden de PAPEL (el reloj de la caducidad)
    enviada_ms  INTEGER NOT NULL
) WITHOUT ROWID;

-- Posiciones abiertas en el demo (como mucho una por simbolo: regla 4).
CREATE TABLE IF NOT EXISTS exec_posiciones (
    decision_id TEXT PRIMARY KEY,
    simbolo     TEXT    NOT NULL,
    cantidad    REAL    NOT NULL,
    entrada     REAL    NOT NULL,       -- precio medio de llenado (avgPx)
    stop        REAL    NOT NULL,
    objetivo    REAL    NOT NULL,
    abierta_ms  INTEGER NOT NULL,
    comision_entrada_usd REAL NOT NULL DEFAULT 0,
    vendiendo_ms INTEGER                -- salida a mercado pedida (decision 4 del 02/10)
) WITHOUT ROWID;

-- Operaciones cerradas en el demo (reglas 10, 11 y 14 con datos del demo).
CREATE TABLE IF NOT EXISTS exec_cierres (
    decision_id     TEXT PRIMARY KEY,
    simbolo         TEXT    NOT NULL,
    cantidad        REAL    NOT NULL,
    entrada         REAL    NOT NULL,
    salida          REAL    NOT NULL,
    abierta_ms      INTEGER NOT NULL,
    cerrada_ms      INTEGER NOT NULL,
    motivo          TEXT    NOT NULL,   -- sl | tp | salida | desconocido
    pnl_usd         REAL    NOT NULL,
    por_stop        INTEGER NOT NULL,
    salida_estimada INTEGER NOT NULL DEFAULT 0   -- 1 = el precio de salida no se pudo leer de OKX
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_exec_cierres_ms ON exec_cierres (cerrada_ms);

-- TODA peticion a OKX y lo que contesto (trazabilidad, PRD 13). Nunca credenciales: solo la peticion y la respuesta.
CREATE TABLE IF NOT EXISTS exec_journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms       INTEGER NOT NULL,
    decision_id TEXT,
    que         TEXT    NOT NULL,       -- entrada | oco | cancelar_entrada | cancelar_oco | salida | veto | ...
    peticion    TEXT,
    resultado   TEXT    NOT NULL,
    detalle     TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_journal_did ON exec_journal (decision_id);

-- Cada pasada de la conciliacion (el juez de la fase 4 mira que corran y que no apunten descuadres).
CREATE TABLE IF NOT EXISTS exec_pasadas (
    ts_ms      INTEGER PRIMARY KEY,
    cuadra     INTEGER NOT NULL,
    acciones   TEXT    NOT NULL,        -- JSON
    descuadres TEXT    NOT NULL,        -- JSON
    sin_oco    TEXT    NOT NULL         -- JSON: las que se quedaron sin OCO en esta pasada
);

-- La regla 6 con datos del exchange: una fila por minuto (y toda lectura en o bajo el suelo).
CREATE TABLE IF NOT EXISTS exec_equity (
    ts_ms      INTEGER PRIMARY KEY,
    equity_usd REAL    NOT NULL,
    fiable     INTEGER NOT NULL,
    usdc_usd   REAL    NOT NULL,
    valor_usd  REAL    NOT NULL
);

-- Los cambios de modo del ejecutor (CAPITAL enclavado, DAILY, DEGRADED, pausa y parada).
CREATE TABLE IF NOT EXISTS exec_modos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms  INTEGER NOT NULL,
    modo   TEXT    NOT NULL,
    activo INTEGER NOT NULL,
    motivo TEXT    NOT NULL
);

-- Avisos de Telegram, igual que en las otras bases (notify/outbox.py los manda).
CREATE TABLE IF NOT EXISTS paper_avisos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    tipo         TEXT    NOT NULL,
    clave        TEXT    NOT NULL UNIQUE,
    texto        TEXT    NOT NULL,
    enviado_ms   INTEGER,
    intentos     INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    descartado   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_paper_avisos_pendientes
    ON paper_avisos (id) WHERE enviado_ms IS NULL AND descartado = 0;
