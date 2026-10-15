-- Con que datos de mercado se decidio cada vela (22/09/2026).
--
-- POR QUE: el journal guardaba QUE se decidio pero no CON QUE. Sin el spread
-- de cada instante no se puede auditar la regla 16, y sin las correlaciones no
-- se puede auditar la mitad de correlacion de la 15: `portfolio/audit.py` lo
-- tenia que dejar fuera. Y es trazabilidad (PRD seccion 13): dentro de un mes,
-- "por que se veto esta entrada" tiene que poder contestarse con lo guardado,
-- no recalculando con datos que ya no son los de aquel momento.
--
-- Volumen: 8 filas de mercado y 28 de correlacion por vela de 4 h. Nada.

-- El libro que vio el bucle para cada simbolo en esa vela.
CREATE TABLE IF NOT EXISTS paper_market (
    ts_ms      INTEGER NOT NULL,
    symbol     TEXT    NOT NULL,
    spread_pct REAL    NOT NULL,
    depth_usd  REAL    NOT NULL,   -- el lado mas flojo, hasta el 0,5 %
    PRIMARY KEY (ts_ms, symbol)
) WITHOUT ROWID;

-- Las correlaciones de 7 dias con las que juzgo la regla 15. Los pares SIN
-- muestra suficiente no estan (features/context.py no los registra), y el
-- motor los trata como 0,0: el auditor tiene que hacer lo mismo.
CREATE TABLE IF NOT EXISTS paper_correlations (
    ts_ms INTEGER NOT NULL,
    a     TEXT    NOT NULL,
    b     TEXT    NOT NULL,
    corr  REAL    NOT NULL,
    PRIMARY KEY (ts_ms, a, b)
) WITHOUT ROWID;
