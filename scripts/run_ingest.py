"""Entrypoint de la fase 1: ingesta continua de datos de mercado.

No opera. No tiene claves. No envia ordenes. Solo escucha el mercado, lo
guarda y avisa cuando los datos dejan de ser fiables.

Uso:
    python scripts/run_ingest.py
    python scripts/run_ingest.py --config config/settings.yaml --duration 3600

Para el criterio de avance (72 h sin huecos), dejarlo corriendo y comprobar
despues con `python scripts/check_gaps.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.clock import utcnow_ms  # noqa: E402
from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.events import Event, EventBus, EventKind  # noqa: E402
from core.logging import get_logger, setup_logging  # noqa: E402
from core.modes import Mode, ModeMachine  # noqa: E402
from core.salud import ENTRAR, SALIR, Salud, Senyales, evaluar  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from data.exchange import Exchange, WhitelistMismatchError  # noqa: E402
from data.ingest.rest import RestIngestor  # noqa: E402
from data.ingest.staleness import StalenessMonitor  # noqa: E402
from data.ingest.ws import WsIngestor  # noqa: E402
from data.store.db import open_database  # noqa: E402
from notify.latido import Latido  # noqa: E402
from data.store.repos import (  # noqa: E402
    BookMetricsRepo,
    CandleRepo,
    EventRepo,
    GapRepo,
    HealthRepo,
    InstrumentRepo,
    L1Repo,
    ModeRepo,
)

log = get_logger("ploutos.ingest")

STALENESS_CHECK_SECONDS = 10
GAP_SCAN_SECONDS = 900          # cada 15 min
SEAM_SCAN_SECONDS = 90          # primera pasada, para cerrar la costura backfill/WS
HEALTH_PERSIST_SECONDS = 30
CLOCK_CHECK_SECONDS = 300
# El latido del vigilante externo se mira cada minuto; `Latido` manda como mucho uno
# cada 2 min (limite de Healthchecks.io: 5 por minuto).
LATIDO_SECONDS = 60
# La ultima vela de 1 m GUARDADA de cada moneda no puede tener mas de esto (desde
# su cierre) para latir. Revision del 24/09/2026: el detector de datos viejos se
# actualiza al RECIBIR, antes de guardar; con el disco lleno la ingesta seguiria
# "fresca" sin guardar nada, y latiendo.
VELA_1M_MAX_EDAD_MS = 3 * 60 * 1000


class IngestService:
    def __init__(self, settings: Settings, db_path: str | None = None) -> None:
        self.settings = settings
        self.db = open_database(db_path or settings.storage.db_path)
        self.bus = EventBus()
        self.modes = ModeMachine()
        # DEGRADED con la misma pieza que el ejecutor (fase 4, pieza d): sale tras 10 min SEGUIDOS sano.
        self.salud = Salud()

        self.candles = CandleRepo(self.db)
        self.l1 = L1Repo(self.db)
        self.books = BookMetricsRepo(self.db)
        self.health = HealthRepo(self.db)
        self.gaps = GapRepo(self.db)
        self.instruments = InstrumentRepo(self.db)
        self.events = EventRepo(self.db)
        self.mode_repo = ModeRepo(self.db)

        self.exchange = Exchange(settings, public_only=True)
        self.staleness = StalenessMonitor(settings=settings, bus=self.bus)
        self.ws: WsIngestor | None = None
        self.rest: RestIngestor | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        # Vigilante externo (decision del propietario del 24/09/2026). Opcional: sin URL no late.
        self.latido = Latido(Secrets().valor("healthcheck_ingesta"), "ploutos-ingest")

    # --- arranque ---

    async def start(self) -> None:
        # El grabador va PRIMERO: si arrancase despues del backfill, el evento
        # de arranque y los huecos detectados en el escaneo inicial se
        # publicarian sin nadie escuchando y no quedarian en el journal.
        # PRD seccion 13: todo tiene que ser trazable, tambien el arranque.
        self._tasks.append(
            asyncio.create_task(self._event_recorder(), name="event-recorder")
        )
        await asyncio.sleep(0)  # deja que el grabador se suscriba

        self.bus.emit(EventKind.STARTUP, whitelist=list(self.settings.whitelist))

        await self.exchange.open()
        # Regla 3, punto de validacion 1 de 4: contra el exchange real.
        self.exchange.check_whitelist()
        await self.instruments.upsert_many(self.exchange.instrument_rows())

        await self._check_clock()

        self.rest = RestIngestor(
            self.settings, self.exchange, self.candles, self.gaps, self.bus
        )
        self.ws = WsIngestor(
            self.settings,
            self.exchange,
            self.candles,
            self.l1,
            self.books,
            self.staleness,
            self.bus,
        )

        log.info("backfill inicial (puede tardar un par de minutos)...")
        await self.rest.backfill_all()

        log.info("busqueda de huecos al arrancar...")
        summary = await self.rest.scan_and_fill()
        log.info(
            "huecos: %d detectados, %d rellenados (%d velas)",
            summary["detected"],
            summary["filled"],
            summary["candles"],
        )

        self.ws.start()
        self._tasks += [
            asyncio.create_task(self._staleness_loop(), name="staleness"),
            asyncio.create_task(self._gap_loop(), name="gap-scan"),
            asyncio.create_task(self._health_loop(), name="health-persist"),
            asyncio.create_task(self._clock_loop(), name="clock-check"),
            asyncio.create_task(self._latido_loop(), name="latido"),
        ]
        log.info("ingesta en marcha. Ctrl+C para parar.")

    async def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        log.info("parando...")
        self.bus.emit(EventKind.SHUTDOWN)
        if self.ws:
            await self.ws.stop()
        # Un respiro para que el grabador vacie la cola antes de cancelarlo:
        # si no, el evento de parada se pierde justo al pararse.
        await asyncio.sleep(0.2)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._persist_health()
        await self.exchange.close()
        self.db.close()
        log.info("parado limpiamente.")

    # --- tareas periodicas ---

    async def _event_recorder(self) -> None:
        """Todo evento va a la tabla `events` (PRD seccion 13: trazabilidad)."""
        queue = self.bus.subscribe()
        try:
            while True:
                event: Event = await queue.get()
                with contextlib.suppress(Exception):
                    await self.events.record(event)
        except asyncio.CancelledError:
            raise
        finally:
            self.bus.unsubscribe(queue)

    async def _staleness_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(STALENESS_CHECK_SECONDS)
            newly = self.staleness.check(utcnow_ms())
            for state in newly:
                log.warning("fuente STALE: %s %s", state.source, state.symbol)
                await self.health.mark_stale(
                    state.source, state.symbol, "sin actualizar", utcnow_ms()
                )
            await self._update_degraded_mode()

    async def _update_degraded_mode(self) -> None:
        """PRD seccion 5: datos obsoletos -> CLOSE_ONLY_DEGRADED; se SALE tras 10 min seguidos sin datos obsoletos
        (`core/salud.py`, decision 6 del propietario del 26/09). Hasta la fase 4 salia en cuanto se recuperaban."""
        degraded = self.staleness.exchange_is_degraded()
        self.salud, que, motivo = evaluar(self.salud, Senyales(utcnow_ms(), datos_obsoletos=degraded))

        if que == ENTRAR:
            stale = sorted(self.staleness.stale_symbols())
            change = self.modes.activate(
                Mode.CLOSE_ONLY_DEGRADED, f"datos obsoletos en {stale}"
            )
            if change:
                log.error("MODO %s: %s", change.mode, change.reason)
                await self.mode_repo.record(change)
                self.bus.emit(
                    EventKind.MODE_CHANGE, mode=str(change.mode), activated=True,
                    reason=change.reason,
                )
        elif que == SALIR:
            change = self.modes.deactivate(
                Mode.CLOSE_ONLY_DEGRADED, f"datos recuperados ({motivo})"
            )
            if change:
                log.info("MODO %s levantado", change.mode)
                await self.mode_repo.record(change)
                self.bus.emit(
                    EventKind.MODE_CHANGE, mode=str(change.mode), activated=False,
                    reason=change.reason,
                )

    async def _gap_loop(self) -> None:
        # Primera pasada poco despues de que el WebSocket coja carrerilla.
        #
        # Entre que termina el backfill de un simbolo y el WebSocket empieza a
        # entregar sus velas pasan segundos o minutos, y ahi queda un hueco en
        # la costura: con 8 monedas x 5 timeframes el backfill tarda mas de un
        # minuto, asi que los primeros simbolos se quedan sin los minutos que
        # median. Esperar al ciclo normal de 15 min dejaria ese agujero visible
        # en el criterio de avance sin necesidad.
        await asyncio.sleep(SEAM_SCAN_SECONDS)
        if self.rest is not None and not self._stopping.is_set():
            try:
                summary = await self.rest.scan_and_fill()
                log.info(
                    "costura backfill/WS: %d huecos detectados, %d rellenados",
                    summary["detected"],
                    summary["filled"],
                )
            except Exception as exc:
                log.error("fallo el escaneo de la costura: %s", exc)

        while not self._stopping.is_set():
            await asyncio.sleep(GAP_SCAN_SECONDS)
            if self.rest is None:
                continue
            try:
                summary = await self.rest.scan_and_fill()
                if summary["detected"]:
                    log.info(
                        "huecos: %d detectados, %d rellenados",
                        summary["detected"],
                        summary["filled"],
                    )
            except Exception as exc:
                log.error("fallo la busqueda de huecos: %s", exc)

    async def _health_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(HEALTH_PERSIST_SECONDS)
            await self._persist_health()

    async def _persist_health(self) -> None:
        for state in self.staleness.states():
            if state.last_update_ms is None:
                continue
            with contextlib.suppress(Exception):
                if state.stale:
                    await self.health.mark_stale(
                        state.source, state.symbol, "sin actualizar", utcnow_ms()
                    )
                else:
                    await self.health.touch(
                        state.source, state.symbol, state.last_update_ms
                    )

    async def _latido_loop(self) -> None:
        """Late SOLO con todas las velas de 1 m frescas. Si la ingesta se para, se
        cuelga o deja de recibir datos, el latido falta y el vigilante avisa. La
        peticion va en un hilo: nunca frena el bucle de la ingesta."""
        while not self._stopping.is_set():
            await asyncio.sleep(LATIDO_SECONDS)
            with contextlib.suppress(Exception):
                if self.staleness.todo_fresco(self.settings.whitelist) and self._guardado_al_dia():
                    await asyncio.to_thread(self.latido.enviar)

    def _guardado_al_dia(self, ahora_ms: int | None = None) -> bool:
        """La ultima vela de 1 m CERRADA y GUARDADA de cada moneda es reciente.

        Lo que se recibe no basta: hay que haberlo escrito. Consulta con indice, en
        el hilo de la ingesta (la conexion es compartida): milisegundos."""
        ahora = ahora_ms if ahora_ms is not None else utcnow_ms()
        for simbolo in self.settings.whitelist:
            ultima = self.candles.last_ts(simbolo, "1m")
            if ultima is None or ahora - (ultima + 60_000) > VELA_1M_MAX_EDAD_MS:
                return False
        return True

    async def _clock_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(CLOCK_CHECK_SECONDS)
            with contextlib.suppress(Exception):
                await self._check_clock()

    async def _check_clock(self) -> None:
        """Informe seccion 1.3[1]: el desfase de reloj rompe las firmas de API."""
        reading = await self.exchange.measure_skew()
        limit = self.settings.data.clock_skew_max_seconds
        if not reading.is_acceptable(limit):
            log.error(
                "DESFASE DE RELOJ: %.2f s (limite %.2f s). "
                "Sincroniza el reloj o las firmas de API fallaran en la fase 4.",
                reading.skew_seconds,
                limit,
            )
            self.bus.emit(
                EventKind.CLOCK_SKEW,
                skew_seconds=reading.skew_seconds,
                limit_seconds=limit,
            )
        else:
            log.info("reloj OK: desfase %.3f s", reading.skew_seconds)


async def run(settings: Settings, duration: float | None) -> int:
    service = IngestService(settings)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, request_stop)

    try:
        await service.start()
    except WhitelistMismatchError as exc:
        log.error("EL BOT NO ARRANCA. %s", exc)
        await service.stop()
        return 2
    except Exception as exc:
        log.exception("fallo al arrancar: %s", exc)
        await service.stop()
        return 1

    try:
        if duration:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=duration)
        else:
            await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await service.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ploutos fase 1: ingesta de datos")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="segundos antes de parar solo (por defecto, indefinido)",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        # Sin logging configurado todavia: el mensaje va tal cual a stderr.
        print(f"EL BOT NO ARRANCA. {exc}", file=sys.stderr)
        return 2

    setup_logging(settings.logging.level, settings.logging.file)
    try:
        return asyncio.run(run(settings, args.duration))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
