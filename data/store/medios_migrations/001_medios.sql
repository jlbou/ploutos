-- Titulares de medios, EN SOMBRA (docs/diseno-medios-sombra.md). Solo los escribe ploutos-medios; nadie que decide
-- los lee. El titulo es texto NO confiable, ya en texto plano y recortado.
CREATE TABLE IF NOT EXISTS medios_titulares (
    id            TEXT PRIMARY KEY,          -- fuente:guid
    fuente        TEXT    NOT NULL,
    calidad       TEXT    NOT NULL,          -- A | B (puesta antes de mirar)
    titulo        TEXT    NOT NULL,
    enlace        TEXT    NOT NULL DEFAULT '',
    publicado_ms  INTEGER,                   -- NULL: el feed no traia una fecha legible
    visto_ms      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS medios_titulares_publicado ON medios_titulares (publicado_ms);

-- Cada lectura de cada fuente: para saber que fuentes funcionan y desde cuando.
CREATE TABLE IF NOT EXISTS medios_lecturas (
    ms        INTEGER NOT NULL,
    fuente    TEXT    NOT NULL,
    ok        INTEGER NOT NULL,
    titulares INTEGER NOT NULL,
    nuevos    INTEGER NOT NULL,
    error     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (ms, fuente)
);
