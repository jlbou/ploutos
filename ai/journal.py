"""De una llamada al analista a filas del journal (pieza 8 del plan de la fase 3).

`portfolio/store.py` escribe el journal pero no puede importar `ai/` (regla de
arquitectura), asi que recibe diccionarios planos con columnas de una lista
cerrada. Este modulo los prepara.

Tres casos, y los tres dejan fila (ver 005_ai.sql):
- una llamada hecha (`call_row` + `decision_rows`);
- una llamada que NO se hizo por el presupuesto de la regla 18 o por estar en
  CLOSE_ONLY_QUOTA (`skipped_row`): sin esta fila, "por que no se hizo nada" no
  tendria respuesta en lo guardado.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ai.contract import SCHEMA_JSON, DecisionType
from ai.invoke import VERIFIED_VERSION, AnalystCall
from ai.prompt import INSTRUCCION, SYSTEM_PROMPT
from core.config import Settings

SKIPPED_BUDGET = "skipped_budget"
SKIPPED_QUOTA = "skipped_quota"
# Vela atrasada tras una parada: sus precios ya no existen (decision del propietario del 23/09).
SKIPPED_STALE = "skipped_stale"


# Las llamadas en SOMBRA (decision 5 del protocolo de la fase 6, opcion B del propietario del 02/10): con la cartera
# llena, la IA decide igual que si hubiera un hueco y no se abre nada. Se juzgan APARTE (`check_fase6.py --sombra`):
# ningun juez las mezcla con las de verdad (todos filtran `kind = 'decision'`).
SOMBRA = "sombra"


def camino(settings: Settings) -> str:
    """Huella de TODO lo que define una decision del analista (protocolo de la fase 6).

    Si cambia cualquiera de estas piezas, la IA que decide ya es otra y la muestra
    de la fase 6 se parte en tramos: el prompt de sistema, la instruccion, el
    esquema, el modelo pedido, la version del CLI, y la configuracion que da forma
    a los candidatos y a lo que se abre (whitelist, estrategia, riesgo, escalones,
    capital, comisiones). NO entra lo que no cambia la decision (rutas, logs,
    presupuesto de llamadas, caducidad del token).
    """
    partes = {
        # Sin CR: en Windows el .md puede salir con CRLF y la huella no coincidiria con la del VPS.
        "system_prompt": SYSTEM_PROMPT.replace(chr(13), ""),
        "instruccion": INSTRUCCION,
        "esquema": SCHEMA_JSON,
        "modelo": settings.claude.model,
        "cli": VERIFIED_VERSION,
        "config": settings.model_dump(
            mode="json",
            include={"whitelist", "capital", "risk", "drawdown_tiers", "strategy"},
        ),
        "comisiones": settings.exchange.fees.model_dump(mode="json"),
    }
    texto = json.dumps(partes, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def call_row(
    call: AnalystCall, *, ts_ms: int, called_ms: int, kind: str, prompt: str | None,
    n_candidates: int, camino: str | None = None,
) -> dict[str, Any]:
    return {
        "ts_ms": ts_ms,
        "called_ms": called_ms,
        "kind": kind,
        "outcome": call.outcome.value,
        "valid": int(call.parsed.ok),
        # Si la llamada fue bien pero la salida no vale, el motivo es del PARSER.
        "reason": call.parsed.reason if call.outcome.value == "ok" else call.detail,
        "n_candidates": n_candidates,
        "latency_s": round(call.latency_s, 3),
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cache_created": call.cache_created,
        "cost_usd_equiv": call.cost_usd_equiv,
        "num_turns": call.num_turns,
        "prompt": prompt,
        "structured": None if call.structured is None
        else json.dumps(call.structured, ensure_ascii=False),
        "result_text": call.result_text,
        "camino": camino,
        "modelo": call.modelo,
    }


NO_MENCIONADO = "no mencionado por el analista: cuenta como skip"


def decision_rows(call: AnalystCall) -> list[dict[str, Any]]:
    """Una fila por CADA candidato y por cada decision sobre posiciones, de una
    salida VALIDA. Invalida: ninguna (la salida cruda va en `ai_calls.structured`).

    - El multiplicador es el que SE USA: un `open` sin `size_multiplier` va a 1,0
      en el parser, y el journal dice 1,0, no NULL (revision del 23/09/2026).
    - Los candidatos que el modelo no menciono tambien tienen fila (`skip`, sin
      confianza): sin ella, "que decidio la IA sobre X" no tendria respuesta.
    """
    if not call.parsed.ok:
        return []
    filas = [
        {
            "ref": d.ref,
            "type": d.type.value,
            "size_multiplier": (
                d.size_multiplier if d.size_multiplier is not None
                else 1.0 if d.type is DecisionType.OPEN else None
            ),
            "confidence": d.confidence,
            "reasons": json.dumps(d.reasons, ensure_ascii=False),
            "risks": json.dumps(d.risks, ensure_ascii=False),
            "executed": int(d.type.is_candidate_decision),
        }
        for d in call.parsed.decisions
    ]
    filas += [
        {"ref": ref, "type": DecisionType.SKIP.value, "size_multiplier": None,
         "confidence": None, "reasons": json.dumps([NO_MENCIONADO], ensure_ascii=False),
         "risks": "[]", "executed": 1}
        for ref in call.parsed.unmentioned
    ]
    return filas


def skipped_row(
    *, ts_ms: int, called_ms: int, outcome: str, reason: str, n_candidates: int,
    camino: str | None = None, kind: str = "decision",
) -> dict[str, Any]:
    """Una decision que el analista NO tomo porque no se le llamo. `kind`: "decision" o "sombra"."""
    if outcome not in (SKIPPED_BUDGET, SKIPPED_QUOTA, SKIPPED_STALE):
        raise ValueError(f"motivo de no llamar desconocido: {outcome}")
    if kind not in ("decision", SOMBRA):
        raise ValueError(f"tipo de fila desconocido: {kind}")
    return {
        "ts_ms": ts_ms, "called_ms": called_ms, "kind": kind, "outcome": outcome,
        "valid": 0, "reason": reason, "n_candidates": n_candidates, "camino": camino,
    }
