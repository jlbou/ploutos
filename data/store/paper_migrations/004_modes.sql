-- Transiciones de modo del bucle de papel (PRD seccion 5, 22/09/2026).
--
-- Hasta hoy el bucle vivia siempre en NORMAL: la maquina de modos
-- (`core/modes.py`) existia y estaba probada, pero nadie la usaba. Ahora el
-- bucle activa CLOSE_ONLY_DAILY (regla 10) y CLOSE_ONLY_CAPITAL (regla 7), y al
-- entrar en cualquiera cancela las entradas pendientes.
--
-- POR QUE SE GUARDA: CLOSE_ONLY_CAPITAL es ENCLAVADO. Si viviera solo en
-- memoria, un reinicio lo levantaria, y la regla 7 dice que solo sale con reset
-- manual. Al arrancar se reconstruye reproduciendo estas filas en orden.
-- Tambien es trazabilidad: cuando y por que se dejo de abrir.

CREATE TABLE IF NOT EXISTS paper_mode_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms           INTEGER NOT NULL,   -- la vela (o el instante del reset manual)
    mode            TEXT    NOT NULL,   -- nombre del Mode
    activated       INTEGER NOT NULL,   -- 1 entra, 0 sale
    reason          TEXT    NOT NULL,
    effective_after TEXT    NOT NULL
);
