"""Maquina de modos (PRD seccion 5, informe seccion 1.4).

Tres propiedades que no son negociables:

1. El modo efectivo es el MAS RESTRICTIVO de los activos. Pueden coexistir
   varios (p. ej. QUOTA y CAPITAL a la vez).
2. `CLOSE_ONLY_CAPITAL` es ENCLAVADO: aunque el equity rebote a 26 $, no vuelve
   a abrir. Solo sale con reset manual. Si no fuera asi, el bot oscilaria
   alrededor del suelo y el suelo dejaria de servir.
3. Solo `NORMAL` puede abrir posiciones. Cualquier otro modo, no.

La fase 1 solo usa NORMAL y CLOSE_ONLY_DEGRADED, pero el conjunto completo vive
aqui desde el principio porque es barato y se testea entero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.clock import utcnow


class Mode(Enum):
    """Modos ordenados por restriccion creciente (`rank`)."""

    NORMAL = ("NORMAL", 0)
    CLOSE_ONLY_QUOTA = ("CLOSE_ONLY_QUOTA", 10)
    CLOSE_ONLY_DEGRADED = ("CLOSE_ONLY_DEGRADED", 11)
    CLOSE_ONLY_DAILY = ("CLOSE_ONLY_DAILY", 12)
    # La pausa del propietario desde Telegram (`/pause`). No esta en la tabla del PRD 5, pero
    # si en sus controles ("pausar", "solo cierre"): decision del propietario del 25/09/2026
    # (docs/diseno-comandos-telegram.md). Se levanta con `/resume`, no sola.
    CLOSE_ONLY_MANUAL = ("CLOSE_ONLY_MANUAL", 15)
    CLOSE_ONLY_CAPITAL = ("CLOSE_ONLY_CAPITAL", 20)
    HALTED = ("HALTED", 30)

    def __init__(self, label: str, rank: int) -> None:
        self.label = label
        self.rank = rank

    def __str__(self) -> str:
        return self.label

    @property
    def can_open(self) -> bool:
        """Regla dura: solo NORMAL abre posiciones."""
        return self is Mode.NORMAL

    @property
    def can_close(self) -> bool:
        """HALTED es configurable; por defecto, conservador: no toca nada."""
        return self is not Mode.HALTED

    @property
    def is_latched(self) -> bool:
        """Regla 7: CLOSE_ONLY_CAPITAL solo sale con reset manual."""
        return self is Mode.CLOSE_ONLY_CAPITAL


# Modos que un reset manual puede levantar.
MANUAL_RESET_ONLY: frozenset[Mode] = frozenset({Mode.CLOSE_ONLY_CAPITAL, Mode.HALTED})


@dataclass(frozen=True, slots=True)
class ModeChange:
    """Una transicion, para el journal y Telegram (PRD seccion 9)."""

    ts: datetime
    mode: Mode
    activated: bool
    reason: str
    effective_before: Mode
    effective_after: Mode


class ModeMachine:
    """Conjunto de modos activos y su resolucion al modo efectivo.

    No hace I/O ni conoce el reloj mas alla de `utcnow()`: es facil de testear
    con secuencias aleatorias de eventos.
    """

    def __init__(self) -> None:
        self._active: dict[Mode, str] = {}
        self._history: list[ModeChange] = []

    @property
    def effective(self) -> Mode:
        """El mas restrictivo de los activos. Sin ninguno activo, NORMAL."""
        if not self._active:
            return Mode.NORMAL
        return max(self._active, key=lambda m: m.rank)

    @property
    def active(self) -> frozenset[Mode]:
        return frozenset(self._active)

    @property
    def history(self) -> tuple[ModeChange, ...]:
        return tuple(self._history)

    @property
    def can_open(self) -> bool:
        return self.effective.can_open

    @property
    def can_close(self) -> bool:
        return self.effective.can_close

    def reason_for(self, mode: Mode) -> str | None:
        return self._active.get(mode)

    def activate(self, mode: Mode, reason: str) -> ModeChange | None:
        """Activa un modo. Devuelve el cambio, o None si ya estaba activo."""
        if mode is Mode.NORMAL:
            raise ValueError("NORMAL no se activa: es la ausencia de restricciones")
        if mode in self._active:
            return None
        before = self.effective
        self._active[mode] = reason
        change = ModeChange(
            ts=utcnow(),
            mode=mode,
            activated=True,
            reason=reason,
            effective_before=before,
            effective_after=self.effective,
        )
        self._history.append(change)
        return change

    def deactivate(self, mode: Mode, reason: str) -> ModeChange | None:
        """Desactiva un modo automatico.

        Los modos enclavados (regla 7) NO se levantan por aqui: hay que usar
        `manual_reset`, que es lo que hace el propietario a mano.
        """
        if mode in MANUAL_RESET_ONLY:
            raise ModeLatchedError(
                f"{mode} es enclavado (regla 7): solo sale con reset manual"
            )
        return self._deactivate_unchecked(mode, reason)

    def manual_reset(self, mode: Mode, reason: str) -> ModeChange | None:
        """Reset manual. Es la unica salida de CLOSE_ONLY_CAPITAL y HALTED."""
        return self._deactivate_unchecked(mode, reason)

    def _deactivate_unchecked(self, mode: Mode, reason: str) -> ModeChange | None:
        if mode not in self._active:
            return None
        before = self.effective
        del self._active[mode]
        change = ModeChange(
            ts=utcnow(),
            mode=mode,
            activated=False,
            reason=reason,
            effective_before=before,
            effective_after=self.effective,
        )
        self._history.append(change)
        return change


class ModeLatchedError(Exception):
    """Se intento levantar automaticamente un modo enclavado."""
