"""Baseline sin IA (informe seccion 1.9).

ES LA PIEZA QUE DECIDE SI EL PROYECTO TIENE SENTIDO. El objetivo declarado de
Ploutos no es ganar dinero: es **saber con datos si la IA aporta ventaja sobre
un baseline sin IA**. Sin esta pieza, "la IA analiza el mercado" es una
afirmacion que nadie puede comprobar.

Por eso el baseline tiene que ser **el mismo experimento con una sola variable
cambiada**: los mismos candidatos, el mismo motor de riesgo, la misma
ejecucion, el mismo periodo. Lo unico distinto es quien elige. Si ademas
cambiase el universo de monedas o los filtros, la comparacion no diria nada.

LA REGLA: coger el candidato con mejor R:R. Es la que propone el informe
seccion 1.9 y es deliberadamente tonta. Un baseline listo no serviria: si
pierde contra la IA no sabrias si es que la IA es buena o que el baseline era
malo; y si gana, habrias construido dos sistemas complicados en vez de uno.

**EL BASELINE NUNCA REDUCE EL TAMANYO.** `size_multiplier` es siempre 1,0. Esa
palanca existe solo para la IA (PRD seccion 6), asi que si el baseline la usara
dejaria de ser el mismo experimento.

Este modulo NO importa nada de `ai/` (hay un test con AST). Tampoco mira la
cartera: ordenar candidatos no necesita saber que hay abierto, y quien decide
si caben es `risk/engine.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from strategy.candidates import Candidate, Generation

# Nombre con el que queda registrado en el journal, para poder separar sus
# operaciones de las de la IA cuando se comparen en la fase 6.
DECIDER = "baseline"


@dataclass(frozen=True, slots=True)
class Choice:
    """Una eleccion. Misma forma que tendra la de la IA, a proposito.

    Que las dos devuelvan lo mismo es lo que permite enchufar una u otra sin
    tocar el resto del bucle, y lo que hace que la comparacion de la fase 6 sea
    entre decisiones y no entre implementaciones.
    """

    candidate: Candidate
    size_multiplier: float = 1.0
    confidence: float | None = None
    reason: str = ""
    decider: str = DECIDER

    @property
    def decision_id(self) -> str:
        return self.candidate.decision_id


def rank(generation: Generation, *, min_reward_risk: float = 0.0) -> list[Choice]:
    """Ordena los candidatos de mejor a peor R:R.

    Devuelve una LISTA y no un solo candidato porque quien la recorre
    (`portfolio/paper.py`) va probandolos contra el motor de riesgo hasta que
    se acaban los huecos: el mejor puede estar vetado por correlacion o por
    cooldown y el segundo no.

    El desempate es por `decision_id`, que es estable. Sin desempate, dos
    candidatos con el mismo R:R se ordenarian segun el orden de llegada y el
    baseline dejaria de ser reproducible, que es justo lo que no puede pasar en
    la mitad de control de un experimento.
    """
    elegibles = [
        c for c in generation.candidates if c.reward_risk >= min_reward_risk
    ]
    ordenados = sorted(elegibles, key=lambda c: (-c.reward_risk, c.decision_id))
    return [
        Choice(
            candidate=c,
            reason=(
                f"mejor R:R disponible ({c.reward_risk:.2f}) entre "
                f"{len(elegibles)} candidato(s)"
                if i == 0
                else f"R:R {c.reward_risk:.2f}, puesto {i + 1} de {len(elegibles)}"
            ),
        )
        for i, c in enumerate(ordenados)
    ]


def choose(generation: Generation, *, min_reward_risk: float = 0.0) -> Choice | None:
    """El mejor candidato, o nada si no hay ninguno que pase el umbral."""
    opciones = rank(generation, min_reward_risk=min_reward_risk)
    return opciones[0] if opciones else None
