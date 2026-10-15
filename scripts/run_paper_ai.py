"""La cartera de papel de la IA (pieza 9 del plan de la fase 3).

El MISMO bucle que el baseline (`scripts/run_paper.py`), con tres diferencias
y ninguna mas, para que la comparacion de la fase 6 sea entre decisiones y no
entre implementaciones:

1. Decide el analista (`ai.decider.AnalystDecider`) en vez de `rank`.
2. Base propia: `var/ploutos-paper-ai.db` (un escritor por base; el juez audita
   una cartera por base: `check_paper.py --decider ai --paper-db ...`).
3. En CLOSE_ONLY_QUOTA, entre velas, sondas a Claude para salir.

Servicio APARTE (`ploutos-paper-ai`, decision 1 del propietario del 23/09): si la IA
falla o se cuelga, el grupo de control sigue. Con su propio tope de memoria
(`MemoryMax`, decision 2).

Sin el token de Claude no arranca (salida 2, que systemd no reintenta): sin
token no hay IA que medir.

    .venv/bin/python scripts/run_paper_ai.py
    .venv/bin/python scripts/run_paper_ai.py --status
    .venv/bin/python scripts/run_paper_ai.py --reset-capital "motivo"
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai.budget import CallBudget  # noqa: E402
from ai.decider import DECIDER, AnalystDecider  # noqa: E402
from ai.quota import QuotaTracker  # noqa: E402
from core.clock import timeframe_ms  # noqa: E402
from core.modes import Mode  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from notify import messages as avisos_txt  # noqa: E402
from portfolio import store  # noqa: E402

log = logging.getLogger("ploutos.paper.ai")

PAPER_DB = REPO / "var" / "ploutos-paper-ai.db"
# El directorio de configuracion del CLI (su HOME): propio, bajo var/, que es lo
# unico que el servicio puede escribir.
CLAUDE_HOME = REPO / "var" / "claude_home_ai"
SIN_TOKEN = 2


def _cargar_run_paper():
    """`scripts/` no es un paquete: se carga el del baseline por su ruta."""
    spec = importlib.util.spec_from_file_location("run_paper", REPO / "scripts" / "run_paper.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["run_paper"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


rp = _cargar_run_paper()


class AIPaperRunner(rp.PaperRunner):
    DECIDER = DECIDER
    SERVICIO = "ploutos-paper-ai"
    LATIDO = "healthcheck_papel_ia"

    def __init__(self, args, *, token: str | None = None, _call=None, _probe=None, clock=time.time) -> None:
        if token is None:
            secreto = Secrets().claude_code_oauth_token
            token = secreto.get_secret_value().strip() if secreto else None
        if not token:
            log.error("falta CLAUDE_CODE_OAUTH_TOKEN en .env: sin token no hay IA que medir")
            raise SystemExit(SIN_TOKEN)
        self._token = token
        self._inyectado = {k: v for k, v in (("_call", _call), ("_probe", _probe)) if v is not None}
        self._clock = clock
        self.analista: AnalystDecider | None = None
        super().__init__(args)
        self.analista = AnalystDecider(
            settings=self.settings,
            budget=CallBudget.from_settings(self.paper, self.settings),
            # Tras un reinicio, el modo ya vive en la base; la causa no hace falta.
            tracker=QuotaTracker.from_active(
                Mode.CLOSE_ONLY_QUOTA in self.loop.modes.active, int(clock() * 1000)
            ),
            token=self._token,
            config_dir=CLAUDE_HOME,
            timeframe_ms=timeframe_ms(self.timeframe),
            clock=clock,
            **self._inyectado,
        )

    def _ahora_ms(self) -> int:
        return int(self._clock() * 1000)

    def _decider(self):
        # Se resuelve en cada vela: `reload()` construye el bucle antes de que
        # exista el analista (necesita la base abierta), y tras un fallo se
        # vuelve a llamar.
        return lambda ctx: self.analista(ctx) if self.analista else []

    def _sombra(self):
        # Opcion B del propietario (02/10): con la cartera llena, la IA decide sobre lo que saldria con hueco y no se
        # abre nada. Va DESPUES de la decision de verdad, en la misma vela (`portfolio/loop.py`, paso 6).
        return lambda ctx: self.analista.sombra(ctx) if self.analista else None

    def _extras(self, stamp: int, result) -> tuple[list, list, int]:
        if self.analista is None:
            return [], [], 0
        llamadas, self.analista.journal = self.analista.journal, []
        cambio, self.analista.quota_change = self.analista.quota_change, None
        cambios, canceladas = [], 0
        if cambio is not None:
            mc, canceladas = self.loop.set_quota_mode(cambio.active, cambio.reason)
            if mc is not None:
                cambios.append(mc)
            if canceladas:
                log.warning("MODO: %d entrada(s) pendiente(s) cancelada(s)", canceladas)
        return llamadas, cambios, canceladas

    def _between_candles(self) -> None:
        """En CLOSE_ONLY_QUOTA, una sonda cuando toca; si responde, se sale YA y se
        guarda YA (si no, un reinicio antes de la vela siguiente volveria a QUOTA)."""
        if self.analista is None or Mode.CLOSE_ONLY_QUOTA not in self.loop.modes.active:
            return
        ahora = int(self._clock() * 1000)
        fila, cambio = self.analista.sondear(ahora)
        if fila is not None:
            store.record_ai_call(self.paper, fila)
        if cambio is not None and not cambio.active:
            mc, _ = self.loop.set_quota_mode(False, cambio.reason)
            if mc is not None:
                store.record_mode_changes(
                    self.paper, ahora,
                    [(mc.mode.name, mc.activated, mc.reason, mc.effective_after.name)],
                )
                store.encolar_avisos(self.paper, ahora, [(
                    "modo", f"{self.DECIDER}:modo:{ahora}:{mc.mode.name}:0",
                    avisos_txt.cambio_de_modo(mc, self.DECIDER),
                )])
                log.warning("MODO: sale %s (%s)", mc.mode, mc.reason)

    def status(self) -> None:
        super().status()
        hoy = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        usadas = self.paper.execute(
            "SELECT COUNT(*) FROM ai_budget_calls WHERE ts_ms >= ?", (int(hoy.timestamp() * 1000),)
        ).fetchone()[0] if self.analista else 0
        print(f"  llamadas a Claude hoy  {usadas}/{self.settings.claude.max_calls_per_day}")


if __name__ == "__main__":
    raise SystemExit(rp.main(AIPaperRunner, str(PAPER_DB)))
