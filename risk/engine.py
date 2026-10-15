"""El motor de riesgo (PRD seccion 4, informe seccion 1.1).

Es codigo puro: entra una foto, sale un veredicto. Sin I/O, sin reloj propio,
sin estado global, y **sin importar nada de `ai/`** (hay un test que lo
comprueba leyendo el arbol sintactico).

Esa pureza es lo que permite el test de propiedades que pide el PRD: generar
miles de secuencias aleatorias de eventos y comprobar los invariantes en todas.

Tres decisiones de disenyo que conviene no deshacer:

1. **Se evaluan TODAS las reglas**, sin cortocircuito. Si una entrada viola
   cinco, queremos ver las cinco: el panel del PRD seccion 10 ensenya por que se
   bloqueo algo, y "por la primera que fallo" no es la respuesta completa.
2. **El tamanyo se calcula DESPUES de aprobar.** Si alguna regla veta, no hay
   tamanyo que calcular, y asi es imposible que un veredicto vetado lleve una
   cantidad no nula por accidente.
3. **Un unico punto de entrada con lock.** Dos aprobaciones simultaneas veriendo
   ambas "2 posiciones abiertas" pasarian las dos y acabarias con 4
   (informe seccion 4.3).
"""

from __future__ import annotations

import threading

from core.config import Settings
from risk.limits import Limits
from risk.rules import all_rules, check_mode
from risk.sizing import compute_size
from risk.state import RiskState
from risk.types import EntryRequest, RuleResult, Verdict

# Regla 4: las decisiones se aprueban de una en una.
_approval_lock = threading.Lock()


def evaluate(
    request: EntryRequest,
    state: RiskState,
    limits: Limits,
    settings: Settings,
) -> Verdict:
    """Decide si una entrada se aprueba, y con que tamanyo.

    Es la unica puerta por la que se abre una posicion en todo el bot.
    """
    with _approval_lock:
        return _evaluate_unlocked(request, state, limits, settings)


def _evaluate_unlocked(
    request: EntryRequest,
    state: RiskState,
    limits: Limits,
    settings: Settings,
) -> Verdict:
    results: list[RuleResult] = [check_mode(state)]

    for number, name, fn in all_rules():
        try:
            results.append(fn(request, state, limits, settings))
        except Exception as exc:
            # Una regla que revienta NO puede dejar pasar la operacion. Ante la
            # duda, se veta: es la direccion segura del error.
            results.append(
                RuleResult(
                    number, name, False,
                    f"la regla fallo al evaluarse ({type(exc).__name__}: {exc})",
                )
            )

    approved = all(r.passed for r in results)

    if not approved:
        return Verdict(
            approved=False,
            results=tuple(results),
            decision_id=request.decision_id,
        )

    sizing = compute_size(request, limits, exposure_usd=state.exposure_usd)
    if not sizing.ok:
        results.append(
            RuleResult(12, "riesgo por operacion", False, sizing.detail)
        )
        return Verdict(
            approved=False,
            results=tuple(results),
            decision_id=request.decision_id,
            sizing_detail=sizing.detail,
        )

    # Segunda barrera de la regla 15 (PRD seccion 13: cada regla dura se
    # comprueba en al menos dos sitios). La primera pasada solo pudo mirar si
    # cabia algo, porque el tamanyo aun no existia; esta mira el tamanyo REAL.
    # Si `compute_size` hace su trabajo, esto no salta nunca: justamente por
    # eso vale la pena, porque el dia que salte sera que alguien ha roto el
    # recorte por margen.
    projected = state.exposure_usd + sizing.notional_usd
    if projected > limits.max_exposure_usd + 1e-9:
        detail = (
            f"con el tamanyo real la exposicion quedaria en {projected:.2f} $, "
            f"por encima del tope de {limits.max_exposure_usd:.2f} $"
        )
        results.append(RuleResult(15, "exposicion y correlacion", False, detail))
        return Verdict(
            approved=False,
            results=tuple(results),
            decision_id=request.decision_id,
            sizing_detail=detail,
        )

    return Verdict(
        approved=True,
        results=tuple(results),
        qty=sizing.qty,
        notional_usd=sizing.notional_usd,
        risk_usd=sizing.risk_usd,
        decision_id=request.decision_id,
        sizing_detail=sizing.detail,
    )


def build_limits(
    settings: Settings, state: RiskState, slider_level: int = 3
) -> Limits:
    """Atajo: los limites vigentes para el equity de esta foto."""
    return Limits.for_state(settings, state.equity_usd, slider_level)


def evaluate_with_limits(
    request: EntryRequest,
    state: RiskState,
    settings: Settings,
    slider_level: int = 3,
) -> Verdict:
    """Construye los limites y evalua, en un paso."""
    return evaluate(
        request, state, build_limits(settings, state, slider_level), settings
    )
