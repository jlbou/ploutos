-- El journal del analista (pieza 8 del plan de la fase 3, 23/09/2026).
--
-- Cada vez que el analista DEBIA decidir queda una fila en `ai_calls`, se le
-- llamara o no: tambien cuando no se llamo porque el presupuesto de la regla 18
-- estaba agotado o el bot estaba en CLOSE_ONLY_QUOTA. Sin esa fila, la cadena
-- candidato -> IA -> veredicto (PRD seccion 13) tendria un hueco justo donde
-- mas importa explicar por que no se hizo nada.
--
-- Se guarda tambien la entrada y la salida CRUDAS: la prueba en seco del
-- 22/09/2026 enseno que una salida invalida no se puede explicar despues si no
-- esta guardada tal cual. ~3-5 KB por llamada y 1-6 llamadas al dia: nada.
--
-- Nunca hay secretos: la entrada no los lleva (regla 19, con test) y el detalle
-- de los errores pasa por `ai.quota.classify(secret=...)`.

CREATE TABLE IF NOT EXISTS ai_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms          INTEGER NOT NULL,   -- la vela en la que se decidia (o el instante de la sonda)
    called_ms      INTEGER NOT NULL,   -- reloj real al llamar
    kind           TEXT    NOT NULL,   -- 'decision' | 'probe'
    outcome        TEXT    NOT NULL,   -- ok | quota | auth | timeout | error | skipped_budget | skipped_quota | skipped_stale
    valid          INTEGER NOT NULL,   -- 1 si la salida cumplio el contrato
    reason         TEXT    NOT NULL,
    n_candidates   INTEGER NOT NULL,
    latency_s      REAL,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cache_created  INTEGER,
    cost_usd_equiv REAL,
    num_turns      INTEGER,
    prompt         TEXT,               -- la entrada, tal cual se envio
    structured     TEXT,               -- structured_output, en JSON
    result_text    TEXT                -- el texto de la respuesta, recortado
);

CREATE INDEX IF NOT EXISTS idx_ai_calls_ts ON ai_calls (ts_ms);

-- Las decisiones de una llamada VALIDA: una por CADA candidato (tambien los que el
-- modelo no menciono, como skip) y una por cada decision sobre posiciones.
-- `executed` = 1 para open/skip; 0 para close/hold/tighten_stop, que se registran
-- pero no se ejecutan (decision D del propietario).
CREATE TABLE IF NOT EXISTS ai_decisions (
    call_id         INTEGER NOT NULL REFERENCES ai_calls (id),
    ref             TEXT    NOT NULL,
    type            TEXT    NOT NULL,
    size_multiplier REAL,
    confidence      REAL,              -- NULL si el modelo no menciono el candidato
    reasons         TEXT    NOT NULL,  -- JSON
    risks           TEXT    NOT NULL,  -- JSON
    executed        INTEGER NOT NULL,
    PRIMARY KEY (call_id, ref)
) WITHOUT ROWID;
