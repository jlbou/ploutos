"""El servicio de comandos de Telegram `ploutos-telegram` (docs/diseno-comandos-telegram.md, pieza 5).

Escucha con `getUpdates` (sondeo largo: sin webhook, porque el cortafuegos solo deja entrar SSH),
interpreta cada mensaje (`notify.comandos`), guarda los comandos en su base
(`var/ploutos-control.db`) y contesta por la misma cola que los avisos (`notify.outbox`). Late
a Healthchecks solo si la vuelta fue bien.

Lo que NO hace, y es a proposito:
- **No toca las carteras.** Las dos LEEN su base (mode=ro) y aplican la pausa o la parada ellas
  mismas, al cierre de cada vela. Si este servicio se cae, las carteras siguen como estaban.
- **No levanta un /kill.** Eso solo se hace aqui, en el VPS, a mano y con motivo:

    .venv/bin/python scripts/run_telegram.py                          # el servicio
    .venv/bin/python scripts/run_telegram.py --una-vez                # una vuelta y sale
    .venv/bin/python scripts/run_telegram.py --status                 # pausa, parada, ultimos comandos
    .venv/bin/python scripts/run_telegram.py --levantar-kill "motivo"

OJO: Telegram solo admite UN lector de `getUpdates` por bot. Con este servicio en marcha,
`scripts/setup_telegram.py --chat-id` choca con el (409).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import Settings, load_settings  # noqa: E402
from core.modes import Mode  # noqa: E402
from core.secrets import Secrets, scrub_url  # noqa: E402
from data.news import store as noticias_db  # noqa: E402
from features.news import bases_de, event_flags, flags  # noqa: E402
from notify import control  # noqa: E402
from notify.comandos import (  # noqa: E402
    Comando, Estado, FotoCartera, Orden, aplicar, interpretar, reconstruir, texto_estado,
)
from notify.latido import Latido  # noqa: E402
from notify.outbox import enviar_pendientes  # noqa: E402
from notify.resumen import resumen_desde_base  # noqa: E402
from notify.telegram import call  # noqa: E402

ESPERA_S = 25            # sondeo largo: Telegram contesta en cuanto llega un mensaje, o a los 25 s
PAUSA_TRAS_FALLO_S = 10
CARTERAS = (("baseline", "ploutos-paper.db"), ("ai", "ploutos-paper-ai.db"))

log = logging.getLogger("ploutos.telegram")


def _ahora_ms() -> int:
    return int(time.time() * 1000)


class TelegramRunner:
    SERVICIO = "ploutos-telegram"
    LATIDO = "healthcheck_telegram"

    def __init__(self, ruta_db: Path | str, *, carteras: dict[str, Path], news_db: Path,
                 settings: Settings | None = None, secretos: Secrets | None = None,
                 _call: Any = call, _enviar: Any = enviar_pendientes,
                 _latido: Latido | None = None, _reloj: Any = _ahora_ms) -> None:
        self.settings = settings or load_settings()
        self.conn = control.conectar(ruta_db)
        control.migrar(self.conn)
        self.carteras = carteras
        self.news_db = Path(news_db)
        secretos = secretos or Secrets()
        self._token = secretos.valor("telegram_bot_token")
        self._chat = secretos.telegram_chat_id
        try:
            self._chat_id = int(self._chat) if self._chat else None
        except ValueError:
            self._chat_id = None
        self._call, self._enviar, self._reloj = _call, _enviar, _reloj
        self._latido = _latido or Latido(secretos.valor(self.LATIDO), self.SERVICIO)

    # --- lo que se contesta ---

    def estado_manual(self) -> Estado:
        return reconstruir(control.comandos(self.conn))

    def _foto(self, nombre: str, ruta: Path, ahora_ms: int) -> FotoCartera | None:
        if not ruta.exists():
            return None
        with closing(sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)) as conn:
            hoy = datetime.fromtimestamp(ahora_ms / 1000, tz=UTC).date()
            r = resumen_desde_base(conn, nombre, hoy, self.settings)
            tiene_velas = conn.execute("SELECT 1 FROM paper_equity LIMIT 1").fetchone() is not None
        return FotoCartera(
            nombre=nombre, modo=Mode[r.modo], equity_usd=r.equity_usd if tiene_velas else None,
            cambio_hoy_usd=r.cambio_dia_usd, cerradas_hoy=r.cerradas_hoy, posiciones=r.posiciones,
            ultima_vela_ms=r.ultima_vela_ms, llamadas_ia=r.llamadas_claude,
        )

    def _noticias(self, ahora_ms: int) -> dict[str, tuple[str, ...]] | None:
        conn = noticias_db.solo_lectura(self.news_db)
        if conn is None:
            return None
        with closing(conn):
            todas = flags(noticias_db.anuncios(conn), bases_de(self.settings.whitelist),
                          levantadas=noticias_db.levantadas(conn))
        return event_flags(todas, ahora_ms, self.settings.whitelist)

    def texto_status(self, ahora_ms: int, manual: Estado) -> str:
        fotos = []
        for nombre, ruta in self.carteras.items():
            try:
                foto = self._foto(nombre, ruta, ahora_ms)
            except Exception:
                log.warning("no se pudo leer la cartera %s para /status", nombre, exc_info=True)
                foto = None
            if foto is not None:
                fotos.append(foto)
        try:
            noticias = self._noticias(ahora_ms)
        except Exception:
            log.warning("no se pudo leer la base de noticias para /status", exc_info=True)
            noticias = None
        texto = texto_estado(
            fotos, ahora_ms=ahora_ms, max_posiciones=self.settings.risk.max_positions,
            max_llamadas=self.settings.claude.max_calls_per_day, manual=manual, noticias=noticias,
        )
        if not fotos:
            texto += "\n\n(ninguna cartera tiene datos todavia)"
        return texto

    # --- una vuelta ---

    def tratar(self, update: dict[str, Any], ahora_ms: int) -> None:
        """Un mensaje: se ejecuta y se guarda con su respuesta, o se apunta como ignorado."""
        uid = int(update["update_id"])
        r = interpretar(update, self._chat_id, ahora_ms)
        if isinstance(r, Comando):
            estado = self.estado_manual()
            _nuevo, texto = aplicar(estado, r)
            if texto is None:
                texto = self.texto_status(ahora_ms, estado)
            control.guardar_comando(self.conn, r, recibido_ms=ahora_ms, origen="telegram", respuesta=texto)
            log.info("comando %s ejecutado", r.orden.value)
        else:
            # Nunca el texto: puede ser de cualquiera.
            control.guardar_ignorado(self.conn, uid, r.motivo, recibido_ms=ahora_ms, respuesta=r.respuesta)
            log.info("mensaje ignorado (%s)", r.motivo)

    def vuelta(self) -> dict[str, Any]:
        """Pide los mensajes nuevos, los trata y manda las respuestas. NUNCA lanza."""
        if not self._token or self._chat_id is None:
            return {"ok": False, "updates": 0, "error": "sin TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env"}
        try:
            params: dict[str, Any] = {"timeout": ESPERA_S, "allowed_updates": json.dumps(["message"])}
            ultimo = control.ultimo_update_id(self.conn)
            if ultimo is not None:
                params["offset"] = ultimo + 1       # confirma a Telegram los ya tratados
            updates = self._call(self._token, "getUpdates", params, timeout=ESPERA_S + 10)
            ahora = self._reloj()
            for u in updates:
                self.tratar(u, ahora)
            control.registrar_lectura(self.conn, ahora, True, len(updates), "")
            enviados, error = self._enviar(self.conn, self._token, self._chat, ahora)
            self._latido.enviar()
            return {"ok": True, "updates": len(updates), "enviados": enviados, "error": error}
        except Exception as exc:
            error = scrub_url(f"{type(exc).__name__}: {exc}", self._token)
            log.warning("vuelta de Telegram fallida: %s", error)
            try:
                control.registrar_lectura(self.conn, self._reloj(), False, 0, error)
            except Exception:
                log.exception("ni siquiera se pudo apuntar el fallo")
            return {"ok": False, "updates": 0, "error": error}

    # --- a mano, en el VPS ---

    def levantar_kill(self, motivo: str) -> str:
        motivo = motivo.strip()
        if not motivo:
            raise ValueError('hace falta un motivo: --levantar-kill "..."')
        estado = self.estado_manual()
        if estado.kill_ms is None:
            raise ValueError("no hay ninguna parada (/kill) activa")
        ahora = self._reloj()
        c = Comando(-1, ahora, Orden.LEVANTAR_KILL, motivo)
        _nuevo, texto = aplicar(estado, c)
        control.guardar_comando(self.conn, c, recibido_ms=ahora, origen="vps", respuesta=texto or "")
        return "parada levantada; las carteras la quitan en su proxima vela"

    def estado(self) -> str:
        e = self.estado_manual()
        hora = lambda ms: datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%d/%m %H:%M:%S UTC")  # noqa: E731
        lineas = [
            f"pausa:   {'desde ' + hora(e.pausa_ms) if e.pausa_ms else 'no'}",
            f"parada:  {'desde ' + hora(e.kill_ms) if e.kill_ms else 'no'}",
            "ultimos comandos:",
        ]
        filas = self.conn.execute(
            "SELECT ts_ms, orden, origen FROM control_comandos ORDER BY id DESC LIMIT 10").fetchall()
        lineas += [f"  {hora(r['ts_ms'])}  {r['orden']:<14} {r['origen']}" for r in filas] or ["  ninguno"]
        ultima = self.conn.execute("SELECT MAX(ms) FROM control_lecturas WHERE ok = 1").fetchone()[0]
        lineas.append(f"ultima vuelta buena: {hora(ultima) if ultima else 'ninguna'}")
        return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Servicio de comandos de Telegram")
    ap.add_argument("--db", default=str(REPO / "var" / "ploutos-control.db"))
    ap.add_argument("--var", default=str(REPO / "var"), help="donde estan las bases de las carteras")
    ap.add_argument("--news-db", default=str(REPO / "var" / "ploutos-news.db"))
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--levantar-kill", metavar="MOTIVO")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    r = TelegramRunner(args.db, carteras={n: Path(args.var) / f for n, f in CARTERAS},
                       news_db=Path(args.news_db))
    if args.status:
        print(r.estado())
        return 0
    if args.levantar_kill is not None:
        try:
            print(r.levantar_kill(args.levantar_kill))
        except ValueError as exc:
            print(exc)
            return 1
        return 0
    while True:
        info = r.vuelta()
        if info["updates"] or not info["ok"]:
            log.info("vuelta: %s", info)
        if args.una_vez:
            return 0 if info["ok"] else 1
        if not info["ok"]:
            time.sleep(PAUSA_TRAS_FALLO_S if "sin TELEGRAM" not in str(info["error"]) else 300)


if __name__ == "__main__":
    sys.exit(main())
