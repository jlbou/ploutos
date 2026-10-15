"""El servicio de noticias `ploutos-news` (docs/diseno-noticias.md, pieza 4).

Cada 5 min: lee los anuncios de OKX (`data/news/okx.py`), guarda los nuevos en su base
(`var/ploutos-news.db`), deriva las flags (`features/news.py`) y encola los avisos de Telegram,
que manda con el mismo sistema que las carteras (`notify.outbox`). Late a Healthchecks solo si
la lectura fue bien.

Lo que NO hace, y es a proposito:
- **No toca las carteras.** Los bucles de papel LEEN su base (mode=ro) y aplican el filtro y la
  salida a mercado ellos mismos: si este servicio se cae, las carteras siguen (decision del propietario,
  opcion B del 22/09).
- **No bloquea nada si la fuente cae**: avisa (tras 1 h sin una lectura buena) y las flags ya
  vistas se mantienen hasta que caduquen, porque se derivan de lo guardado.

    .venv/bin/python scripts/run_news.py                   # el servicio
    .venv/bin/python scripts/run_news.py --una-vez         # una pasada y sale
    .venv/bin/python scripts/run_news.py --status          # flags activas y ultima lectura
    .venv/bin/python scripts/run_news.py --levantar <clave> --motivo "texto"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import Settings, load_settings  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from data.news import okx  # noqa: E402
from data.news import store as db  # noqa: E402
from features.news import Flag, bases_de, flags, pendientes_del_propietario  # noqa: E402
from notify import messages as m  # noqa: E402
from notify.latido import Latido  # noqa: E402
from notify.outbox import enviar_pendientes  # noqa: E402
from portfolio import store as cola  # noqa: E402  (encolar_avisos: misma tabla paper_avisos)

PASADA_S = 300
FUENTE_CAIDA_MS = 3600_000              # aviso tras 1 h sin una lectura buena (disenyo, pieza 7)
HORA_PENDIENTES = (0, 10)               # el recordatorio diario, con el resumen de las carteras
QUOTE = "USDC"

log = logging.getLogger("ploutos.news")


def par_de(f: Flag) -> str:
    return f"{f.moneda}/{QUOTE}"


class NewsRunner:
    SERVICIO = "ploutos-news"
    LATIDO = "healthcheck_noticias"

    def __init__(self, ruta_db: Path | str, *, settings: Settings | None = None,
                 secretos: Secrets | None = None, _leer: Any = okx.leer,
                 _enviar: Any = enviar_pendientes, _latido: Latido | None = None) -> None:
        self.settings = settings or load_settings()
        self.bases = bases_de(self.settings.whitelist)
        self.conn = db.conectar(ruta_db)
        db.migrar(self.conn)
        secretos = secretos or Secrets()
        self._token = secretos.valor("telegram_bot_token")
        self._chat = secretos.telegram_chat_id
        self._leer, self._enviar = _leer, _enviar
        self._latido = _latido or Latido(secretos.valor(self.LATIDO), self.SERVICIO)

    def flags(self) -> list[Flag]:
        return flags(db.anuncios(self.conn), self.bases, levantadas=db.levantadas(self.conn))

    def avisos(self, ahora_ms: int) -> list[tuple[str, str, str]]:
        """(tipo, clave, texto). La clave hace que cada aviso salga UNA vez (UNIQUE en la tabla)."""
        out = []
        for f in self.flags():
            if f.activa(ahora_ms):
                out.append(("noticia", f"noticia:{f.clave}", m.aviso_noticia(
                    par_de(f), str(f.tipo), str(f.gravedad), f.titulo, url=f.anuncio, hasta_ms=f.hasta_ms)))
        ultima = db.ultima_lectura_buena(self.conn)
        primera = self.conn.execute("SELECT MIN(ms) FROM news_lecturas").fetchone()[0]
        desde = ultima if ultima is not None else primera
        if desde is not None and ahora_ms - desde >= FUENTE_CAIDA_MS:
            out.append(("noticia", f"noticia:caida:{desde}", m.fuente_noticias_caida(desde, ahora_ms)))
        ahora = datetime.fromtimestamp(ahora_ms / 1000, tz=UTC)
        if (ahora.hour, ahora.minute) >= HORA_PENDIENTES:
            # Solo las que ya estaban AYER: el dia en que sale un aviso, el propietario ya tiene ese aviso;
            # recordarselo en el mismo momento seria un segundo mensaje igual (revision del 25/09).
            hoy_ms = int(ahora.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            pend = [(par_de(f), str(f.tipo), f.desde_ms, f.titulo)
                    for f in pendientes_del_propietario(self.flags(), ahora_ms) if f.desde_ms < hoy_ms]
            texto = m.noticias_pendientes(pend, ahora_ms)
            if texto:
                out.append(("noticia", f"noticia:pendientes:{ahora:%Y-%m-%d}", texto))
        return out

    def pasada(self, ahora_ms: int | None = None) -> dict[str, Any]:
        """Una vuelta. NUNCA lanza: un fallo aqui es "no nos hemos enterado", no una caida."""
        ahora_ms = ahora_ms if ahora_ms is not None else int(time.time() * 1000)
        try:
            lectura = self._leer(ya_vistos=db.ids_vistos(self.conn))
            nuevos = db.guardar(self.conn, lectura.anuncios, ahora_ms)
            ok = not lectura.fuente_caida
            db.registrar_lectura(self.conn, ahora_ms, ok, len(lectura.anuncios), nuevos, lectura.errores)
            cola.encolar_avisos(self.conn, ahora_ms, self.avisos(ahora_ms))
            enviados, error = self._enviar(self.conn, self._token, self._chat, ahora_ms)
            if ok:
                self._latido.enviar()
            return {"ok": ok, "nuevos": nuevos, "errores": lectura.errores,
                    "enviados": enviados, "error_envio": error}
        except Exception as exc:   # la base, un bug: se apunta y la siguiente vuelta lo reintenta
            log.exception("la pasada de noticias fallo")
            return {"ok": False, "nuevos": 0, "errores": [f"{type(exc).__name__}: {exc}"],
                    "enviados": 0, "error_envio": None}

    def estado(self, ahora_ms: int) -> str:
        activas = [f for f in self.flags() if f.activa(ahora_ms)]
        ultima = db.ultima_lectura_buena(self.conn)
        lineas = [f"ultima lectura buena: {datetime.fromtimestamp(ultima / 1000, tz=UTC):%d/%m %H:%M UTC}"
                  if ultima else "ultima lectura buena: ninguna todavia",
                  f"anuncios guardados: {self.conn.execute('SELECT COUNT(*) FROM news_anuncios').fetchone()[0]}",
                  f"flags activas: {len(activas)}"]
        for f in activas:
            hasta = "no caduca (la levanta el propietario)" if f.hasta_ms is None else \
                f"hasta {datetime.fromtimestamp(f.hasta_ms / 1000, tz=UTC):%d/%m %H:%M UTC}"
            lineas.append(f"  {par_de(f)} {f.tipo} ({f.gravedad}), {hasta}\n    clave: {f.clave}")
        return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Servicio de noticias (anuncios de OKX)")
    ap.add_argument("--db", default=str(REPO / "var" / "ploutos-news.db"))
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--levantar", metavar="CLAVE")
    ap.add_argument("--motivo", default="")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    r = NewsRunner(args.db)
    ahora = int(time.time() * 1000)
    if args.status:
        print(r.estado(ahora))
        return 0
    if args.levantar:
        if not args.motivo.strip():
            print("hace falta --motivo \"...\": queda apuntado por que se levanto")
            return 1
        claves = {f.clave for f in r.flags()}
        if args.levantar not in claves:
            print(f"no hay ninguna flag con la clave {args.levantar!r}; mira --status")
            return 1
        db.levantar(r.conn, args.levantar, args.motivo, ahora)
        print(f"levantada: {args.levantar} ({args.motivo})")
        return 0
    while True:
        info = r.pasada()
        log.info("pasada: %s", info)
        if args.una_vez:
            return 0 if info["ok"] else 1
        time.sleep(PASADA_S)


if __name__ == "__main__":
    sys.exit(main())
