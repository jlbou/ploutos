"""La base de los comandos de Telegram (`var/ploutos-control.db`, pieza 5 del diseno).

La escribe el servicio `ploutos-telegram` (y `run_telegram.py --levantar-kill`, a mano en el
VPS); las carteras y el juez de papel la abren con `solo_lectura`. La pausa y la parada no se
guardan: se derivan de `comandos()` con `notify.comandos.reconstruir`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from notify.comandos import Comando, Orden

MIGRACIONES = Path(__file__).resolve().parent.parent / "data" / "store" / "control_migrations"


def conectar(ruta: Path | str) -> sqlite3.Connection:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta))
    conn.row_factory = sqlite3.Row
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA busy_timeout=5000"):
        conn.execute(pragma)
    return conn


def solo_lectura(ruta: Path | str) -> sqlite3.Connection | None:
    """Para las carteras y el juez. None si la base aun no existe (el servicio no ha arrancado
    nunca): entonces nadie ha mandado nada, y las carteras no cambian sus modos."""
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


def comandos(conn: sqlite3.Connection) -> list[Comando]:
    """Todos los comandos ejecutados, en el orden en que se aplicaron."""
    return [Comando(-1 if r["update_id"] is None else r["update_id"], r["ts_ms"], Orden(r["orden"]), r["texto"])
            for r in conn.execute("SELECT update_id, ts_ms, orden, texto FROM control_comandos ORDER BY id")]


def ultimo_update_id(conn: sqlite3.Connection) -> int | None:
    """El ultimo mensaje de Telegram ya tratado (ejecutado o ignorado): se pide desde el siguiente."""
    fila = conn.execute(
        "SELECT MAX(u) FROM (SELECT MAX(update_id) AS u FROM control_comandos"
        " UNION ALL SELECT MAX(update_id) FROM control_ignorados)").fetchone()
    return fila[0] if fila else None


def guardar_comando(conn: sqlite3.Connection, c: Comando, *, recibido_ms: int, origen: str,
                    respuesta: str | None) -> int:
    """El comando y su respuesta (en la cola de avisos), en UNA transaccion: no puede quedar
    un comando aplicado sin respuesta, ni una respuesta de un comando que no se guardo."""
    with conn:
        cur = conn.execute(
            "INSERT INTO control_comandos (update_id, ts_ms, recibido_ms, orden, texto, origen)"
            " VALUES (?,?,?,?,?,?)",
            (c.update_id if origen == "telegram" else None, c.ts_ms, recibido_ms, c.orden.value, c.texto, origen))
        cid = int(cur.lastrowid)
        if respuesta is not None:
            conn.execute("INSERT INTO paper_avisos (ts_ms, tipo, clave, texto) VALUES (?,?,?,?)",
                         (recibido_ms, "comando", f"comando:{cid}", respuesta))
    return cid


def guardar_ignorado(conn: sqlite3.Connection, update_id: int, motivo: str, *, recibido_ms: int,
                     respuesta: str | None) -> None:
    with conn:
        conn.execute("INSERT OR IGNORE INTO control_ignorados (update_id, recibido_ms, motivo) VALUES (?,?,?)",
                     (update_id, recibido_ms, motivo))
        if respuesta is not None:
            conn.execute("INSERT OR IGNORE INTO paper_avisos (ts_ms, tipo, clave, texto) VALUES (?,?,?,?)",
                         (recibido_ms, "comando", f"ignorado:{update_id}", respuesta))


def registrar_lectura(conn: sqlite3.Connection, ms: int, ok: bool, updates: int, error: str) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO control_lecturas (ms, ok, updates, error) VALUES (?,?,?,?)",
                     (ms, int(ok), updates, error[:2000]))
