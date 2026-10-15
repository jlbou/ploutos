"""Una iteracion del bucle de decision, compartida por el historico y el vivo.

POR QUE ESTE MODULO EXISTE: el recorrido historico
(`scripts/replay_baseline.py`) y el bucle en vivo (`scripts/run_paper.py`)
tienen que decidir **exactamente igual**. Si cada uno tuviera su copia de los
pasos, acabarian separandose con el tiempo y las 72 h en vivo estarian midiendo
algo distinto de lo que se midio en el historico, sin que nadie se entere. La
comparacion de la fase 6 dejaria de significar nada.

Asi que la secuencia vive aqui una sola vez:

    1. avanzar el simulador con la vela de cada simbolo (llenados, stops, TP)
    2. recalcular correlaciones (regla 15)
    3. filtros -> candidatos
    4. el que decide (baseline hoy, IA en la fase 3) ordena
    5. el motor de riesgo aprueba o veta, uno a uno, hasta que no quedan huecos
    6. las aprobadas se mandan al simulador

Lo unico que cambia entre historico y vivo es de donde salen las velas y si
hay que esperar a la siguiente. Eso es de quien llama, no de aqui.

SIN I/O Y SIN RELOJ PROPIO: recibe el instante como parametro. Es lo que
permite que el historico avance 191 velas en segundos y el vivo espere 4 h,
ejecutando el mismo codigo.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pandas as pd

from core.config import Settings
from core.modes import Mode, ModeChange, ModeMachine
from features.context import CorrelationMatrix, compute as compute_correlations
from portfolio.paper import Bar, ExitReason, PaperBroker, PaperLedger, PaperTrade
from risk.engine import evaluate
from risk.limits import Limits
from risk.state import ClosedTrade, PendingEntry, Position, RiskState
from risk.types import Instrument
from strategy.baseline import Choice, rank
from strategy.candidates import Candidate
from strategy.filters import Screening
from strategy.pipeline import MarketData, PipelineResult, run as run_pipeline


# La IA solo puede REDUCIR el tamanyo (PRD seccion 6). Escrito aqui y no
# importado de `ai/` (portfolio no importa ai/): el bucle es la ultima puerta y no
# se fia de que el parser haya hecho su trabajo.
MIN_SIZE_MULTIPLIER = 0.5

# Los modos que ponen los comandos de Telegram, y el motivo que queda al quitarlos. La pausa se
# quita con /resume + /si; la parada, SOLO en el VPS (decision del propietario del 25/09/2026).
MANUALES: dict[Mode, str] = {
    Mode.CLOSE_ONLY_MANUAL: "/resume confirmado desde Telegram",
    Mode.HALTED: "levantada en el VPS (run_telegram.py --levantar-kill)",
}


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Lo que ve el que decide, en el MOMENTO de decidir: despues del paso 1
    (llenados, stops, caducidades y modos de esta vela). La prueba en seco del
    22/09 enseno que una foto tomada antes miente: el analista vio 0 huecos en
    una vela en la que acababa de cerrarse una posicion."""

    ts_ms: int
    now: datetime
    candidates: tuple[Candidate, ...]
    state: RiskState
    limits: Limits
    mode: Mode
    marks: dict[str, float]


# El que decide: recibe el contexto y devuelve los candidatos que quiere abrir,
# en el orden en que quiere probarlos. El baseline es `rank`; el de la IA lo
# construye `scripts/run_paper_ai.py` con `ai/` y se PASA aqui (el bucle no
# importa `ai/`). Lo que devuelva lo sigue aprobando o vetando el motor.
Decider = Callable[[DecisionContext], list[Choice]]

log = logging.getLogger("ploutos.loop")

# Los candidatos en SOMBRA (decision 5 del protocolo de la fase 6, opcion B del propietario del 02/10): con la cartera
# llena, "si hubiera hueco, que abririas?". Recibe el contexto con esos candidatos y NO devuelve nada: no se
# abre nunca nada (`docs/archivo/propuesta-candidatos-sombra.md`). Solo la cartera de la IA lo tiene.
Sombra = Callable[[DecisionContext], None]

# Con la cartera llena, la criba se repite con este tope de posiciones para ver que saldria con hueco.
TOPE_SOMBRA = 99
LLENA = "huecos ocupados"


def solo_por_llena(screening: Screening) -> bool:
    """La moneda cae UNICAMENTE porque no quedan huecos (no por otra regla a la vez, ni porque ya tenga
    posicion: eso es otra pregunta). Igual que `docs/estudios/candidatos-sombra/sombra.py`."""
    rechazos = screening.rejections
    return bool(rechazos) and all(r.name == "hueco libre" and LLENA in r.detail for r in rechazos)


@dataclass(frozen=True, slots=True)
class StepResult:
    """Todo lo que paso en una vela. Es lo que se registra en el journal."""

    ts_ms: int
    closed: tuple[PaperTrade, ...] = ()
    submitted: tuple[Choice, ...] = ()
    vetoed: tuple[tuple[Candidate, tuple[int, ...], str], ...] = ()
    pipeline: PipelineResult | None = None
    equity_usd: float = 0.0
    correlations: CorrelationMatrix | None = None
    # Transiciones de modo de esta vela, y entradas canceladas al entrar en
    # un modo de solo cierre (PRD seccion 5).
    mode_changes: tuple[ModeChange, ...] = ()
    cancelled: int = 0
    # Entradas canceladas por una flag de noticias en esta vela (pieza 4d): decision_id de cada una.
    canceladas_noticia: tuple[str, ...] = ()
    # Si el que decide fallo (la vela sigue, sin entradas): para el log.
    decide_error: str = ""
    # Los candidatos en sombra de esta vela (solo la cartera de la IA): para el log. No se abren.
    sombra: tuple[Candidate, ...] = ()

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return self.pipeline.candidates if self.pipeline else ()

    def summary(self) -> str:
        cuando = datetime.fromtimestamp(self.ts_ms / 1000, tz=UTC)
        partes = [f"{cuando:%Y-%m-%d %H:%M} equity {self.equity_usd:.2f} $"]
        if self.closed:
            partes.append(f"{len(self.closed)} cerrada(s)")
        if self.candidates:
            partes.append(f"{len(self.candidates)} candidato(s)")
        if self.submitted:
            partes.append(f"{len(self.submitted)} orden(es)")
        if self.vetoed:
            partes.append(f"{len(self.vetoed)} vetado(s)")
        for c in self.mode_changes:
            partes.append(f"{'ENTRA' if c.activated else 'SALE'} {c.mode}")
        if self.cancelled:
            partes.append(f"{self.cancelled} entrada(s) cancelada(s)")
        return ", ".join(partes)


@dataclass
class TradingLoop:
    """El bucle. Guarda solo lo que hace falta para decidir la vela siguiente."""

    instruments: dict[str, Instrument]
    cost: object              # CostModel; sin tipar para no importar de mas
    settings: Settings
    broker: PaperBroker
    ledger: PaperLedger
    timeframe: str = "4h"
    slider_level: int = 3
    # Los modos del PRD seccion 5. El efectivo es el mas restrictivo de los
    # activos. Quien carga el estado de la base (run_paper) reconstruye esto
    # con `store.load_modes`, porque CLOSE_ONLY_CAPITAL es enclavado y tiene
    # que sobrevivir a un reinicio.
    modes: ModeMachine = field(default_factory=ModeMachine)
    # None = el baseline (`rank`), exactamente como en la fase 2.
    decide: Decider | None = None
    # None = sin sombra (el baseline). La de la IA la pasa `scripts/run_paper_ai.py`.
    sombra: Sombra | None = None

    # Cuantas operaciones cerradas se miran para los cooldowns (regla 14).
    RECENT_MEMORY = 40
    # La desviacion de USDC de la vela en curso (regla 17). La pone `step`.
    _usdc: float | None = None
    # Flags de noticias de ESTA vela ({par: (etiquetas,)}), para `filter_event` (pieza 4c del
    # disenyo de noticias). Vacio = no nos hemos enterado de nada, no "no hay eventos".
    _event_flags: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # NO HAY LISTAS PROPIAS DE OPERACIONES CERRADAS, y es a proposito. Antes
    # el bucle llevaba en memoria `closed_today` y `recent`, y un reinicio las
    # dejaba vacias: la perdida del dia (regla 10), las operaciones del dia
    # (regla 11) y los cooldowns y la pausa (regla 14) volvian a cero aunque
    # las operaciones estuvieran guardadas en la base de papel. Ahora se sacan
    # en cada vela de `broker.trades`, que es lo que se guarda y se recarga:
    # una sola fuente de verdad, y nada que restaurar.

    def step(
        self,
        ts_ms: int,
        market: dict[str, MarketData],
        bars: dict[str, Bar],
        hourly: dict[str, pd.Series],
        *,
        usdc_deviation_pct: float | None,
        event_flags: dict[str, tuple[str, ...]] | None = None,
        salir_ya: frozenset[str] | None = None,
        manuales: Mapping[Mode, str] | None = None,
        cerrar_todo: bool = False,
    ) -> StepResult:
        """Procesa una vela. `bars` son las velas que acaban de cerrar.

        `usdc_deviation_pct` es OBLIGATORIO y sin valor por defecto (regla 17):
        quien llama tiene que decir de donde sale, o `None` si no lo sabe, y
        con `None` no se entra. Ver `features/usdc.py`.
        """
        now = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        self._usdc = usdc_deviation_pct
        # Noticias: con valor por defecto, al reves que la regla 17, porque NO es una regla dura:
        # sin fuente de noticias (el recorrido historico, o el servicio sin desplegar) el filtro
        # deja pasar, como decidio el propietario ("si la fuente cae, se avisa pero no se bloquea").
        self._event_flags = dict(event_flags or {})
        # Comandos de Telegram (docs/diseno-comandos-telegram.md): la pausa y la parada que habia
        # al CIERRE de esta vela. Lo primero, porque HALTED cambia lo que se hace en el paso 1b.
        cambios_manuales = self._sync_manuales(manuales)

        # 1. Avanzar el simulador. Primero esto: una posicion que salta en esta
        #    vela libera su hueco ANTES de decidir si se abre otra.
        closed: list[PaperTrade] = []
        marks: dict[str, float] = {}
        for symbol, bar in bars.items():
            marks[symbol] = bar.close
            closed.extend(self.broker.on_bar(symbol, bar))

        # 1b. Noticias (pieza 4d), DESPUES de la vela (que ya lleno, caduco o salto lo que tocaba)
        #     y ANTES de apuntar el equity, como un stop. Con CUALQUIER flag se cancelan las
        #     entradas pendientes de esa moneda ("no entrar" es tambien no dejar que se llene una
        #     orden ya puesta); con una CRITICA, ademas, se vende al cierre (PRD 5, decision 2 del propietario).
        #     Sin vela de esa moneda en esta pasada no hay precio: se vende en la siguiente.
        canceladas_noticia: list[str] = []
        for symbol in sorted(self._event_flags):
            for orden in self.broker.pending:
                if orden.symbol == symbol:
                    canceladas_noticia.append(orden.decision_id)
            self.broker.cancel_pending(symbol)
        # En HALTED el bot no toca las posiciones (PRD 5; decision 4 de la fase 4): ni por una
        # noticia. Sus stops y objetivos siguen, que en real son las OCO del exchange.
        vender = () if self.modes.effective is Mode.HALTED else sorted(salir_ya or ())
        for symbol in vender:
            if symbol in bars:
                trade = self.broker.close_at_market(symbol, bars[symbol])
                if trade is not None:
                    closed.append(trade)
        # "Cerrar todo" desde el panel (el propietario, 26/09): TODAS las posiciones a mercado, al cierre de esta
        # vela, aunque el bot este parado (es una orden expresa del propietario, no una decision del bot). Las
        # entradas pendientes las cancela la pausa que va con el (ver `notify.comandos`).
        if cerrar_todo:
            for symbol in sorted(self.broker.positions):
                if symbol in bars:
                    trade = self.broker.close_at_market(symbol, bars[symbol], ExitReason.MANUAL)
                    if trade is not None:
                        closed.append(trade)

        equity = self.ledger.record(ts_ms, marks)

        # Modos (PRD seccion 5), ANTES de decidir nada. Al pasar de NORMAL a
        # cualquier modo de solo cierre se cancelan las entradas pendientes.
        # Las posiciones abiertas siguen con su stop y su objetivo: en papel
        # los lleva siempre, que es lo que en real seria verificar la OCO.
        mode_changes = [*cambios_manuales, *self._update_modes(now)]
        # EL INVARIANTE, no la transicion: en cualquier modo de solo cierre no
        # queda ninguna entrada pendiente. Mirar solo el paso de NORMAL a solo
        # cierre no bastaba (revision del 23/09/2026): si un cambio de modo se
        # guardaba sin el estado (la salida por sonda va por su cuenta) y el
        # proceso se reiniciaba, volvia QUOTA con una pendiente viva, y nadie la
        # cancelaba porque la transicion ya habia pasado.
        cancelled = 0
        if self.modes.effective is not Mode.NORMAL and self.broker.pending:
            cancelled = self.broker.cancel_pending()

        # 2. Correlaciones de la regla 15, con la ventana que acaba aqui.
        correlations = compute_correlations(
            {s: serie for s, serie in hourly.items() if len(serie) > 0}
        )

        limits = Limits.for_state(self.settings, equity, self.slider_level)
        state = self._state(now, marks, correlations)

        # 3. Filtros y candidatos.
        pipeline = run_pipeline(
            market, state, limits, self.settings, self.cost, self.instruments,
            timeframe=self.timeframe, now=now, correlations=correlations,
        )

        submitted: list[Choice] = []
        vetoed: list[tuple[Candidate, tuple[int, ...], str]] = []

        # 4 y 5. El que decide ordena; el motor de riesgo aprueba o veta.
        #    El estado se reconstruye en CADA iteracion: si la anterior abrio
        #    una posicion, la siguiente tiene que verla. Reutilizar la foto
        #    seria como preguntar dos veces "queda hueco?" antes de ocuparlo.
        generation = pipeline.generation()
        estado_al_decidir = state
        decide_error = ""
        if self.decide is None:
            choices = rank(generation)
        else:
            # Un que decide que falla = no hacer nada en esta vela (PRD seccion 6).
            # Sin esto la vela quedaria atascada: el bucle la reintenta cada
            # minuto y fallaria siempre igual (revision del 24/09/2026).
            try:
                choices = self.decide(DecisionContext(
                    ts_ms=ts_ms, now=now, candidates=generation.candidates, state=state,
                    limits=limits, mode=self.modes.effective, marks=dict(marks),
                ))
            except Exception as exc:
                choices, decide_error = [], f"{type(exc).__name__}: {exc}"
        de_esta_vela = {c.decision_id: c for c in generation.candidates}
        for choice in choices:
            # El que decide elige ENTRE los candidatos; no los crea (PRD seccion 6).
            # Y se usa el candidato DE LA VELA, no el objeto que devolvio: uno con el
            # mismo id y otro stop no puede colarse (revision del 24/09/2026).
            candidate = de_esta_vela.get(choice.decision_id)
            if candidate is None:
                vetoed.append((choice.candidate, (), "no es un candidato de esta vela"))
                continue
            state = self._state(now, marks, correlations)
            verdict = evaluate(
                candidate.to_entry_request(self.instruments[candidate.symbol]),
                state, limits, self.settings,
            )
            if not verdict.approved:
                vetoed.append((candidate, verdict.veto_numbers, verdict.reason()))
                continue
            qty, motivo = self._aplicar_multiplicador(candidate, verdict.qty, choice.size_multiplier)
            if motivo:
                vetoed.append((candidate, (), motivo))
                continue
            if self.broker.submit(
                candidate.decision_id, candidate.symbol, qty,
                candidate.entry, candidate.stop, candidate.target,
                candidate.setup, ts_ms,
            ):
                submitted.append(choice)

        # 6. La sombra, DESPUES de la decision de verdad (la de verdad nunca espera por ella) y sin tocar
        #    nada: la segunda criba es pura y lo que decida no llega al simulador.
        sombra = self._sombra(market, estado_al_decidir, limits, now, correlations, pipeline, ts_ms, marks)

        return StepResult(
            ts_ms=ts_ms,
            closed=tuple(closed),
            submitted=tuple(submitted),
            vetoed=tuple(vetoed),
            pipeline=pipeline,
            equity_usd=equity,
            correlations=correlations,
            mode_changes=tuple(mode_changes),
            cancelled=cancelled,
            canceladas_noticia=tuple(canceladas_noticia),
            decide_error=decide_error,
            sombra=sombra,
        )

    def _sombra(
        self, market: dict[str, MarketData], state: RiskState, limits: Limits, now: datetime,
        correlations: CorrelationMatrix, pipeline: PipelineResult, ts_ms: int, marks: dict[str, float],
    ) -> tuple[Candidate, ...]:
        """Los candidatos que saldrian si hubiera hueco, y se los pasa a `self.sombra`. Nunca lanza."""
        if self.sombra is None or self.modes.effective is not Mode.NORMAL:
            return ()
        llenas = {s.symbol for s in pipeline.screenings if solo_por_llena(s)}
        if not llenas:
            return ()
        try:
            abierto = run_pipeline(
                market, state, replace(limits, max_positions=TOPE_SOMBRA), self.settings, self.cost,
                self.instruments, timeframe=self.timeframe, now=now, correlations=correlations,
            )
            candidatos = tuple(c for c in abierto.generation().candidates if c.symbol in llenas)
            if candidatos:
                self.sombra(DecisionContext(
                    ts_ms=ts_ms, now=now, candidates=candidatos, state=state, limits=limits,
                    mode=self.modes.effective, marks=dict(marks),
                ))
            return candidatos
        except Exception:  # noqa: BLE001 - la sombra nunca puede tumbar la vela de verdad
            log.exception("la sombra fallo en la vela %s: la vela de verdad sigue", ts_ms)
            return ()

    def _aplicar_multiplicador(
        self, candidate: Candidate, qty: float, multiplicador: float
    ) -> tuple[float, str | None]:
        """La cantidad que aprobo el motor, reducida por el que decide.

        DESPUES del motor, a proposito: el motor ya ha visto el tamanyo maximo,
        asi que reducirlo no puede saltarse ninguna regla (menos riesgo, menos
        nocional, menos exposicion). Hacia abajo al lote. Si reducida queda por
        debajo del minimo del par, no se abre: una orden que el exchange
        rechazaria no es una orden.
        """
        if multiplicador == 1.0:
            return qty, None
        if not (MIN_SIZE_MULTIPLIER <= multiplicador <= 1.0):
            return 0.0, (f"multiplicador {multiplicador} fuera de "
                         f"[{MIN_SIZE_MULTIPLIER}; 1]: el que decide solo puede reducir")
        ins = self.instruments[candidate.symbol]
        reducida = ins.round_amount_down(qty * multiplicador)
        if reducida <= 0 or reducida * candidate.entry < ins.min_notional_usd(candidate.entry):
            return 0.0, (f"con el multiplicador {multiplicador} la orden queda por debajo "
                         f"del minimo del par")
        return reducida, None

    def set_quota_mode(self, active: bool, reason: str) -> tuple[ModeChange | None, int]:
        """Entra o sale de CLOSE_ONLY_QUOTA (PRD seccion 5; regla 18 en el motor).

        Lo decide quien habla con Claude (`ai.quota.QuotaTracker`): el bucle no
        importa `ai/` (regla de arquitectura), solo recibe la orden. Al ENTRAR en
        solo cierre, como con cualquier otro modo, se cancelan las pendientes.
        Devuelve (el cambio o None si no cambio nada, entradas canceladas); el
        cambio hay que guardarlo (`store.save_step` o `store.record_mode_changes`).
        """
        if active:
            cambio = self.modes.activate(Mode.CLOSE_ONLY_QUOTA, reason)
        else:
            cambio = self.modes.deactivate(Mode.CLOSE_ONLY_QUOTA, reason)
        # El mismo invariante que en `step`: en solo cierre, ninguna pendiente.
        cancelled = 0
        if self.modes.effective is not Mode.NORMAL and self.broker.pending:
            cancelled = self.broker.cancel_pending()
        return cambio, cancelled

    def _sync_manuales(self, manuales: Mapping[Mode, str] | None) -> list[ModeChange]:
        """Pone y quita CLOSE_ONLY_MANUAL (/pause) y HALTED (/kill) segun los comandos.

        `manuales` sale de `notify.comandos.reconstruir(...).modos`, que ya ha aplicado lo que
        Telegram no puede hacer (levantar un /kill). None = no se sabe (sin base de control): no
        se toca nada, y una pausa o una parada ya guardadas siguen.
        """
        if manuales is None:
            return []
        cambios: list[ModeChange | None] = []
        for modo, al_quitar in MANUALES.items():
            if modo in manuales:
                cambios.append(self.modes.activate(modo, manuales[modo]))
            elif modo in self.modes.active:
                cambios.append(self.modes.manual_reset(modo, al_quitar))
        return [c for c in cambios if c is not None]

    def _update_modes(self, now: datetime) -> list[ModeChange]:
        """Activa y desactiva los modos que dependen de la cartera.

        - CLOSE_ONLY_CAPITAL (regla 7): dos lecturas de equity SEGUIDAS en o
          por debajo del suelo. Enclavado: aunque el equity rebote, no sale
          por aqui, solo con reset manual (`run_paper.py --reset-capital`).
          En papel hay una lectura por vela; en real seran cada 15 s.
        - CLOSE_ONLY_DAILY (regla 10): la perdida realizada de hoy llega al
          limite. Se levanta sola en cuanto cambia el dia UTC.

        QUOTA la pone quien habla con Claude, con `set_quota_mode`. DEGRADED
        (conexion con el exchange, fase 4) y HALTED (manual) no aplican todavia.
        """
        cambios: list[ModeChange | None] = []
        suelo = self.settings.capital.floor_usd
        ultimas = [e for _ts, e in self.ledger.history[-2:]]
        if len(ultimas) == 2 and all(e <= suelo for e in ultimas):
            cambios.append(self.modes.activate(
                Mode.CLOSE_ONLY_CAPITAL,
                f"regla 7: dos lecturas seguidas en o bajo el suelo "
                f"({ultimas[0]:.2f} y {ultimas[1]:.2f} $, suelo {suelo:.2f} $)",
            ))

        hoy, _recientes = self.closed_trades(now)
        perdida = -sum(t.pnl_usd for t in hoy)
        limite = self.settings.risk.daily_loss_limit_usd
        if perdida >= limite:
            cambios.append(self.modes.activate(
                Mode.CLOSE_ONLY_DAILY,
                f"regla 10: perdida de hoy {perdida:.2f} $ >= {limite:.2f} $",
            ))
        elif Mode.CLOSE_ONLY_DAILY in self.modes.active:
            cambios.append(self.modes.deactivate(
                Mode.CLOSE_ONLY_DAILY, f"nuevo dia UTC ({now:%Y-%m-%d})",
            ))
        return [c for c in cambios if c is not None]

    def closed_trades(self, now: datetime) -> tuple[tuple[ClosedTrade, ...], tuple[ClosedTrade, ...]]:
        """(cerradas hoy, cerradas recientes), sacadas de lo que esta guardado.

        "Hoy" es el dia UTC de `now`: las reglas 10 y 11 se resetean a las
        00:00 UTC. El instante de cierre es la apertura de la vela que cerro la
        operacion, que es tambien el instante con el que el bucle la proceso.
        """
        registros = [
            ClosedTrade(
                symbol=t.symbol,
                closed_at=datetime.fromtimestamp(t.closed_ts_ms / 1000, tz=UTC),
                pnl_usd=t.net_pnl_usd,
                hit_stop=t.hit_stop,
                decision_id=t.decision_id,
            )
            for t in self.broker.trades
        ]
        hoy = tuple(r for r in registros if r.closed_at.date() == now.date())
        recientes = tuple(registros[-self.RECENT_MEMORY:])
        return hoy, recientes

    def _state(
        self, now: datetime, marks: dict[str, float], correlations: CorrelationMatrix
    ) -> RiskState:
        """La foto que mira el motor de riesgo, sacada del simulador."""
        positions = tuple(
            Position(
                symbol=p.symbol,
                qty=p.qty,
                entry_price=p.entry_price,
                stop_price=p.stop_price,
                target_price=p.target_price,
                opened_at=datetime.fromtimestamp(p.opened_ts_ms / 1000, tz=UTC),
                decision_id=p.decision_id,
            )
            for p in self.broker.positions.values()
        )
        pending = tuple(
            PendingEntry(
                symbol=o.symbol,
                qty=o.qty,
                limit_price=o.limit_price,
                stop_price=o.stop_price,
                created_at=datetime.fromtimestamp(o.created_ts_ms / 1000, tz=UTC),
                decision_id=o.decision_id,
            )
            for o in self.broker.pending
        )
        equity = self.ledger.equity_usd(marks)
        closed_today, recent = self.closed_trades(now)
        usado = sum(p.qty * p.entry_price for p in positions)
        usado += sum(o.notional for o in self.broker.pending)
        return RiskState(
            now=now,
            equity_usd=equity,
            free_quote_usd=max(0.0, equity - usado),
            mode=self.modes.effective,
            positions=positions,
            pending_entries=pending,
            closed_today=closed_today,
            recent_closed=recent,
            marks=marks,
            correlations=dict(correlations.values),
            usdc_deviation_pct=self._usdc,
            event_flags=self._event_flags,
        )
