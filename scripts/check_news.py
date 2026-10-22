"""El juez de la pieza de noticias (docs/diseno-noticias.md, pieza 8).

Criterio de avance de la pieza (seccion 8 del disenyo): el servicio estable una semana sin
huecos, y las carteras con el filtro enchufado DE VERDAD. Esto lo mide, sin reutilizar el
codigo del servicio para juzgarlo: relee las bases y rederiva las flags.

    exit 0 -> criterio CUMPLIDO: >= 7 dias de servicio y todo coherente
    exit 1 -> hay incoherencias (se dice cuales)
    exit 2 -> coherente, pero aun no hay 7 dias

Solo LEE (mode=ro): se puede lanzar en el VPS con todo en marcha.

    .venv/bin/python scripts/check_news.py
    .venv/bin/python scripts/check_news.py --paper-db var/ploutos-paper.db --paper-db var/ploutos-paper-ai.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.clock import timeframe_ms  # noqa: E402
from core import paradas  # noqa: E402
from core.config import load_settings  # noqa: E402
from data.news import store as db  # noqa: E402
from features.news import bases_de, flags  # noqa: E402

HUECO_MAX_MS = 15 * 60_000          # el servicio lee cada 5 min: 15 deja margen para un reinicio
CAIDA_AVISO_MS = 3600_000           # tras 1 h sin lectura buena tenia que avisar (pieza 7)
DIAS_CRITERIO = 7
MAX_EJEMPLOS = 5


class Check:
    def __init__(self, nombre: str):
        self.nombre, self.fallos, self.comprobados = nombre, [], 0
        self.justificados: list[str] = []       # huecos explicados por una parada conocida

    @property
    def ok(self) -> bool:
        return not self.fallos


def _fmt(ms: int) -> str:
    return time.strftime("%d/%m %H:%M", time.gmtime(ms / 1000))


def juzgar(news: sqlite3.Connection, carteras: dict[str, sqlite3.Connection], whitelist: tuple[str, ...],
           tf_ms: int) -> tuple[list[Check], int]:
    """Las comprobaciones, y cuantos ms de servicio hay (de la primera a la ultima lectura)."""
    lecturas = [dict(r) for r in news.execute("SELECT ms, ok FROM news_lecturas ORDER BY ms")]
    avisos = {r[0] for r in news.execute("SELECT clave FROM paper_avisos")}
    todas = flags(db.anuncios(news), bases_de(whitelist), levantadas=db.levantadas(news))
    sin_levantar = flags(db.anuncios(news), bases_de(whitelist))
    checks = []

    c = Check("el servicio no se ha parado (lecturas cada <= 15 min)")
    for a, b in zip(lecturas, lecturas[1:]):
        c.comprobados += 1
        if b["ms"] - a["ms"] > HUECO_MAX_MS:
            hueco = (f"sin lecturas de {_fmt(a['ms'])} a {_fmt(b['ms'])} "
                     f"({(b['ms'] - a['ms']) / 60_000:.0f} min)")
            parada = paradas.justificada(a["ms"], b["ms"])
            if parada is None:
                c.fallos.append(hueco)
            else:
                c.justificados.append(f"{hueco}: {parada.motivo}")
    checks.append(c)

    c = Check("si la fuente cayo mas de 1 h, se aviso")
    ultima_buena = None
    for lec in lecturas:
        c.comprobados += 1
        if lec["ok"]:
            ultima_buena = lec["ms"]
            continue
        desde = ultima_buena if ultima_buena is not None else lecturas[0]["ms"]
        if lec["ms"] - desde >= CAIDA_AVISO_MS and f"noticia:caida:{desde}" not in avisos:
            c.fallos.append(f"la fuente no respondia desde {_fmt(desde)} y a las {_fmt(lec['ms'])} "
                            "no habia aviso")
            ultima_buena = lec["ms"]      # un fallo por caida, no uno por lectura
    checks.append(c)

    c = Check("cada flag que llego a estar activa se aviso")
    for f in todas:
        vista = any(f.activa(lec["ms"]) for lec in lecturas)
        if not vista:
            continue
        c.comprobados += 1
        if f"noticia:{f.clave}" not in avisos:
            c.fallos.append(f"{f.moneda} {f.tipo}: activa y sin aviso ({f.titulo[:60]!r})")
    checks.append(c)

    c = Check("cada flag levantada a mano existe")
    claves = {f.clave for f in sin_levantar}
    for r in news.execute("SELECT clave, motivo FROM news_levantadas"):
        c.comprobados += 1
        if r["clave"] not in claves:
            c.fallos.append(f"levantada {r['clave']!r} no corresponde a ninguna flag")
        if not (r["motivo"] or "").strip():
            c.fallos.append(f"levantada {r['clave']!r} sin motivo")
    checks.append(c)

    c = Check("ninguna cartera genero candidatos de una moneda con flag")
    for nombre, conn in carteras.items():
        for d in conn.execute("SELECT ts_ms, symbol, decision_id FROM paper_decisions "
                              "WHERE kind IN ('candidate', 'submitted')"):
            c.comprobados += 1
            base = (d["symbol"] or "").split("/", 1)[0]
            decision = int(d["ts_ms"]) + tf_ms
            activas = [f for f in todas if f.moneda == base and f.activa(decision)]
            if activas:
                c.fallos.append(f"{nombre}: {d['decision_id']} en {d['symbol']} con {activas[0].tipo} activa")
    checks.append(c)

    servicio = lecturas[-1]["ms"] - lecturas[0]["ms"] if len(lecturas) > 1 else 0
    return checks, servicio


def main() -> int:
    ap = argparse.ArgumentParser(description="Juez de la pieza de noticias")
    ap.add_argument("--news-db", default=str(REPO / "var" / "ploutos-news.db"))
    ap.add_argument("--paper-db", action="append",
                    help="una base de cartera (se puede repetir); por defecto, las dos")
    ap.add_argument("--tf", default="4h")
    args = ap.parse_args()
    settings = load_settings()

    news = db.solo_lectura(args.news_db)
    if news is None:
        print(f"No existe {args.news_db}: el servicio de noticias no ha arrancado.")
        return 2
    rutas = args.paper_db or [str(REPO / "var" / "ploutos-paper.db"), str(REPO / "var" / "ploutos-paper-ai.db")]
    carteras = {}
    for ruta in rutas:
        if Path(ruta).exists():
            conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            carteras[Path(ruta).stem] = conn
    checks, servicio = juzgar(news, carteras, settings.whitelist, timeframe_ms(args.tf))

    print(f"Noticias: {servicio / 86_400_000:.1f} dias de servicio; carteras: {', '.join(carteras) or 'ninguna'}")
    for c in checks:
        print(f"  {'OK   ' if c.ok else 'FALLA'} {c.nombre}  ({c.comprobados} comprobados)")
        for f in c.fallos[:MAX_EJEMPLOS]:
            print(f"          - {f}")
        if len(c.fallos) > MAX_EJEMPLOS:
            print(f"          ... y {len(c.fallos) - MAX_EJEMPLOS} mas")
        for j in c.justificados:
            print(f"          · justificado: {j}")
    print()
    if any(not c.ok for c in checks):
        print("RESULTADO: hay incoherencias. El criterio NO se cumple.")
        return 1
    if servicio < DIAS_CRITERIO * 86_400_000:
        print(f"RESULTADO: coherente, pero solo {servicio / 86_400_000:.1f} dias de {DIAS_CRITERIO}. Aun no.")
        return 2
    print(f"RESULTADO: criterio CUMPLIDO ({servicio / 86_400_000:.1f} dias, todo coherente).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
