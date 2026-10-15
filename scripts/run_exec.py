"""El ejecutor del demo de OKX (fase 4): `ploutos-exec`. El UNICO servicio que lee las claves de OKX.

Espeja en el demo la cartera de la IA en papel (decisiones del propietario del 24/09, 26/09 y 02/10; `docs/archivo/diseno-fase-4.md`):
mismas ordenes, sin llamadas nuevas a la IA, con las 19 reglas otra vez sobre el estado del demo, el stop y el objetivo
adjuntos en el exchange y la conciliacion cada 5 min. La logica esta en `execution/ejecutor.py`; aqui, el arranque, las
comprobaciones de la cuenta y el bucle.

NO ARRANCA (exit 1) si:
- la clave no es la del DEMO (nada de dinero real hasta la fase 7);
- la clave tiene permiso de retirada, o no tiene el de trading (regla 19);
- la comision no se cobra en USDC (`feeType = 1`, decision 2 de la fase 4).
Y solo opera los pares cuya comision REAL no sea mas cara que la configurada (decisiones del 23/09 y 02/10): en el
demo, NEAR se queda en papel.

    python scripts/run_exec.py                 # el servicio
    python scripts/run_exec.py --once          # una vuelta y salir
    python scripts/run_exec.py --status        # que hay ahora (sin hablar con OKX)
    python scripts/run_exec.py --reset-capital "motivo"   # levanta CLOSE_ONLY_CAPITAL (solo a mano)

Nunca imprime ni guarda credenciales: los errores de OKX llevan el tipo y el cuerpo de la respuesta, no las cabeceras.
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
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.clock import timeframe_ms  # noqa: E402
from core.config import Settings, load_settings  # noqa: E402
from core.logging import setup_logging  # noqa: E402
from core.modes import Mode  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from data.news import store as noticias  # noqa: E402
from execution import comisiones, guardia  # noqa: E402
from execution import store as db  # noqa: E402
from execution.ejecutor import VUELTA_MS, Ejecutor  # noqa: E402
from features.news import Flag, bases_de, event_flags, flags  # noqa: E402
from notify import control  # noqa: E402
from notify import messages as avisos_txt  # noqa: E402
from notify.comandos import Comando, reconstruir  # noqa: E402
from notify.latido import Latido  # noqa: E402
from notify.outbox import enviar_pendientes  # noqa: E402
from portfolio import store as papel_store  # noqa: E402
from risk.types import Instrument  # noqa: E402

log = logging.getLogger("ploutos.exec")
SERVICIO = "ploutos-exec"
LATIDO = "healthcheck_ejecutor"
_stop = False


def _handle_signal(signum, _frame) -> None:
    global _stop
    _stop = True
    log.info("senyal %s: parando al acabar la vuelta", signum)


# --- Comprobaciones de arranque (puras: lo que contesto OKX) ---------------------------------------------------


def motivos_cuenta(config: dict[str, Any]) -> list[str]:
    """Lo que impide arrancar, leido de `GET /api/v5/account/config`."""
    datos = ((config or {}).get("data") or [{}])[0]
    perm = {p.strip() for p in str(datos.get("perm", "")).split(",") if p.strip()}
    motivos = []
    if "withdraw" in perm:
        motivos.append("la clave TIENE permiso de retirada (regla 19)")
    if "trade" not in perm:
        motivos.append(f"la clave no tiene permiso de trading (perm = {sorted(perm)})")
    if str(datos.get("feeType")) != "1":
        motivos.append(f"feeType = {datos.get('feeType')}: la comision no va en USDC (fijar_comision_usdc.py)")
    return motivos


def instrumentos_de(markets: dict[str, Any], whitelist: tuple[str, ...], settings: Settings) -> dict[str, Instrument]:
    """Los instrumentos del EXCHANGE al que se manda (en el demo, sus ticks: preparacion-fase-4 12) con las
    comisiones de settings.yaml (decision del 23/09)."""
    f = settings.exchange.fees
    out = {}
    for s in whitelist:
        m = markets.get(s)
        if m is None:
            continue
        out[s] = Instrument(s, float(m["precision"]["price"]), float(m["precision"]["amount"]),
                            float(m["limits"]["amount"]["min"] or 0.0), f.maker_pct / 100, f.taker_pct / 100)
    return out


# --- El servicio -----------------------------------------------------------------------------------------------


class Servicio:
    def __init__(self, args) -> None:
        self.args = args
        self.settings = load_settings()
        secretos = Secrets()
        self._tg_token = (secretos.telegram_bot_token.get_secret_value().strip()
                          if secretos.telegram_bot_token else None)
        self._tg_chat = secretos.telegram_chat_id
        self._ultimo_error_tg: str | None = None
        self._latido = Latido(secretos.valor(LATIDO), SERVICIO)
        self.secretos = secretos
        self.conn = db.conectar(args.exec_db)
        aplicadas = db.migrar(self.conn)
        if aplicadas:
            log.info("esquema del ejecutor aplicado: %s", aplicadas)
        self.news_db, self.control_db = Path(args.news_db), Path(args.control_db)
        self._flags_vistas: list[Flag] = []
        self._comandos_vistos: list[Comando] | None = None
        self.ej: Ejecutor | None = None

    def ahora_ms(self) -> int:
        return int(time.time() * 1000)

    def arrancar(self) -> None:
        import ccxt
        s = self.secretos
        if not s.has_okx:
            raise SystemExit("faltan las credenciales de OKX en .env")
        if not s.okx_demo:
            raise SystemExit("la clave NO es la del demo: nada de dinero real hasta la fase 7. No se arranca.")
        ex = ccxt.okx({
            "hostname": self.settings.exchange.hostname,
            "apiKey": s.okx_api_key.get_secret_value(),
            "secret": s.okx_api_secret.get_secret_value(),
            "password": s.okx_password.get_secret_value(),
            "enableRateLimit": True, "timeout": 10_000,
            "options": {"defaultType": "spot", **guardia.OPCIONES_EXCHANGE},
            "headers": {"User-Agent": "ploutos/0.1"},
        })
        ex.set_sandbox_mode(True)
        ex.load_markets()
        motivos = motivos_cuenta(ex.private_get_account_config())
        if motivos:
            for m in motivos:
                log.error("NO se arranca: %s", m)
            raise SystemExit("la cuenta demo no esta en orden: " + "; ".join(motivos))
        instrumentos = instrumentos_de(ex.markets, tuple(self.settings.whitelist), self.settings)
        conf = (self.settings.exchange.fees.maker_pct, self.settings.exchange.fees.taker_pct)
        reales = {}
        for par in instrumentos:
            r = ex.private_get_account_trade_fee({"instType": "SPOT", "instId": par.replace("/", "-")})
            reales[par] = comisiones.comision_usdc(r)
        operables, fuera = comisiones.operables(tuple(instrumentos), reales, conf)
        for m in fuera:
            log.warning("par que no se opera: %s", m)
        sin_par = [p for p in self.settings.whitelist if p not in instrumentos]
        log.info("operables en el demo: %s; sin par en el demo: %s", ", ".join(operables) or "(ninguno)",
                 ", ".join(sin_par) or "(ninguno)")
        db.apuntar(self.conn, self.ahora_ms(), None, "arranque", "ok",
                   f"operables {list(operables)}; fuera {fuera}; sin par {sin_par}")
        self.ej = Ejecutor(ex=ex, settings=self.settings, conn=self.conn, papel_db=Path(self.args.paper_db),
                           instrumentos=instrumentos, operables=operables, tf_ms=timeframe_ms(self.args.tf),
                           manuales=self._manuales, flags=self._flags, reloj=self.ahora_ms)

    # Las mismas fuentes y las mismas reglas que la cartera de papel (scripts/run_paper.py).

    def _manuales(self, ahora_ms: int) -> dict[Mode, str] | None:
        try:
            c = control.solo_lectura(self.control_db)
            if c is not None:
                try:
                    self._comandos_vistos = control.comandos(c)
                finally:
                    c.close()
        except Exception:
            log.warning("no se pudo leer la base de control: se usan los ultimos comandos vistos", exc_info=True)
        if self._comandos_vistos is None:
            return None
        return reconstruir([c for c in self._comandos_vistos if c.ts_ms <= ahora_ms]).modos

    def _flags(self, ahora_ms: int) -> dict[str, tuple[str, ...]]:
        try:
            c = noticias.solo_lectura(self.news_db)
            if c is not None:
                try:
                    self._flags_vistas = flags(noticias.anuncios(c), bases_de(self.settings.whitelist),
                                               levantadas=noticias.levantadas(c))
                finally:
                    c.close()
        except Exception:
            log.warning("no se pudo leer la base de noticias: se usan las ultimas flags vistas", exc_info=True)
        return event_flags(self._flags_vistas, ahora_ms, self.settings.whitelist)

    def vuelta(self) -> None:
        try:
            inf = self.ej.vuelta()
            for h in inf.hechos:
                log.info(h)
            if inf.leido and inf.modo is not Mode.CLOSE_ONLY_DEGRADED:
                self._latido.enviar()      # solo si OKX contesto y no esta degradado
        except Exception as exc:
            log.exception("fallo en la vuelta: la siguiente vuelve a leer OKX (gana el exchange)")
            try:          # como mucho un aviso por hora: un fallo que se repite cada 15 s no puede llenar Telegram
                ahora = self.ahora_ms()
                papel_store.encolar_avisos(self.conn, ahora, [(
                    "exec", f"exec:fallo:{ahora // 3_600_000}",
                    f"<b>Demo</b> · fallo en la vuelta del ejecutor: {type(exc).__name__}: {str(exc)[:300]}")])
            except Exception:
                log.exception("aviso del fallo: fallo")
        self._avisos()

    def _avisos(self) -> None:
        try:
            _enviados, error = enviar_pendientes(self.conn, self._tg_token, self._tg_chat, self.ahora_ms())
            if error != self._ultimo_error_tg:
                if error:
                    log.warning("avisos de Telegram sin mandar: %s", error)
                self._ultimo_error_tg = error
        except Exception:
            log.exception("avisos de Telegram: fallo (el bucle sigue)")

    def aviso_arranque(self) -> None:
        """Tras un "parado" llega siempre su "en marcha de nuevo" (el propietario, 26/09), como en los demas servicios."""
        try:
            parada = aviso_pendiente(self.conn)
            if parada is None:
                return
            ahora = self.ahora_ms()
            papel_store.encolar_avisos(self.conn, ahora, [(
                "arranque", f"exec:arranque:{ahora}", avisos_txt.bot_en_marcha(SERVICIO, parada, ahora))])
        except Exception:
            log.exception("aviso de arranque: fallo")

    def run(self) -> None:
        self.aviso_arranque()
        log.info("ejecutor en marcha, una vuelta cada %d s", VUELTA_MS // 1000)
        while not _stop:
            self.vuelta()
            for _ in range(VUELTA_MS // 1000):
                if _stop:
                    break
                time.sleep(1)
        log.info("parado limpiamente")
        try:
            ahora = self.ahora_ms()
            papel_store.encolar_avisos(self.conn, ahora, [(
                "parada", f"exec:parada:{ahora}", avisos_txt.bot_parado(SERVICIO, "parado limpiamente"))])
            enviar_pendientes(self.conn, self._tg_token, self._tg_chat, ahora)
        except Exception:
            log.exception("aviso de parada: fallo")


def aviso_pendiente(conn: sqlite3.Connection) -> int | None:
    """La hora del ultimo "parado" si aun no tiene su "en marcha"; si no, None (un primer arranque no avisa)."""
    def ultima(tipo: str) -> int | None:
        return conn.execute("SELECT MAX(ts_ms) FROM paper_avisos WHERE tipo = ?", (tipo,)).fetchone()[0]
    parada, arranque = ultima("parada"), ultima("arranque")
    if parada is None or (arranque is not None and arranque >= parada):
        return None
    return parada


def estado(conn: sqlite3.Connection) -> str:
    """Lo que hay ahora, leido de la base (sin hablar con OKX)."""
    def hora(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%d/%m %H:%M:%S")
    lineas = []
    f = db.foto(conn)
    lineas.append("foto: " + ("ninguna (no ha arrancado nunca)" if f is None else f"{hora(f[0])}, capital {f[1]} $"))
    activos = db.modos_activos(conn)
    lineas.append("modos: " + (", ".join(f"{m} ({r})" for m, r in activos.items()) or "NORMAL"))
    e = db.ultima_equity(conn)
    if e is not None:
        lineas.append(f"equity: {e['equity_usd']:.2f} $ ({'fiable' if e['fiable'] else 'NO fiable'}) a las {hora(e['ts_ms'])}")
    for x in db.entradas(conn):
        lineas.append(f"entrada {x.decision_id}: {x.cantidad:g} {x.simbolo} a {x.limite:g}, stop {x.stop:g}")
    for p in db.posiciones(conn):
        lineas.append(f"posicion {p.decision_id}: {p.cantidad:g} {p.simbolo} a {p.entrada:g}, stop {p.stop:g},"
                      f" objetivo {p.objetivo:g}")
    hoy = int(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    c = db.cierres(conn, hoy)
    lineas.append(f"cerradas hoy: {len(c)}, {sum(x.pnl_usd for x in c):+.2f} $")
    p = db.ultima_pasada(conn)
    if p is not None:
        lineas.append(f"ultima conciliacion: {hora(p['ts_ms'])}, {'cuadra' if p['cuadra'] else 'DESCUADRE: ' + p['descuadres']}")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper-ai.db"),
                    help="la cartera de la IA en papel, la que se espeja (solo lectura)")
    ap.add_argument("--news-db", default=str(REPO / "var" / "ploutos-news.db"))
    ap.add_argument("--control-db", default=str(REPO / "var" / "ploutos-control.db"))
    ap.add_argument("--exec-db", default=str(REPO / "var" / "ploutos-exec.db"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset-capital", metavar="MOTIVO", default=None)
    args = ap.parse_args()
    setup_logging(level="INFO")
    if args.status:
        conn = db.conectar(args.exec_db)
        db.migrar(conn)
        print(estado(conn))
        return 0
    if args.reset_capital is not None:
        conn = db.conectar(args.exec_db)
        db.migrar(conn)
        if Mode.CLOSE_ONLY_CAPITAL.name not in db.modos_activos(conn):
            print("CLOSE_ONLY_CAPITAL no esta activo: no hay nada que levantar.")
            return 1
        if not args.reset_capital.strip():
            print("Hace falta un motivo: queda en la base.")
            return 1
        db.guardar_modo(conn, int(time.time() * 1000), Mode.CLOSE_ONLY_CAPITAL.name, False,
                        f"reset manual: {args.reset_capital.strip()}")
        print(f"CLOSE_ONLY_CAPITAL levantado. Reinicia el servicio: systemctl restart {SERVICIO}")
        return 0
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    s = Servicio(args)
    s.arrancar()
    if args.once:
        s.vuelta()
        print(estado(s.conn))
        return 0
    s.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
