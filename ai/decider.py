"""El analista como "el que decide" del bucle (pieza 9 del plan de la fase 3).

Encaja en `portfolio.loop.Decider`: recibe el contexto del momento de decidir y
devuelve `Choice`s. El bucle no importa `ai/`: esto se le PASA desde
`scripts/run_paper_ai.py`. Lo que devuelva lo sigue aprobando o vetando el
motor de riesgo, igual que al baseline.

El orden de cada vela, y por que:

1. Sin candidatos, no se llama (decision B del propietario).
2. Vela ATRASADA (el servicio estuvo parado y se esta poniendo al dia), no se
   llama: sus precios ya no existen y el presupuesto no se gasta en ellas
   (decision 3 del propietario del 23/09). Queda fila `skipped_stale`.
3. En CLOSE_ONLY_QUOTA no se llama (solo sondas): fila `skipped_quota`. En los
   otros modos de solo cierre (diario, capital) no se puede abrir nada: no se
   llama ni se apunta.
4. Presupuesto de la regla 18 (`CallBudget.try_acquire`, que apunta ANTES de
   llamar). Agotado: fila `skipped_budget` y CLOSE_ONLY_QUOTA (decision del propietario
   del 23/09).
5. Una llamada. Invalida, timeout o error = ninguna entrada en esta vela y SIN
   reintento (no se gasta otra llamada en la misma vela).
6. Los `open` validos, en el orden en que los dio el modelo. La confianza se
   registra pero NO ordena (`ai/parser.py`: "se registra, NO se usa").

`called_ms` del journal es EL MISMO instante que se pasa al presupuesto: el juez
vuelve a contar la regla 18 con `called_ms` (revision del 23/09).

El journal y el cambio de modo NO se escriben aqui: se dejan en `journal` y
`quota_change` para que quien guarda la vela los meta en la MISMA transaccion
(`store.save_step`). Un reinicio a medias no deja una llamada sin su vela.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ai.budget import CallBudget
from ai.invoke import call_analyst, probe_claude
from ai.journal import (
    SKIPPED_BUDGET, SKIPPED_QUOTA, SKIPPED_STALE, SOMBRA, call_row, camino, decision_rows, skipped_row,
)
from ai.prompt import LimitsView, PositionView, build_input, render
from ai.quota import QuotaChange, QuotaTracker
from core.config import Settings
from core.modes import Mode
from portfolio.loop import DecisionContext
from strategy.baseline import Choice

DECIDER = "ai"
log = logging.getLogger("ploutos.ai.decider")

# Lo que la sombra deja SIEMPRE libre para las decisiones de verdad (propuesta de la sombra, detalle 2): solo llama
# si, despues, quedarian al menos estas llamadas en la ventana de 5 h y en el dia. Una sombra no puede dejar sin
# llamada a una vela de verdad.
MARGEN_SOMBRA_VENTANA = 4
MARGEN_SOMBRA_DIA = 20


def _limites(ctx: DecisionContext) -> LimitsView:
    """Los limites VIGENTES (regla 9, slider) y cuanto queda de cada uno."""
    lim = ctx.limits
    ocupados = len(ctx.state.positions) + len(ctx.state.pending_entries)
    perdida = -sum(t.pnl_usd for t in ctx.state.closed_today)
    return LimitsView(
        max_positions=lim.max_positions,
        slots_free=max(0, lim.max_positions - ocupados),
        risk_per_trade_usd=lim.risk_per_trade_usd,
        daily_loss_left_usd=max(0.0, lim.daily_loss_limit_usd - perdida),
        trades_left_today=max(0, lim.max_trades_per_day - len(ctx.state.closed_today) - ocupados),
    )


def _posiciones(ctx: DecisionContext) -> list[PositionView]:
    return [
        PositionView(p.decision_id, p.symbol, p.entry_price,
                     ctx.marks.get(p.symbol, p.entry_price), p.stop_price, p.target_price,
                     p.opened_at)
        for p in ctx.state.positions
    ]


def entrada_de(ctx: DecisionContext) -> dict[str, Any]:
    """El JSON que ve el analista, sacado del contexto del momento de decidir."""
    return build_input(
        now=ctx.now, mode=ctx.mode.name, equity_usd=ctx.state.equity_usd,
        free_quote_usd=ctx.state.free_quote_usd, positions=_posiciones(ctx),
        limits=_limites(ctx), candidates=list(ctx.candidates),
    )


@dataclass
class AnalystDecider:
    settings: Settings
    budget: CallBudget
    tracker: QuotaTracker
    token: str
    config_dir: Path
    timeframe_ms: int
    clock: Callable[[], float] = time.time
    _call: Any = call_analyst          # los tests lo sustituyen: nada de red en un test
    _probe: Any = probe_claude
    # Lo de la ultima vela, para `store.save_step`: (fila de la llamada, filas de decisiones).
    journal: list[tuple[dict[str, Any], list[dict[str, Any]]]] = field(default_factory=list)
    quota_change: QuotaChange | None = None
    # La ultima vela decidida, para no volver a llamar si se reintenta (ver __call__).
    _memoria: tuple | None = field(default=None, repr=False)
    # Con que camino de decision se decide (protocolo de la fase 6): va en cada fila.
    _camino: str = field(default="", init=False, repr=False)
    # La ultima vela en sombra, para no volver a llamar si se reintenta (como `_memoria`).
    _memoria_sombra: tuple | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._camino = camino(self.settings)

    def _ahora_ms(self) -> int:
        return int(self.clock() * 1000)

    def _no_llamo(self, ctx: DecisionContext, outcome: str, motivo: str, ahora: int) -> None:
        self.journal.append((skipped_row(
            ts_ms=ctx.ts_ms, called_ms=ahora, outcome=outcome, reason=motivo,
            n_candidates=len(ctx.candidates), camino=self._camino,
        ), []))

    def __call__(self, ctx: DecisionContext) -> list[Choice]:
        """Nunca lanza: un fallo aqui es "no hacer nada en esta vela" y queda en el log."""
        self.journal, self.quota_change = [], None
        clave = (ctx.ts_ms, frozenset(c.decision_id for c in ctx.candidates))
        # REINTENTO de la misma vela (fallo al guardarla y recarga): no se vuelve a
        # llamar. Se devuelve lo mismo y se repone el journal, que se perdio con el
        # fallo. Sin esto, cada reintento era otra llamada a Claude y un registro
        # perdido (revision del 24/09/2026).
        if self._memoria is not None and self._memoria[0] == clave:
            _clave, journal, cambio, ids = self._memoria
            self.journal, self.quota_change = list(journal), cambio
            por_id = {c.decision_id: c for c in ctx.candidates}
            return [replace(e, candidate=por_id[e.decision_id]) for e in ids]
        try:
            elecciones = self._decidir(ctx)
        except Exception:
            log.exception("el analista fallo en la vela %s: no se abre nada", ctx.ts_ms)
            elecciones = []
        self._memoria = (clave, list(self.journal), self.quota_change, list(elecciones))
        return elecciones

    def _decidir(self, ctx: DecisionContext) -> list[Choice]:
        if not ctx.candidates:
            return []
        ahora = self._ahora_ms()

        # Cerrada hace mas de una vela: no es la vela "de ahora".
        if ahora - (ctx.ts_ms + self.timeframe_ms) > self.timeframe_ms:
            self._no_llamo(ctx, SKIPPED_STALE, "vela atrasada: sus precios ya no existen", ahora)
            return []
        if ctx.mode is Mode.CLOSE_ONLY_QUOTA:
            self._no_llamo(ctx, SKIPPED_QUOTA, "CLOSE_ONLY_QUOTA: solo sondas", ahora)
            return []
        if ctx.mode is not Mode.NORMAL:
            return []

        # La entrada ANTES del presupuesto: si prepararla fallara, no se habria
        # gastado una llamada sin hacerla (y el reintento de cada minuto se
        # comeria las 8 de la ventana en 8 minutos; revision del 24/09/2026).
        entrada = entrada_de(ctx)
        prompt = render(entrada)

        permiso = self.budget.try_acquire(ahora, kind="decision")
        if not permiso.allowed:
            self._no_llamo(ctx, SKIPPED_BUDGET, permiso.reason, ahora)
            self.quota_change = self.tracker.on_budget_denied(permiso.reason, ahora)
            return []

        llamada = self._call(
            entrada, token=self.token, config_dir=self.config_dir,
            model=self.settings.claude.model, timeout_s=self.settings.claude.timeout_seconds,
        )
        self.journal.append((
            call_row(llamada, ts_ms=ctx.ts_ms, called_ms=ahora, kind="decision",
                     prompt=prompt, n_candidates=len(ctx.candidates), camino=self._camino),
            decision_rows(llamada),
        ))
        self.quota_change = self.tracker.on_outcome(llamada.outcome, llamada.detail, ahora)
        if not llamada.parsed.ok:
            return []

        por_id = {c.decision_id: c for c in ctx.candidates}
        return [
            Choice(
                candidate=por_id[o.cid],
                size_multiplier=o.size_multiplier,
                confidence=o.confidence,
                reason=" / ".join(o.reasons) or "sin razones",
                decider=DECIDER,
            )
            for o in llamada.parsed.opens
            if o.cid in por_id
        ]

    # --- la sombra (decision 5 del protocolo de la fase 6, opcion B del propietario del 02/10) ---

    def sombra(self, ctx: DecisionContext) -> None:
        """Con la cartera llena: la IA decide sobre los candidatos que saldrian con hueco. No devuelve nada.

        La MISMA entrada que una llamada normal, con `slots_free: 1` y las posiciones de verdad: la IA no sabe
        que es sombra y decide igual que si hubiera un hueco, que es la pregunta (propuesta, detalle 1). Va en
        el journal con `kind = 'sombra'`, en la misma transaccion que la vela. Nunca lanza.
        """
        if not ctx.candidates:
            return
        clave = (ctx.ts_ms, frozenset(c.decision_id for c in ctx.candidates))
        if self._memoria_sombra is not None and self._memoria_sombra[0] == clave:
            self.journal.extend(self._memoria_sombra[1])   # reintento de la misma vela: no se vuelve a llamar
            return
        antes = len(self.journal)
        try:
            self._sombra(ctx)
        except Exception:
            log.exception("la sombra fallo en la vela %s: no pasa nada (no abre nada)", ctx.ts_ms)
        self._memoria_sombra = (clave, list(self.journal[antes:]))

    def _sombra(self, ctx: DecisionContext) -> None:
        ahora = self._ahora_ms()
        if ahora - (ctx.ts_ms + self.timeframe_ms) > self.timeframe_ms:
            return      # vela atrasada: sus precios ya no existen
        if ctx.mode is not Mode.NORMAL:
            return
        limites = _limites(ctx)
        if limites.trades_left_today <= 0:
            return      # hoy ya no se podria abrir nada aunque hubiera hueco
        entrada = build_input(
            now=ctx.now, mode=ctx.mode.name, equity_usd=ctx.state.equity_usd,
            free_quote_usd=ctx.state.free_quote_usd, positions=_posiciones(ctx),
            limits=replace(limites, slots_free=1), candidates=list(ctx.candidates),
        )
        prompt = render(entrada)

        def sin_presupuesto(motivo: str) -> None:
            # Sin llamada y SIN cambiar de modo: quedarse sin margen para la sombra no es quedarse sin cuota.
            self.journal.append((skipped_row(
                ts_ms=ctx.ts_ms, called_ms=ahora, outcome=SKIPPED_BUDGET, reason=f"sombra sin presupuesto: {motivo}",
                n_candidates=len(ctx.candidates), camino=self._camino, kind=SOMBRA,
            ), []))

        hay = self.budget.check(ahora)
        quedarian_ventana = self.budget.per_window - hay.used_window - 1
        quedarian_dia = self.budget.per_day - hay.used_today - 1
        if not hay.allowed or quedarian_ventana < MARGEN_SOMBRA_VENTANA or quedarian_dia < MARGEN_SOMBRA_DIA:
            sin_presupuesto(f"quedarian {quedarian_ventana} en 5 h y {quedarian_dia} hoy (margen "
                            f"{MARGEN_SOMBRA_VENTANA} y {MARGEN_SOMBRA_DIA})")
            return
        if not self.budget.try_acquire(ahora, kind=SOMBRA).allowed:
            sin_presupuesto(hay.reason)
            return
        llamada = self._call(
            entrada, token=self.token, config_dir=self.config_dir,
            model=self.settings.claude.model, timeout_s=self.settings.claude.timeout_seconds,
        )
        self.journal.append((
            call_row(llamada, ts_ms=ctx.ts_ms, called_ms=ahora, kind=SOMBRA,
                     prompt=prompt, n_candidates=len(ctx.candidates), camino=self._camino),
            decision_rows(llamada),
        ))
        # La cuota agotada o el login caducado son de verdad aunque los vea la sombra.
        cambio = self.tracker.on_outcome(llamada.outcome, llamada.detail, ahora)
        if self.quota_change is None:
            self.quota_change = cambio

    def sondear(self, ahora_ms: int | None = None) -> tuple[dict[str, Any] | None, QuotaChange | None]:
        """En CLOSE_ONLY_QUOTA, una sonda si toca. Devuelve (fila del journal, cambio).

        La sonda tambien pasa por el presupuesto (regla 18). Si no hay, no se
        llama y se reintenta en el siguiente intervalo.
        """
        ahora = ahora_ms if ahora_ms is not None else self._ahora_ms()
        if not self.tracker.should_probe(ahora):
            return None, None
        self.tracker.mark_probe(ahora)
        if not self.budget.try_acquire(ahora, kind="probe").allowed:
            return None, None
        clasif = self._probe(
            token=self.token, config_dir=self.config_dir, model=self.settings.claude.model,
        )
        fila = {
            "ts_ms": ahora, "called_ms": ahora, "kind": "probe", "outcome": clasif.outcome.value,
            "valid": 0, "reason": clasif.detail or clasif.outcome.value, "n_candidates": 0,
        }
        return fila, self.tracker.on_outcome(clasif.outcome, clasif.detail, ahora)
