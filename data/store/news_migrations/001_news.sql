-- La base de la pieza de noticias (docs/diseno-noticias.md, pieza 4; 25/09/2026).
--
-- BASE PROPIA, como decidio el propietario (opcion B): el servicio `ploutos-news` escribe aqui y los
-- bucles de papel la LEEN en mode=ro. Un escritor por base (SQLite en WAL): si la fuente de
-- noticias falla o el servicio se cuelga, no arrastra ni a la ingesta ni a las carteras.
--
-- Las flags NO se guardan: se DERIVAN cada vez de los anuncios y de las levantadas
-- (`features.news.flags`), igual que las reglas 10, 11 y 14 se derivan de las operaciones.
-- Lo que vive en memoria se pierde al reiniciar; lo que se deriva de lo guardado, no.

-- Cada anuncio visto una vez. `id` = su URL (unica por anuncio).
CREATE TABLE IF NOT EXISTS news_anuncios (
    id            TEXT PRIMARY KEY,
    publicado_ms  INTEGER NOT NULL,   -- pTime de OKX: desde aqui cuenta la flag
    titulo        TEXT    NOT NULL,   -- texto NO confiable (PRD 6): se escapa al ensenyarlo
    visto_ms      INTEGER NOT NULL
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_news_anuncios_publicado ON news_anuncios (publicado_ms);

-- Las flags que el propietario levanto a mano (decision 5: el deslistado no caduca solo). Por clave de
-- flag (`Flag.clave`), no por moneda: levantar una no borra las demas de la misma moneda.
CREATE TABLE IF NOT EXISTS news_levantadas (
    clave         TEXT PRIMARY KEY,
    levantada_ms  INTEGER NOT NULL,
    motivo        TEXT    NOT NULL
) WITHOUT ROWID;

-- Una fila por pasada: si leyo, cuantos, cuantos nuevos y que fallo. El juez mira aqui si el
-- servicio estuvo parado, y el propio servicio, desde cuando la fuente no responde.
CREATE TABLE IF NOT EXISTS news_lecturas (
    ms        INTEGER PRIMARY KEY,
    ok        INTEGER NOT NULL,       -- 1 si leyo al menos un tipo sin error
    anuncios  INTEGER NOT NULL,
    nuevos    INTEGER NOT NULL,
    errores   TEXT    NOT NULL        -- '' si ninguno
) WITHOUT ROWID;

-- La misma cola de avisos de Telegram que las carteras (006_avisos.sql, mismo esquema), para
-- mandarlos con `notify.outbox.enviar_pendientes` sin escribir otro sistema de envio.
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
