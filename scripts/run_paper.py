"""Bucle de papel en vivo (criterio de avance ampliado de la fase 2).

    velas cerradas -> filtros -> candidatos -> baseline -> motor de riesgo -> papel

SOLO LEE de la base principal y SOLO ESCRIBE en la suya. Eso no es una
comodidad: mientras corren las 72 h de la fase 1, el proceso de ingesta es lo
que se esta midiendo, y en SQLite-WAL los lectores no bloquean al escritor pero
dos escritores si compiten. Ver la cabecera de
`data/store/paper_migrations/001_paper.sql`.

NO HABLA CON EL EXCHANGE NI NECESITA SUS CLAVES. Todo lo que mira son velas que
la ingesta ya ha guardado (fases 1-3: datos publicos, PRD seccion 12). Desde el
24/09/2026 lee de `.env` UNA cosa, opcional: las credenciales de Telegram, para
los avisos (`notify/outbox.py`). Sin ellas, los avisos se quedan en la base.

    python scripts/run_paper.py
    python scripts/run_paper.py --once        # una pasada y salir
    python scripts/run_paper.py --status      # que hay ahora mismo

SE PUEDE REINICIAR EN CUALQUIER MOMENTO. El estado vive en la base de papel y
el cursor dice hasta que vela se proceso, asi que al arrancar sigue donde
estaba en vez de empezar de cero o reprocesar.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import load_settings  # noqa: E402
from core.modes import Mode  # noqa: E402
from core.logging import setup_logging  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from notify import control  # noqa: E402
from notify import messages as avisos_txt  # noqa: E402
from notify.comandos import Comando, cerrar_todo_en, reconstruir  # noqa: E402
from notify.latido import Latido  # noqa: E402
from notify.outbox import avisos_de_la_vela, enviar_pendientes, resumen_si_toca  # noqa: E402
from core.clock import timeframe_ms  # noqa: E402
from data.news import store as noticias  # noqa: E402
from data.usdc import fetch_mids, public_client  # noqa: E402
from features.news import Flag, bases_de, event_flags, flags, pares_criticos  # noqa: E402
from features.usdc import bloquea_paridad, usdc_parity  # noqa: E402
from portfolio import store  # noqa: E402
from portfolio.loop import TradingLoop  # noqa: E402
from portfolio.paper import Bar, PaperBroker, PaperLedger  # noqa: E402
from risk.types import Instrument  # noqa: E402
from strategy.costs import CostModel  # noqa: E402
from strategy.pipeline import MarketData, filas_sin_senyal  # noqa: E402

log = logging.getLogger("ploutos.paper")

# Cada cuanto se mira si hay vela nueva. Con velas de 4 h no hace falta correr:
# un minuto de retraso en una decision de 4 h no cambia nada, y sondear cada
# pocos segundos solo gasta CPU y castiga la base que la ingesta esta usando.
POLL_SECONDS = 60

# Velas de historia que se cargan para decidir. El percentil del regimen pide
# 60 valores no nulos del ATR y el ATR se come 42 velas de calentamiento.
HISTORY_BARS = 200
# Cuanto se espera a las monedas que faltan de una vela ya cerrada (ver `_closed_bars_after`).
ESPERA_VELA_MS = 2 * 60_000

_stop = False


def _handle_signal(signum, _frame) -> None:
    global _stop
    _stop = True
    log.info("senyal %s recibida: terminando despues de esta pasada", signum)


class PaperRunner:
    # Quien decide en esta cartera. El baseline es `rank`, dentro del bucle; la
    # cartera de la IA (`scripts/run_paper_ai.py`) cambia estas tres cosas y nada
    # mas. Aqui no se importa `ai/`: el grupo de control no puede depender del
    # codigo de la IA ni para arrancar (test de arquitectura).
    DECIDER = "baseline"
    SERVICIO = "ploutos-paper"
    # La URL de su comprobacion en el vigilante externo (`.env`).
    LATIDO = "healthcheck_papel"

    def _decider(self):
        """El que decide que se le pasa al bucle. None = el baseline."""
        return None

    def _sombra(self):
        """Los candidatos en sombra (decision 5 de la fase 6). None = sin sombra: el baseline no la tiene."""
        return None

    def _extras(self, stamp: int, result) -> tuple[list, list, int]:
        """(journal del analista, cambios de modo, entradas canceladas por esos
        cambios) de esta vela, para guardarlos en la MISMA transaccion que la
        vela. El baseline no tiene."""
        return [], [], 0

    def _between_candles(self) -> None:
        """Lo que se hace en cada vuelta aunque no haya vela nueva (las sondas de
        la IA en CLOSE_ONLY_QUOTA). El baseline, nada."""

    def _ahora_ms(self) -> int:
        """El reloj de los avisos. La cartera de la IA lo cambia por el suyo."""
        return int(time.time() * 1000)

    def __init__(self, args) -> None:
        self.settings = load_settings()
        # Telegram (PRD seccion 9): opcional. Sin credenciales los avisos se quedan
        # en la base y no se mandan. Es lo UNICO de .env que lee este proceso.
        secretos = Secrets()
        self._tg_token = (
            secretos.telegram_bot_token.get_secret_value().strip()
            if secretos.telegram_bot_token else None
        )
        self._tg_chat = secretos.telegram_chat_id
        self._ultimo_error_tg: str | None = None
        # El vigilante externo: sin latido, Healthchecks.io avisa de que esto se ha parado.
        self._latido = Latido(secretos.valor(self.LATIDO), self.SERVICIO)
        self.timeframe = args.tf
        self.main_db = Path(args.main_db)
        self.paper_db = Path(args.paper_db)

        # Lectura pura de la base principal. `mode=ro` es una red de seguridad
        # explicita: aunque alguien anyada un INSERT por error, SQLite lo
        # rechaza en vez de escribir en la base que se esta midiendo.
        self.main = sqlite3.connect(
            f"file:{self.main_db}?mode=ro", uri=True, timeout=10
        )
        self.main.row_factory = sqlite3.Row

        self.paper = store.connect(self.paper_db)
        applied = store.migrate(self.paper)
        if applied:
            log.info("esquema de papel aplicado: %s", applied)

        # Comisiones de settings.yaml, no las de ccxt (decision del propietario, 23/09/2026).
        rows = self.settings.exchange.fees.apply(
            [dict(r) for r in self.main.execute("SELECT * FROM instruments")]
        )
        if not rows:
            raise SystemExit(
                "la tabla `instruments` esta vacia: arranca antes la ingesta"
            )
        self.instruments = {r["symbol"]: Instrument.from_row(r) for r in rows}
        self.cost = CostModel.from_repo(
            type("R", (), {"all": lambda _self: rows})(),
            now_ms=max(r["fetched_ms"] for r in rows),
        )

        self.starting_usd = args.equity
        self.slider = args.slider
        # Noticias (pieza 4c): la base de `ploutos-news`, SOLO en lectura. Las dos carteras leen
        # la misma, asi que el baseline y la IA reciben las mismas flags (decision del propietario, 22/09).
        self.news_db = Path(getattr(args, "news_db", None) or REPO / "var" / "ploutos-news.db")
        self._flags_vistas: list[Flag] = []
        # Comandos de Telegram (docs/diseno-comandos-telegram.md): la base de `ploutos-telegram`,
        # SOLO en lectura. Las dos carteras leen la misma: una pausa las para a las dos.
        self.control_db = Path(getattr(args, "control_db", None) or REPO / "var" / "ploutos-control.db")
        self._comandos_vistos: list[Comando] | None = None
        # De donde salen los precios de la regla 17. Los tests lo sustituyen:
        # un test que llama a la red depende de la red.
        self._okx = None
        self.usdc_mids = self._fetch_usdc_mids
        self.reload()

        log.info(
            "arrancado: %d posicion(es), %d pendiente(s), %d operacion(es) "
            "cerradas, cursor %s",
            len(self.broker.positions), len(self.broker.pending),
            len(self.broker.trades),
            datetime.fromtimestamp(self.cursor / 1000, tz=UTC).isoformat()
            if self.cursor else "sin empezar",
        )

    def reload(self) -> None:
        """(Re)construye el simulador y el bucle desde la base de papel.

        Se llama al arrancar y TAMBIEN cuando una pasada falla a medias: para
        entonces el simulador en memoria puede haber avanzado la vela (llenado
        una entrada, envejecido una orden, apuntado equity) sin que se haya
        guardado nada. Reintentar sobre ese estado aplicaria la misma vela dos
        veces. Tirarlo y recargar lo guardado deja el estado exactamente como
        estaba en la ultima vela que si se completo.
        """
        self.broker = PaperBroker(self.instruments)
        self.ledger = PaperLedger(starting_usd=self.starting_usd, broker=self.broker)
        store.load_state(self.paper, self.broker, self.ledger)
        self.loop = TradingLoop(
            instruments=self.instruments,
            cost=self.cost,
            settings=self.settings,
            broker=self.broker,
            ledger=self.ledger,
            timeframe=self.timeframe,
            slider_level=self.slider,
            modes=store.load_modes(self.paper),
            decide=self._decider(),
            sombra=self._sombra(),
        )
        self.cursor = store.cursor(self.paper, self.timeframe)

    def _fetch_usdc_mids(self) -> dict[str, float | None]:
        if self._okx is None:
            self._okx = public_client(self.settings)
        return fetch_mids(self._okx)

    # --- lectura de velas ---

    def _closed_bars_after(self, ts_ms: int | None) -> list[int]:
        """Las velas listas para procesar despues del cursor, en orden: las que tienen cerradas TODAS las
        monedas de la whitelist.

        BUG REAL (27/09/2026, 04:00): bastaba con que UNA moneda tuviera la vela cerrada. La ingesta escribe
        las ocho en ~1,5 s y el bucle miro en medio: proceso la vela sin DOGE (y el baseline, sin XRP). Para
        esas monedas no se miro el stop ni el objetivo de esa vela, la posicion se valoro a precio de entrada
        y el generador vio la vela anterior. Lo cazo el juez de papel (equity 50,398 contra 50,263).

        Si una moneda no llega en ESPERA_VELA_MS tras el cierre (la ingesta de esa moneda falla), se procesa
        con las que hay y se dice en el log: el bucle no puede quedarse parado por una moneda. Nunca se salta
        una vela: si la primera no esta lista, no se procesa ninguna de las siguientes.
        """
        monedas = tuple(self.settings.whitelist)
        sql = (
            "SELECT ts_open_ms, COUNT(DISTINCT symbol) FROM candles WHERE timeframe = ? AND closed = 1"
            f" AND symbol IN ({','.join('?' * len(monedas))})"
        )
        params: list[object] = [self.timeframe, *monedas]
        if ts_ms is not None:
            sql += " AND ts_open_ms > ?"
            params.append(ts_ms)
        sql += " GROUP BY ts_open_ms ORDER BY ts_open_ms"
        ahora, paso = self._ahora_ms(), timeframe_ms(self.timeframe)
        listas: list[int] = []
        for stamp, n in self.main.execute(sql, params):
            if n < len(monedas):
                if ahora < int(stamp) + paso + ESPERA_VELA_MS:
                    break                      # aun estan llegando: se espera, sin saltarse ninguna
                log.warning("vela %s: solo %d de %d monedas %d s despues del cierre; se procesa con las que hay",
                            datetime.fromtimestamp(int(stamp) / 1000, tz=UTC).strftime("%d/%m %H:%M"),
                            n, len(monedas), (ahora - int(stamp) - paso) // 1000)
            listas.append(int(stamp))
        return listas

    def _history(self, symbol: str, until_ms: int) -> pd.DataFrame:
        rows = self.main.execute(
            "SELECT * FROM (SELECT * FROM candles WHERE symbol = ? "
            "AND timeframe = ? AND closed = 1 AND ts_open_ms <= ? "
            "ORDER BY ts_open_ms DESC LIMIT ?) ORDER BY ts_open_ms",
            (symbol, self.timeframe, until_ms, HISTORY_BARS),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def _book(self, symbol: str) -> tuple[float, float]:
        row = self.main.execute(
            "SELECT spread_pct, depth_bid_05pct, depth_ask_05pct FROM book_metrics "
            "WHERE symbol = ? ORDER BY ts_ms DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not row:
            # Sin libro no se puede juzgar la regla 16. Un spread imposible
            # hace que el filtro descarte, que es la direccion segura.
            return 99.0, 0.0
        return (
            float(row["spread_pct"]),
            min(float(row["depth_bid_05pct"]), float(row["depth_ask_05pct"])),
        )

    def _hourly(self, until_ms: int) -> dict[str, pd.Series]:
        """Series de 1 h para las correlaciones de la regla 15 (7 dias)."""
        out: dict[str, pd.Series] = {}
        for symbol in self.settings.whitelist:
            rows = self.main.execute(
                "SELECT * FROM (SELECT ts_open_ms, close FROM candles "
                "WHERE symbol = ? AND timeframe = ? AND closed = 1 "
                "AND ts_open_ms <= ? ORDER BY ts_open_ms DESC LIMIT 200) "
                "ORDER BY ts_open_ms",
                (symbol, "1h", until_ms),
            ).fetchall()
            if rows:
                frame = pd.DataFrame([dict(r) for r in rows])
                out[symbol] = frame.set_index("ts_open_ms")["close"]
        return out

    # --- una pasada ---

    def process(self, stamp: int) -> None:
        market: dict[str, MarketData] = {}
        bars: dict[str, Bar] = {}
        sin_vela: list[str] = []

        for symbol in self.settings.whitelist:
            history = self._history(symbol, stamp)
            if history.empty:
                continue
            ultima = history.iloc[-1]
            if int(ultima["ts_open_ms"]) != stamp:
                # Sin la vela de esta hora (la ingesta no la escribio en ESPERA_VELA_MS): la ultima que hay es
                # una ANTERIOR, y un candidato de esa moneda saldria de una vela vieja. No se le generan
                # candidatos y queda en el journal (28/09: antes ningun juez lo habria visto).
                sin_vela.append(symbol)
                continue
            bars[symbol] = Bar.from_row(ultima.to_dict())
            spread, depth = self._book(symbol)
            market[symbol] = MarketData(
                symbol=symbol,
                candles=history,
                spread_pct=spread,
                depth_usd=depth,
            )

        if not market:
            return

        # Regla 17. OJO: es la paridad de AHORA, no la de la vela: si el bucle
        # se pone al dia de varias velas tras una caida, todas usan la misma
        # lectura. Para velas de 4 h es aceptable; no hay historia de USDC.
        usdc = usdc_parity(self.usdc_mids())
        if usdc.deviation_pct is None:
            log.warning("regla 17: paridad de USDC desconocida (%s); no se entra", usdc.detail)
        tope_usdc = self.settings.risk.usdc_depeg_pct
        anterior = store.ultima_paridad(self.paper, stamp)
        paridad = (
            None if anterior is None else bloquea_paridad(anterior[0], tope_usdc),
            bloquea_paridad(usdc.deviation_pct, tope_usdc), usdc.detail, tope_usdc,
        )
        decision_ms = stamp + timeframe_ms(self.timeframe)
        flags_ahora = self._event_flags(decision_ms)
        result = self.loop.step(
            stamp, market, bars, self._hourly(stamp),
            usdc_deviation_pct=usdc.deviation_pct,
            event_flags=flags_ahora,
            salir_ya=pares_criticos(self._flags_vistas, decision_ms, self.settings.whitelist),
            manuales=self._manuales(decision_ms),
            # Despues de `_manuales`, que acaba de leer la base de control.
            cerrar_todo=cerrar_todo_en(self._comandos_vistos or (), decision_ms, timeframe_ms(self.timeframe)),
        )

        filas: list[tuple] = []
        for c in result.candidates:
            filas.append((c.decision_id, c.symbol, c.setup, "candidate", str(c)))
        for choice in result.submitted:
            c = choice.candidate
            filas.append((c.decision_id, c.symbol, c.setup, "submitted", choice.reason))
        simbolo_de = {o.decision_id: o.symbol for o in self.broker.orders}
        for did in result.canceladas_noticia:
            sim = simbolo_de.get(did)
            filas.append((did, sim, None, "cancelled", "noticia: " + ", ".join(flags_ahora.get(sim, ()))))
        for c, _numeros, motivo in result.vetoed:
            filas.append((c.decision_id, c.symbol, c.setup, "vetoed", motivo))
        if result.pipeline:
            for cribada in result.pipeline.filtered_out:
                filas.append((None, cribada.symbol, None, "filtered", cribada.reason()))
            # Paso los filtros y no dio candidato: por que, en una frase corta, para el panel (el propietario, 29/09).
            # Solo lo apunta; no cambia ninguna decision.
            for symbol, frase in filas_sin_senyal(result.pipeline):
                filas.append((None, symbol, None, "sin_senyal", frase))
        for symbol in sin_vela:
            filas.append((None, symbol, None, "filtered",
                          "sin la vela de esta hora: la ingesta no la escribio a tiempo; sin candidatos"))
        # Journal, contexto de mercado y estado en UNA transaccion: ver
        # `store.save_step`. El contexto es CON QUE se decidio (spread para la
        # regla 16, correlaciones para la 15): sin el, no se puede auditar.
        mercado = [(m.symbol, m.spread_pct, m.depth_usd) for m in market.values()]
        correlaciones = (
            [(a, b, c) for (a, b), c in result.correlations.values.items()]
            if result.correlations else []
        )
        if result.decide_error:
            log.error("el que decide fallo en esta vela (sin entradas): %s", result.decide_error)
        llamadas, mas_cambios, mas_canceladas = self._extras(stamp, result)
        cambios = [*result.mode_changes, *mas_cambios]
        historia = self.ledger.history
        avisos = avisos_de_la_vela(
            ts_ms=stamp, cartera=self.DECIDER, cerradas=result.closed, cambios=cambios,
            canceladas=result.cancelled + mas_canceladas,
            equity_anterior=historia[-2][1] if len(historia) >= 2 else None,
            equity=result.equity_usd, escalones=self.settings.drawdown_tiers,
            journal=llamadas,
            paridad=paridad,
        )
        store.save_step(
            self.paper, self.broker, self.ledger, self.timeframe, stamp, filas,
            decider=self.DECIDER,
            market=mercado, correlations=correlaciones,
            usdc=(usdc.primary, usdc.check, usdc.deviation_pct, usdc.detail),
            mode_changes=[
                (c.mode.name, c.activated, c.reason, c.effective_after.name)
                for c in cambios
            ],
            ai_calls=llamadas,
            avisos=avisos,
        )
        for c in cambios:
            # En la fase 5 esto va tambien a Telegram (PRD seccion 9).
            log.warning("MODO: %s %s (%s)", "entra" if c.activated else "sale", c.mode, c.reason)
        if result.cancelled:
            log.warning("MODO: %d entrada(s) pendiente(s) cancelada(s)", result.cancelled)
        self.cursor = stamp

        for trade in result.closed:
            log.info("cerrada: %s", trade)
        if result.sombra:
            log.info("sombra: %d candidato(s) con la cartera llena (no se abre nada): %s", len(result.sombra),
                     ", ".join(c.decision_id for c in result.sombra))
        for choice in result.submitted:
            log.info("orden: %s", choice.candidate)
        log.info("%s", result.summary())

    def catch_up(self) -> int:
        """Procesa todas las velas cerradas que falten. Devuelve cuantas."""
        pendientes = self._closed_bars_after(self.cursor)
        if self.cursor is None and len(pendientes) > HISTORY_BARS:
            # Primer arranque: no se reproduce toda la historia, se empieza en
            # la ultima vela. El recorrido historico ya existe aparte
            # (`scripts/replay_baseline.py`) y mezclarlo con el vivo haria
            # imposible saber que operaciones son de verdad "en vivo".
            log.info(
                "primer arranque: se ignoran %d velas anteriores y se empieza "
                "en la ultima", len(pendientes) - 1,
            )
            pendientes = pendientes[-1:]
        for stamp in pendientes:
            self.process(stamp)
        return len(pendientes)

    def status(self) -> None:
        print(f"Bucle de papel ({self.timeframe})")
        print("=" * 60)
        cuando = (
            datetime.fromtimestamp(self.cursor / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
            if self.cursor else "sin empezar"
        )
        print(f"  ultima vela procesada  {cuando} UTC")
        print(f"  modo efectivo          {self.loop.modes.effective}")
        print(f"  posiciones abiertas    {len(self.broker.positions)}")
        for p in self.broker.positions.values():
            print(f"     {p.symbol} {p.setup}: entrada {p.entry_price:.6g}, "
                  f"stop {p.stop_price:.6g}, objetivo {p.target_price:.6g}")
        print(f"  entradas pendientes    {len(self.broker.pending)}")
        for o in self.broker.pending:
            print(f"     {o.symbol} {o.setup}: limite {o.limit_price:.6g} "
                  f"({o.bars_waited} vela(s) esperando)")
        stats = self.broker.stats()
        print(f"  operaciones cerradas   {stats['trades']}")
        if stats["trades"]:
            print(f"     aciertos {stats['win_rate_pct']:.0f} %, "
                  f"expectativa {stats['expectancy_r']:+.3f} R, "
                  f"neto {stats['net_pnl_usd']:+.3f} $")
        if self.ledger.history:
            print(f"  equity                 {self.ledger.history[-1][1]:.2f} $ "
                  f"(drawdown max {self.ledger.max_drawdown_pct():.2f} %)")

    def _event_flags(self, decision_ms: int) -> dict[str, tuple[str, ...]]:
        """Las flags de noticias activas en el instante de la decision (el CIERRE de la vela).

        Al cierre y no a la apertura: un deslistado anunciado a las 10:30 tiene que parar la
        decision de las 12:00 de la vela de 08:00-12:00. Sin base (el servicio aun no esta)
        no hay flags; si la base falla al leerse, se usan las ULTIMAS que se vieron: una flag
        critica ya vista se mantiene aunque la fuente caiga (decision del propietario del 22/09).
        """
        try:
            conn = noticias.solo_lectura(self.news_db)
            if conn is not None:
                try:
                    self._flags_vistas = flags(noticias.anuncios(conn), bases_de(self.settings.whitelist),
                                               levantadas=noticias.levantadas(conn))
                finally:
                    conn.close()
        except Exception:
            log.warning("no se pudo leer la base de noticias: se usan las ultimas flags vistas", exc_info=True)
        return event_flags(self._flags_vistas, decision_ms, self.settings.whitelist)

    def _manuales(self, decision_ms: int) -> dict[Mode, str] | None:
        """La pausa y la parada de Telegram en el instante de la decision (el CIERRE de la vela),
        como las noticias: un comando cuenta para las velas que cierran despues de enviarlo.

        Sin base (el servicio aun no esta) -> None: no se toca ningun modo. Si la base falla al
        leerse, se usan los ULTIMOS comandos vistos: una pausa ya vista no se pierde por eso.
        """
        try:
            conn = control.solo_lectura(self.control_db)
            if conn is not None:
                try:
                    self._comandos_vistos = control.comandos(conn)
                finally:
                    conn.close()
        except Exception:
            log.warning("no se pudo leer la base de control: se usan los ultimos comandos vistos",
                        exc_info=True)
        if self._comandos_vistos is None:
            return None
        return reconstruir([c for c in self._comandos_vistos if c.ts_ms <= decision_ms]).modos

    def tick(self) -> None:
        """Una vuelta del bucle vivo. Nunca lanza."""
        try:
            self.catch_up()
            self._between_candles()
            # Solo tras una vuelta SIN error: un bucle vivo pero atascado no late.
            self._latido.enviar()
        except Exception:
            # Un fallo en una pasada no puede tumbar el bucle: la vela
            # siguiente vuelve a intentarlo. El cursor no avanza, y el
            # estado en memoria se TIRA y se recarga de la base, porque
            # puede haber avanzado a medias (ver `reload`).
            log.exception("fallo procesando una vela; se recarga y se reintenta")
            self.reload()
        self._avisos()

    def _avisos(self) -> None:
        """El resumen diario, si toca, y mandar lo pendiente. Aparte y blindado: un
        fallo de Telegram no puede provocar la recarga del bucle ni tocar la vela."""
        try:
            ahora = self._ahora_ms()
            resumen = resumen_si_toca(self.paper, self.DECIDER, ahora, self.settings)
            if resumen is not None:
                store.encolar_avisos(self.paper, ahora, [resumen])
            _enviados, error = enviar_pendientes(self.paper, self._tg_token, self._tg_chat, ahora)
            if error != self._ultimo_error_tg:
                # Una vez por cambio, no en cada vuelta: sin credenciales seria cada minuto.
                if error:
                    log.warning("avisos de Telegram sin mandar: %s", error)
                self._ultimo_error_tg = error
        except Exception:
            log.exception("avisos de Telegram: fallo (el bucle sigue)")

    def _aviso_parada(self, motivo: str) -> None:
        """PRD seccion 9: parada del bot. Se intenta mandar ya; si no sale, queda en
        la base y sale al volver a arrancar (el descarte de 12 h lo acota)."""
        try:
            ahora = self._ahora_ms()
            store.encolar_avisos(self.paper, ahora, [(
                "parada", f"{self.DECIDER}:parada:{ahora}", avisos_txt.bot_parado(self.SERVICIO, motivo),
            )])
            enviar_pendientes(self.paper, self._tg_token, self._tg_chat, ahora)
        except Exception:
            log.exception("aviso de parada: fallo")

    def _aviso_arranque(self) -> None:
        """Si la ultima vez se paro limpiamente (y aviso), avisa de que ha vuelto (el propietario, 26/09): tras
        un "parado" llega siempre su "en marcha de nuevo". Un primer arranque no avisa de nada."""
        try:
            def ultima(tipo: str) -> int | None:
                return self.paper.execute(
                    "SELECT MAX(ts_ms) FROM paper_avisos WHERE tipo = ?", (tipo,)).fetchone()[0]

            parada, arranque = ultima("parada"), ultima("arranque")
            if parada is None or (arranque is not None and arranque >= parada):
                return
            ahora = self._ahora_ms()
            store.encolar_avisos(self.paper, ahora, [(
                "arranque", f"{self.DECIDER}:arranque:{ahora}",
                avisos_txt.bot_en_marcha(self.SERVICIO, parada, ahora),
            )])
        except Exception:
            log.exception("aviso de arranque: fallo")

    def run(self) -> None:
        self._aviso_arranque()
        log.info("bucle en marcha, sondeo cada %d s", POLL_SECONDS)
        while not _stop:
            self.tick()
            for _ in range(POLL_SECONDS):
                if _stop:
                    break
                time.sleep(1)
        log.info("parado limpiamente")
        self._aviso_parada("parado limpiamente (reinicio, actualizacion o parada manual)")


def main(runner_cls=None, paper_db_default: str | None = None) -> int:
    """Tambien la usa `scripts/run_paper_ai.py`, con su clase y su base."""
    runner_cls = runner_cls or PaperRunner
    parser = argparse.ArgumentParser(description=f"Bucle de papel en vivo ({runner_cls.DECIDER})")
    parser.add_argument("--tf", default="4h")
    parser.add_argument("--equity", type=float, default=50.0)
    parser.add_argument("--slider", type=int, default=3)
    parser.add_argument("--main-db", default=str(REPO / "var" / "ploutos.db"))
    parser.add_argument("--paper-db", default=paper_db_default or str(REPO / "var" / "ploutos-paper.db"))
    parser.add_argument("--news-db", default=str(REPO / "var" / "ploutos-news.db"),
                        help="la base del servicio de noticias (solo lectura)")
    parser.add_argument("--control-db", default=str(REPO / "var" / "ploutos-control.db"),
                        help="la base de los comandos de Telegram (solo lectura)")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--reset-capital", metavar="MOTIVO", default=None,
        help="levanta CLOSE_ONLY_CAPITAL (regla 7). Solo a mano, con un motivo. "
             f"Despues: systemctl restart {runner_cls.SERVICIO}",
    )
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    setup_logging(level="INFO")
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    runner = runner_cls(args)
    if args.reset_capital is not None:
        if Mode.CLOSE_ONLY_CAPITAL not in runner.loop.modes.active:
            print("CLOSE_ONLY_CAPITAL no esta activo: no hay nada que levantar.")
            return 1
        if not args.reset_capital.strip():
            print("Hace falta un motivo: queda en el journal.")
            return 1
        cambio = runner.loop.modes.manual_reset(
            Mode.CLOSE_ONLY_CAPITAL, args.reset_capital.strip()
        )
        store.record_manual_reset(
            runner.paper, int(time.time() * 1000), Mode.CLOSE_ONLY_CAPITAL.name,
            args.reset_capital.strip(), cambio.effective_after.name,
        )
        print("CLOSE_ONLY_CAPITAL levantado. Reinicia el servicio para que lo vea:")
        print(f"    systemctl restart {runner_cls.SERVICIO}")
        return 0
    if args.status:
        runner.status()
        return 0
    if args.once:
        procesadas = runner.catch_up()
        print(f"{procesadas} vela(s) procesada(s)")
        return 0
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
