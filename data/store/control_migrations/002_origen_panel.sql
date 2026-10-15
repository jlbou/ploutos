-- Los comandos tambien pueden venir del PANEL (fase 5; decision del propietario del 26/09/2026): pausar, quitar
-- la pausa, parar, levantar la parada y "cerrar todo". SQLite no deja cambiar un CHECK: se rehace la tabla
-- con las mismas filas y los mismos id (el orden en que se aplican los comandos).
CREATE TABLE control_comandos_nueva (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    update_id    INTEGER UNIQUE,
    ts_ms        INTEGER NOT NULL,
    recibido_ms  INTEGER NOT NULL,
    orden        TEXT    NOT NULL,
    texto        TEXT    NOT NULL,
    origen       TEXT    NOT NULL CHECK (origen IN ('telegram', 'vps', 'panel'))
);
INSERT INTO control_comandos_nueva (id, update_id, ts_ms, recibido_ms, orden, texto, origen)
    SELECT id, update_id, ts_ms, recibido_ms, orden, texto, origen FROM control_comandos;
DROP TABLE control_comandos;
ALTER TABLE control_comandos_nueva RENAME TO control_comandos;
