"""Como acabo una llamada a `claude -p`, y si hay que entrar en CLOSE_ONLY_QUOTA.

PRD seccion 5: `CLOSE_ONLY_QUOTA` entra con "cuota de Claude agotada, login
caducado o error de autenticacion de Claude", y sale sola cuando una sonda
responde bien. Informe seccion 3.1: detectarlo por patrones del texto de error, y
tratar **cualquier fallo desconocido como "sin IA"** para esa llamada.

Patrones:
- CUOTA (informe 3.1): `You've hit your session limit`, `weekly limit`, `Sonnet
  limit`; `rate_limit` en los eventos de reintento.
- AUTENTICACION: `Not logged in · Please run /login` es EXACTAMENTE lo que devolvio
  el CLI en el control sin token del 22/09/2026; `Login expired` sale del informe.

Los patrones solo se miran si la llamada FALLO. Una respuesta buena cuyo
`market_read` diga "rate limit" no es un error de cuota.

Sin I/O: recibe el codigo de salida y lo que escribio el CLI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CallOutcome(Enum):
    OK = "ok"
    QUOTA = "quota"          # cuota agotada -> CLOSE_ONLY_QUOTA
    AUTH = "auth"            # sin login o token caducado -> CLOSE_ONLY_QUOTA
    TIMEOUT = "timeout"      # sin IA en esta llamada
    ERROR = "error"          # cualquier otra cosa: sin IA en esta llamada

    @property
    def enters_quota_mode(self) -> bool:
        return self in (CallOutcome.QUOTA, CallOutcome.AUTH)


_CUOTA = re.compile(
    r"hit your (session|weekly|opus|sonnet|usage)? ?limit|usage limit|rate[_ ]limit|limit reached",
    re.IGNORECASE,
)
_AUTH = re.compile(
    r"not logged in|please run /login|login expired|invalid api key|oauth token"
    r"|authentication[_ ]error|token (has )?expired|unauthorized|\b401\b",
    re.IGNORECASE,
)

MAX_DETAIL = 200


@dataclass(frozen=True, slots=True)
class Classification:
    outcome: CallOutcome
    detail: str
    envelope: dict[str, Any] | None = None   # el sobre de --output-format json, si lo hubo


def _tapar(texto: str, secreto: str | None) -> str:
    texto = texto or ""
    if secreto:
        texto = texto.replace(secreto, "***")
    return " ".join(texto.split())[:MAX_DETAIL]


def classify(
    returncode: int | None,
    stdout: str,
    stderr: str = "",
    *,
    timed_out: bool = False,
    secret: str | None = None,
) -> Classification:
    """Clasifica una llamada. Nunca lanza."""
    if timed_out:
        return Classification(CallOutcome.TIMEOUT, "la llamada supero el timeout")

    envelope: dict[str, Any] | None = None
    try:
        parsed = json.loads(stdout) if stdout and stdout.strip() else None
        envelope = parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        envelope = None

    fallo_en_sobre = envelope is not None and bool(envelope.get("is_error"))
    if returncode == 0 and envelope is not None and not fallo_en_sobre:
        return Classification(CallOutcome.OK, "ok", envelope)

    # Fallo: se busca el motivo en todo lo que dijo el CLI.
    texto = " ".join(
        str(x) for x in (
            (envelope or {}).get("result", ""),
            (envelope or {}).get("subtype", ""),
            "" if envelope is not None else stdout,
            stderr,
        ) if x
    )
    detalle = _tapar(texto, secret) or f"codigo de salida {returncode} sin mensaje"
    if _AUTH.search(texto):
        return Classification(CallOutcome.AUTH, detalle, envelope)
    if _CUOTA.search(texto):
        return Classification(CallOutcome.QUOTA, detalle, envelope)
    if returncode == 0 and envelope is None:
        return Classification(CallOutcome.ERROR, "la salida no es el JSON esperado", None)
    return Classification(CallOutcome.ERROR, detalle, envelope)


# --------------------------------------------------------------------------
# CLOSE_ONLY_QUOTA: cuando se entra y cuando se sale (pieza 7 de la fase 3)
# --------------------------------------------------------------------------

# Informe seccion 3.1: una sonda barata cada 30-60 min mientras dure el modo.
PROBE_INTERVAL_MS = 45 * 60 * 1000

CAUSA_CUOTA = "cuota"
CAUSA_AUTH = "autenticacion"
CAUSA_PRESUPUESTO = "presupuesto"


@dataclass(frozen=True, slots=True)
class QuotaChange:
    """Hay que activar (`active=True`) o desactivar CLOSE_ONLY_QUOTA."""

    active: bool
    reason: str


@dataclass
class QuotaTracker:
    """Cuando el analista no esta disponible, y cuando vuelve a estarlo.

    ENTRA (PRD seccion 5): cuota de Claude agotada, login caducado o error de
    autenticacion; y tambien con el presupuesto propio de la regla 18 agotado.
    Esto ultimo NO esta en la lista del PRD: lo decidio el propietario el 23/09/2026 (sin
    presupuesto la IA no puede decidir, y se trata igual que si no hubiera IA).

    SALE con UNA regla para las tres causas: una llamada que responde bien. En
    CLOSE_ONLY_QUOTA no se abre nada, asi que no hay llamadas de decision: la que
    responde bien es una SONDA, que se lanza cada `PROBE_INTERVAL_MS`. Si la causa
    era el presupuesto, la sonda tampoco sale hasta que el presupuesto la deje
    (tambien cuenta como llamada), y cuando sale y responde, se sale del modo.

    Un timeout o un error desconocido NO cambian nada: "sin IA" en esa llamada.

    Sin reloj y sin I/O. Tras un reinicio se reconstruye con `from_active()`: el
    modo en si ya vive en la base (`paper_mode_changes`).
    """

    active: bool = False
    cause: str | None = None
    since_ms: int | None = None
    last_probe_ms: int | None = None

    @classmethod
    def from_active(cls, active: bool, now_ms: int) -> QuotaTracker:
        """Tras un reinicio. La causa no se guarda: da igual, se sale igual."""
        return cls(active=active, cause="desconocida" if active else None,
                   since_ms=now_ms if active else None)

    def _entrar(self, causa: str, detalle: str, now_ms: int) -> QuotaChange | None:
        if self.active:
            return None
        self.active, self.cause, self.since_ms, self.last_probe_ms = True, causa, now_ms, None
        return QuotaChange(True, f"{causa}: {detalle}")

    def on_outcome(self, outcome: CallOutcome, detail: str, now_ms: int) -> QuotaChange | None:
        """Tras CUALQUIER llamada (de decision o sonda)."""
        if outcome is CallOutcome.QUOTA:
            return self._entrar(CAUSA_CUOTA, detail, now_ms)
        if outcome is CallOutcome.AUTH:
            return self._entrar(CAUSA_AUTH, detail, now_ms)
        if outcome is CallOutcome.OK and self.active:
            self.active, self.cause, self.since_ms = False, None, None
            return QuotaChange(False, "Claude vuelve a responder")
        return None

    def on_budget_denied(self, reason: str, now_ms: int) -> QuotaChange | None:
        return self._entrar(CAUSA_PRESUPUESTO, reason, now_ms)

    def should_probe(self, now_ms: int) -> bool:
        if not self.active:
            return False
        desde = self.last_probe_ms if self.last_probe_ms is not None else self.since_ms
        return desde is None or now_ms - desde >= PROBE_INTERVAL_MS

    def mark_probe(self, now_ms: int) -> None:
        """Se INTENTO una sonda (haya salido o no por el presupuesto)."""
        self.last_probe_ms = now_ms
