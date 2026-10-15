"""El contrato de salida del analista (informe seccion 1.5).

Dos copias del mismo contrato, a proposito:

- `schema.json` es lo que recibe `claude -p --json-schema` (EN LINEA, no como
  ruta: verificado el 22/09/2026). Obliga al modelo a devolver esta forma.
- `AnalystOutput` (pydantic) es lo que valida el parser. Se vuelve a validar
  aunque el esquema ya lo haya forzado: el esquema es del CLI, que no controlamos,
  y la regla de la casa es que cada garantia se compruebe en dos sitios.

`tests/unit/test_ai_contract.py` comprueba que las dos copias dicen lo mismo.

Diferencias con el ejemplo del informe, y por que:
- No hay `rejected`: un `skip` con sus razones dice lo mismo, y dos sitios para
  decir "no" son dos sitios que pueden contradecirse.
- No hay `hypothesis_proposals`: el aprendizaje es de la fase 8.
- `size_multiplier` es opcional: si falta en un `open`, vale 1,0 (no reduce).
  Es el maximo que el motor ya permitiria, asi que no abre ninguna puerta.
- **UN solo campo de referencia, `ref`**, y no `cid` + `position_id` como en el
  informe. Medido el 22/09/2026 en la prueba en seco: con los dos opcionales,
  Claude rellenaba LOS DOS con el mismo valor en cada decision, y la respuesta
  entera se descartaba. `ref` es el `cid` en `open`/`skip` y el id de la
  posicion en `close`/`hold`/`tighten_stop`; el parser comprueba cual toca.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

# Lo que se le pasa al CLI: el esquema compacto, en una linea.
SCHEMA_JSON = json.dumps(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), separators=(",", ":"))

# PRD seccion 6: la IA solo puede REDUCIR el tamanyo.
MIN_SIZE_MULTIPLIER = 0.5
MAX_SIZE_MULTIPLIER = 1.0


# Cada razon o riesgo, como mucho 200 caracteres (igual que en schema.json).
Texto = Annotated[str, Field(max_length=200)]


class DecisionType(str, Enum):
    OPEN = "open"
    SKIP = "skip"
    CLOSE = "close"
    HOLD = "hold"
    TIGHTEN_STOP = "tighten_stop"

    @property
    def is_candidate_decision(self) -> bool:
        """Las que se refieren a un candidato (`cid`), no a una posicion."""
        return self in (DecisionType.OPEN, DecisionType.SKIP)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: DecisionType
    ref: str = Field(max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    size_multiplier: float | None = Field(
        default=None, ge=MIN_SIZE_MULTIPLIER, le=MAX_SIZE_MULTIPLIER
    )
    reasons: list[Texto] = Field(max_length=5)
    risks: list[Texto] = Field(default_factory=list, max_length=5)


class AnalystOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decisions: list[Decision] = Field(max_length=20)
    market_read: str = Field(max_length=300)
