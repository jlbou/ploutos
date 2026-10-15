"""La base de los medios en sombra (`var/ploutos-medios.db`). La escribe SOLO `ploutos-medios`."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from data.medios.rss import Titular
from features.news import DURACIONES_H, Anuncio, Tipo

MIGRACIONES = Path(__file__).resolve().parent.parent / "store" / "medios_migrations"
# Las de los anuncios de OKX, salvo el deslistado: de un medio no lo levanta nadie, asi que cuenta 72 h
# (docs/diseno-medios-sombra.md 3, fijado antes de mirar).
DURACIONES_SOMBRA_H = {**DURACIONES_H, Tipo.DELISTING: 72}


def conectar(ruta: Path | str) -> sqlite3.Connection:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta))
    conn.row_factory = sqlite3.Row
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA busy_timeout=5000"):
        conn.execute(pragma)
    return conn


def migrar(conn: sqlite3.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    hechas = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    aplicadas = []
    for ruta in sorted(MIGRACIONES.glob("*.sql")):
        version = int(ruta.name.split("_", 1)[0])
        if version in hechas:
            continue
        with conn:
            conn.executescript(ruta.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (version, ruta.name))
        aplicadas.append(ruta.name)
    return aplicadas


def guardar(conn: sqlite3.Connection, titulares: list[Titular], calidad: str, visto_ms: int) -> int:
    """Guarda los nuevos; devuelve cuantos eran nuevos. Una fecha en el futuro (reloj del medio mal) se queda en la
    de cuando se vio: si no, una flag en sombra podria empezar antes de existir la noticia."""
    with conn:
        antes = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO medios_titulares (id, fuente, calidad, titulo, enlace, publicado_ms, visto_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            [(t.id, t.fuente, calidad, t.titulo, t.enlace,
              None if t.publicado_ms is None else min(t.publicado_ms, visto_ms), visto_ms) for t in titulares])
        return conn.total_changes - antes


def registrar_lectura(conn: sqlite3.Connection, ms: int, fuente: str, ok: bool, titulares: int, nuevos: int,
                      error: str | None) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO medios_lecturas (ms, fuente, ok, titulares, nuevos, error)"
                     " VALUES (?,?,?,?,?,?)", (ms, fuente, int(ok), titulares, nuevos, (error or "")[:500]))


def anuncios(conn: sqlite3.Connection) -> list[Anuncio]:
    """Los titulares como "anuncios", para derivar las flags EN SOMBRA con el clasificador de OKX tal cual. Sin fecha
    del medio, cuenta la de cuando se vio."""
    return [Anuncio(r["id"], r["publicado_ms"] if r["publicado_ms"] is not None else r["visto_ms"], r["titulo"])
            for r in conn.execute("SELECT id, publicado_ms, visto_ms, titulo FROM medios_titulares")]


def resumen_fuentes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT t.fuente, t.calidad, COUNT(*) AS titulares,"
        " (SELECT MAX(ms) FROM medios_lecturas l WHERE l.fuente = t.fuente AND l.ok = 1) AS ultima_buena,"
        " (SELECT error FROM medios_lecturas l WHERE l.fuente = t.fuente ORDER BY ms DESC LIMIT 1) AS ultimo_error"
        " FROM medios_titulares t GROUP BY t.fuente ORDER BY t.calidad, t.fuente"))
