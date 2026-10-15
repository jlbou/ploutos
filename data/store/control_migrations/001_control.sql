-- La base de los comandos de Telegram (docs/diseno-comandos-telegram.md, pieza 5; 25/09/2026).
--
-- BASE PROPIA, como la de noticias: el servicio `ploutos-telegram` escribe aqui y las dos
-- carteras la LEEN en mode=ro. Un escritor por base (SQLite en WAL). La unica excepcion es
-- `run_telegram.py --levantar-kill`, que el propietario lanza a mano en el VPS (como `run_news.py --levantar`).
--
-- La pausa y la parada NO se guardan: se DERIVAN de los comandos (`notify.comandos.reconstruir`),
-- asi que sobreviven a cualquier reinicio y el juez las puede rederivar.

-- Cada comando que se EJECUTO (los que pasaron `interpretar`), y los del VPS.
CREATE TABLE IF NOT EXISTS control_comandos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,   -- el orden en que se aplican
    update_id    INTEGER UNIQUE,                      -- el de Telegram; NULL si viene del VPS
    ts_ms        INTEGER NOT NULL,                    -- hora del mensaje (Telegram) o de la orden
    recibido_ms  INTEGER NOT NULL,
    orden        TEXT    NOT NULL,                    -- notify.comandos.Orden
    texto        TEXT    NOT NULL,                    -- lo que escribio el propietario, o el motivo
    origen       TEXT    NOT NULL CHECK (origen IN ('telegram', 'vps'))
);

-- Los mensajes que NO se ejecutaron: solo el motivo, NUNCA el texto (puede ser de cualquiera).
CREATE TABLE IF NOT EXISTS control_ignorados (
    update_id    INTEGER PRIMARY KEY,
    recibido_ms  INTEGER NOT NULL,
    motivo       TEXT    NOT NULL
) WITHOUT ROWID;

-- Una fila por vuelta del sondeo: el juez mira aqui si el servicio estuvo parado.
CREATE TABLE IF NOT EXISTS control_lecturas (
    ms       INTEGER PRIMARY KEY,
    ok       INTEGER NOT NULL,
    updates  INTEGER NOT NULL,
    error    TEXT    NOT NULL               -- '' si ninguno; sin el token (scrub_url)
) WITHOUT ROWID;

-- Las respuestas van por la misma cola que los avisos (006_avisos.sql, mismo esquema), para
-- mandarlas con `notify.outbox.enviar_pendientes`. Clave `comando:<id>` o `ignorado:<update_id>`.
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
