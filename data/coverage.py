"""Cobertura de velas en una ventana: la medida del criterio de avance de la fase 1.

POR QUE EXISTE (hallazgo del 22/09/2026). `check_gaps.py` buscaba huecos solo
ENTRE dos velas presentes, contaba las esperadas desde la primera presente
hasta la ultima presente, y comprobaba la historia solo por el PRINCIPIO de la
ventana. O sea: si la ingesta moria a la hora 60 y se miraba a la 72, las 12 h
finales sin datos no contaban como hueco, porque no habia una vela despues que
lo cerrara. Decia "CRITERIO CUMPLIDO" justo en el fallo que las 72 h existen
para detectar.

Aqui las velas esperadas salen del RELOJ, no de las presentes: toda vela cuya
apertura cae en la ventana y que ya deberia haber cerrado. Lo que falte, este
donde este (principio, medio o final), es un hueco.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# Margen para la ultima vela. El secuenciador de la ingesta da una vela por
# cerrada cuando llega la SIGUIENTE (`data/ingest/sequencer.py`), asi que la
# ultima puede tardar unos segundos en aparecer tras su cierre. Dos minutos
# cubren eso y el desfase de reloj que `data/validate.py` ya tolera.
GRACE_MS = 2 * 60 * 1000


@dataclass(frozen=True, slots=True)
class Hole:
    """Velas consecutivas que faltan: de `first_ms` a `last_ms`, ambas incluidas."""

    first_ms: int
    last_ms: int
    count: int


@dataclass(frozen=True, slots=True)
class Coverage:
    first_expected_ms: int | None
    last_expected_ms: int | None
    expected: int
    present: int
    holes: tuple[Hole, ...] = field(default_factory=tuple)

    @property
    def missing(self) -> int:
        return sum(h.count for h in self.holes)

    @property
    def pct(self) -> float:
        return self.present / self.expected * 100.0 if self.expected else 0.0


def expected_slots(since_ms: int, now_ms: int, step_ms: int, grace_ms: int = GRACE_MS) -> range:
    """Aperturas de las velas que DEBERIAN estar cerradas y guardadas.

    La primera es la primera apertura >= `since_ms`; la ultima, la ultima cuya
    vela cerro hace al menos `grace_ms`.
    """
    first = -(-since_ms // step_ms) * step_ms
    last = (now_ms - step_ms - grace_ms) // step_ms * step_ms
    if last < first:
        return range(0)
    return range(first, last + step_ms, step_ms)


def coverage(
    stamps: Iterable[int], since_ms: int, now_ms: int, step_ms: int,
    grace_ms: int = GRACE_MS,
) -> Coverage:
    """Compara las velas cerradas guardadas (`stamps`) con las esperadas."""
    slots = expected_slots(since_ms, now_ms, step_ms, grace_ms)
    if not slots:
        return Coverage(None, None, 0, 0)
    presentes = {int(s) for s in stamps} & set(slots)

    holes: list[Hole] = []
    inicio: int | None = None
    for ts in slots:
        if ts in presentes:
            if inicio is not None:
                holes.append(Hole(inicio, ts - step_ms, (ts - inicio) // step_ms))
                inicio = None
        elif inicio is None:
            inicio = ts
    if inicio is not None:
        holes.append(Hole(inicio, slots[-1], (slots[-1] - inicio) // step_ms + 1))

    return Coverage(slots[0], slots[-1], len(slots), len(presentes), tuple(holes))
