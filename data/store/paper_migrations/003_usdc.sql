-- La paridad de USDC con la que se decidio cada vela (regla 17, 22/09/2026).
--
-- Hasta hoy nadie la calculaba: valia 0,0 por defecto y la regla 17 no podia
-- saltar nunca. Ahora el bucle la deduce de cuatro libros publicos de OKX
-- (`features/usdc.py`) y la guarda aqui para que el juez pueda auditarla.
--
-- deviation_pct NULL = DESCONOCIDA (faltaba un precio, o A y C discrepaban), y
-- con ella no se entra.

CREATE TABLE IF NOT EXISTS paper_usdc (
    ts_ms         INTEGER PRIMARY KEY,
    primary_usd   REAL,      -- A: USDC/USDT x USDT/USD
    check_usd     REAL,      -- C: BTC/USD / BTC/USDC
    deviation_pct REAL,      -- (A - 1) x 100, solo si A y C coinciden
    detail        TEXT NOT NULL
) WITHOUT ROWID;
