"""El presupuesto de llamadas a Claude (regla dura 18).

Como mucho `max_calls_per_day` al dia (UTC) y `max_calls_per_5h_window` en
cualquier ventana MOVIL de 5 h, los dos de `config/settings.yaml` (40 y 8; la
configuracion no deja subirlos). Existe para que el bot no se coma la cuota de
Claude que el propietario usa para todo lo demas (informe seccion 1.5).

Tres decisiones que no hay que deshacer:

1. **Se guarda en la base, no en memoria.** Es la leccion de las reglas 10, 11 y
   14 (22/09/2026): lo que vive en memoria vuelve a cero en cada reinicio, y el
   servicio lleva `Restart=always`. Un bot que se reinicia en bucle no puede
   convertirse en un bot que llama a Claude sin tope.
2. **Cuenta INTENTOS, no exitos.** Una llamada que agota el timeout o devuelve
   basura tambien ha gastado cuota. Se apunta ANTES de llamar.
3. **Comprobar y apuntar van en UNA transaccion** (`try_acquire`). Si fueran dos
   pasos, dos procesos podrian mirar a la vez, ver el ultimo hueco libre y
   llamar los dos.

La regla 18 del motor de riesgo NO mira esto: mira el modo (`CLOSE_ONLY_QUOTA`),
que es como le llega el efecto sin importar nada de `ai/`.

Sin reloj propio: el instante se pasa.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from core.config import Settings

WINDOW_MS = 5 * 3600 * 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_budget_calls (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    kind  TEXT    NOT NULL      -- 'decision' | 'probe'
);
CREATE INDEX IF NOT EXISTS idx_ai_budget_ts ON ai_budget_calls (ts_ms);
"""


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    allowed: bool
    used_today: int
    used_window: int
    reason: str


def _inicio_del_dia(now_ms: int) -> int:
    d = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


class CallBudget:
    def __init__(self, conn: sqlite3.Connection, per_day: int, per_window: int) -> None:
        if per_window > per_day:
            raise ValueError("regla 18: el tope por ventana no puede superar al diario")
        self.conn = conn
        self.per_day = per_day
        self.per_window = per_window
        with conn:
            conn.executescript(SCHEMA)

    @classmethod
    def from_settings(cls, conn: sqlite3.Connection, settings: Settings) -> CallBudget:
        return cls(conn, settings.claude.max_calls_per_day, settings.claude.max_calls_per_5h_window)

    def _usado(self, now_ms: int) -> tuple[int, int]:
        hoy = self.conn.execute(
            "SELECT COUNT(*) FROM ai_budget_calls WHERE ts_ms >= ? AND ts_ms <= ?",
            (_inicio_del_dia(now_ms), now_ms),
        ).fetchone()[0]
        ventana = self.conn.execute(
            "SELECT COUNT(*) FROM ai_budget_calls WHERE ts_ms > ? AND ts_ms <= ?",
            (now_ms - WINDOW_MS, now_ms),
        ).fetchone()[0]
        return int(hoy), int(ventana)

    def check(self, now_ms: int) -> BudgetCheck:
        """Si se podria llamar ahora. No apunta nada."""
        hoy, ventana = self._usado(now_ms)
        if hoy >= self.per_day:
            return BudgetCheck(False, hoy, ventana,
                               f"regla 18: {hoy} llamadas hoy, tope {self.per_day}")
        if ventana >= self.per_window:
            return BudgetCheck(False, hoy, ventana,
                               f"regla 18: {ventana} llamadas en 5 h, tope {self.per_window}")
        return BudgetCheck(True, hoy, ventana,
                           f"{hoy}/{self.per_day} hoy, {ventana}/{self.per_window} en 5 h")

    def try_acquire(self, now_ms: int, kind: str = "decision") -> BudgetCheck:
        """Comprueba y, si cabe, APUNTA la llamada. Todo en una transaccion.

        Se llama justo ANTES de invocar a Claude. Si devuelve `allowed=False`, no
        se llama.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            veredicto = self.check(now_ms)
            if veredicto.allowed:
                self.conn.execute(
                    "INSERT INTO ai_budget_calls (ts_ms, kind) VALUES (?, ?)", (now_ms, kind)
                )
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return veredicto
