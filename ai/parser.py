"""El parser de la salida del analista: lo que decide si lo que dijo Claude vale.

Reglas del contrato (informe seccion 1.5) y decisiones del propietario del 22/09/2026:

1. **Salida invalida = no hacer nada.** JSON que no cumple el contrato, campos de
   mas, tipos fuera de rango: la respuesta ENTERA se descarta y se apunta como
   `llm_invalid_output`. Nunca una excepcion hacia arriba, nunca una orden.
2. **Un `ref` inventado (candidato o posicion) descarta la respuesta ENTERA**, no
   solo esa decision. Si se inventa una cosa, las demas tampoco son de fiar. El
   esquema de `--json-schema` NO impide esto (`cid` es solo un string: medido el
   22/09/2026), asi que esta regla solo vive aqui.
3. **Solo cuentan `open` y `skip`** (decision D del propietario). `close`, `hold` y
   `tighten_stop` se devuelven aparte, como "no ejecutadas", para registrarlas.
4. **La IA solo puede reducir el tamanyo**: `size_multiplier` en [0,5; 1,0]. Ya lo
   fuerza el esquema; aqui se vuelve a comprobar (dos barreras, PRD seccion 13).
5. **La confianza se registra, no se usa**: los LLM estan mal calibrados.
6. Un candidato que la IA no menciona cuenta como `skip`.

Sin I/O: recibe lo ya parseado del sobre de `--output-format json` (la clave
`structured_output`) y los identificadores validos de ESA llamada.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ai.contract import (
    MAX_SIZE_MULTIPLIER,
    MIN_SIZE_MULTIPLIER,
    AnalystOutput,
    Decision,
    DecisionType,
)

INVALID_KIND = "llm_invalid_output"


@dataclass(frozen=True, slots=True)
class Opening:
    """Un candidato que la IA quiere abrir. El motor de riesgo aun puede vetarlo."""

    cid: str
    size_multiplier: float
    confidence: float          # se registra, NO se usa (regla 5)
    reasons: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParseResult:
    ok: bool
    reason: str
    opens: tuple[Opening, ...] = ()
    skips: tuple[str, ...] = ()               # los que dijo que no y los no mencionados
    not_executed: tuple[Decision, ...] = ()   # close/hold/tighten_stop (decision D)
    market_read: str = ""
    kind: str = field(default="ok")
    # Todas las decisiones ya VALIDADAS, tal como las dio el modelo: el journal
    # las guarda sin volver a validar (una segunda validacion podria divergir).
    decisions: tuple[Decision, ...] = ()
    # Los candidatos que el modelo no menciono (cuentan como skip).
    unmentioned: tuple[str, ...] = ()

    @classmethod
    def invalid(cls, reason: str, candidate_ids: frozenset[str] = frozenset()) -> ParseResult:
        # Invalida = no hacer nada: todos los candidatos quedan sin abrir.
        return cls(False, reason, skips=tuple(sorted(candidate_ids)), kind=INVALID_KIND)


def parse(
    structured: Any,
    candidate_ids: set[str] | frozenset[str],
    position_ids: set[str] | frozenset[str] = frozenset(),
) -> ParseResult:
    """Valida la salida del analista contra el contrato y los ids de la llamada."""
    candidatos = frozenset(candidate_ids)
    posiciones = frozenset(position_ids)

    if not isinstance(structured, dict):
        return ParseResult.invalid("sin salida estructurada (structured_output)", candidatos)
    try:
        salida = AnalystOutput.model_validate(structured)
    except ValidationError as exc:
        primero = exc.errors()[0]
        donde = ".".join(str(p) for p in primero.get("loc", ()))
        return ParseResult.invalid(
            f"no cumple el contrato: {donde}: {primero.get('msg')}", candidatos
        )

    # Regla 2: nada inventado, ni en una sola decision. `ref` es un candidato en
    # open/skip y una posicion en close/hold/tighten_stop (ver ai/contract.py).
    for d in salida.decisions:
        if d.type.is_candidate_decision:
            if d.ref not in candidatos:
                return ParseResult.invalid(f"cid inventado: {d.ref!r}", candidatos)
        elif d.ref not in posiciones:
            return ParseResult.invalid(f"posicion inventada: {d.ref!r}", candidatos)

    # Una referencia, una decision: "abre" y "no abras", o "hold" y "close" sobre la
    # misma posicion, es contradictorio. (Y el journal usa (llamada, ref) de clave.)
    repetidos = [c for c, n in Counter(d.ref for d in salida.decisions).items() if n > 1]
    if repetidos:
        return ParseResult.invalid(f"decision repetida para {sorted(repetidos)}", candidatos)

    opens: list[Opening] = []
    mencionados: set[str] = set()
    for d in salida.decisions:
        if d.type is DecisionType.OPEN:
            mult = 1.0 if d.size_multiplier is None else d.size_multiplier
            # Regla 4, segunda barrera. El modelo ya lo ha validado, pero si
            # alguien lo relaja algun dia, esto sigue en pie.
            if not (MIN_SIZE_MULTIPLIER <= mult <= MAX_SIZE_MULTIPLIER):
                return ParseResult.invalid(f"size_multiplier fuera de rango: {mult}", candidatos)
            opens.append(Opening(d.ref, mult, d.confidence, tuple(d.reasons), tuple(d.risks)))
        if d.type.is_candidate_decision:
            mencionados.add(d.ref)

    abiertos = {o.cid for o in opens}
    skips = tuple(sorted(candidatos - abiertos))
    no_ejecutadas = tuple(d for d in salida.decisions if not d.type.is_candidate_decision)
    detalle = f"{len(opens)} open, {len(skips)} skip"
    if candidatos - mencionados:
        detalle += f" ({len(candidatos - mencionados)} sin mencionar)"
    if no_ejecutadas:
        detalle += f", {len(no_ejecutadas)} sobre posiciones (no se ejecutan)"
    return ParseResult(
        True, detalle, tuple(opens), skips, no_ejecutadas, salida.market_read,
        decisions=tuple(salida.decisions),
        unmentioned=tuple(sorted(candidatos - mencionados)),
    )
