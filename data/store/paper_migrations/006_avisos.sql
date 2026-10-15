-- Los avisos de Telegram, pendientes y enviados (PRD seccion 9; 24/09/2026).
--
-- POR QUE UNA TABLA Y NO ENVIAR DIRECTAMENTE: un aviso se escribe aqui en la
-- MISMA transaccion que la vela que lo produce (`store.save_step`). Asi:
-- - un reinicio a medias no lo pierde (si la vela no se guardo, el aviso
--   tampoco, y al reprocesarla se vuelve a generar una vez);
-- - no se repite (`clave` UNICA);
-- - si Telegram esta caido, se manda despues, y el bucle ni se entera.
-- Otro paso (`notify.outbox`) los envia y los marca.

CREATE TABLE IF NOT EXISTS paper_avisos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,   -- la vela (o el instante) que lo genera
    tipo         TEXT    NOT NULL,   -- operacion | modo | escalon | auth | resumen | parada
    clave        TEXT    NOT NULL UNIQUE,
    texto        TEXT    NOT NULL,   -- HTML de Telegram (notify.messages)
    enviado_ms   INTEGER,            -- NULL = pendiente
    intentos     INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    descartado   INTEGER NOT NULL DEFAULT 0   -- 1 = demasiado viejo para mandarlo ya
);

CREATE INDEX IF NOT EXISTS idx_paper_avisos_pendientes
    ON paper_avisos (id) WHERE enviado_ms IS NULL AND descartado = 0;
