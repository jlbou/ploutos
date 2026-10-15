"""La base de noticias (`var/ploutos-news.db`): guardar, leer y levantar (pieza 4).

La escribe SOLO el servicio `ploutos-news`; los bucles de papel la abren con `solo_lectura`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from features.news import Anuncio

MIGRACIONES = Path(__file__).resolve().parent.parent / "store" / "news_migrations"


def conectar(ruta: Path | str) -> sqlite3.Connection:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta))
    conn.row_factory = sqlite3.Row
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA busy_timeout=5000"):
        conn.execute(pragma)
    return conn


def solo_lectura(ruta: Path | str) -> sqlite3.Connection | None:
    """Para los bucles de papel. None si la base aun no existe (el servicio no ha arrancado):
    eso es "no nos hemos enterado de nada", y el filtro deja pasar (decision del propietario)."""
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
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


def ids_vistos(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute("SELECT id FROM news_anuncios"))


def guardar(conn: sqlite3.Connection, anuncios: list[Anuncio], visto_ms: int) -> int:
    """Guarda los nuevos; devuelve cuantos eran nuevos de verdad."""
    with conn:
        antes = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO news_anuncios (id, publicado_ms, titulo, visto_ms) VALUES (?,?,?,?)",
            [(a.id, a.publicado_ms, a.titulo, visto_ms) for a in anuncios])
        return conn.total_changes - antes


def anuncios(conn: sqlite3.Connection) -> list[Anuncio]:
    return [Anuncio(r["id"], r["publicado_ms"], r["titulo"])
            for r in conn.execute("SELECT id, publicado_ms, titulo FROM news_anuncios ORDER BY publicado_ms, id")]


def levantadas(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute("SELECT clave FROM news_levantadas"))


def levantar(conn: sqlite3.Connection, clave: str, motivo: str, ms: int) -> None:
    if not motivo.strip():
        raise ValueError("levantar una flag necesita un motivo: queda en el registro")
    with conn:
        conn.execute("INSERT OR REPLACE INTO news_levantadas (clave, levantada_ms, motivo) VALUES (?,?,?)",
                     (clave, ms, motivo.strip()))


def registrar_lectura(conn: sqlite3.Connection, ms: int, ok: bool, total: int, nuevos: int,
                      errores: list[str]) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO news_lecturas (ms, ok, anuncios, nuevos, errores) VALUES (?,?,?,?,?)",
                     (ms, int(ok), total, nuevos, " | ".join(errores)[:2000]))


def ultima_lectura_buena(conn: sqlite3.Connection) -> int | None:
    fila = conn.execute("SELECT MAX(ms) FROM news_lecturas WHERE ok = 1").fetchone()
    return fila[0] if fila else None
