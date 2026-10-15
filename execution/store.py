"""La base del ejecutor (`var/ploutos-exec.db`, `data/store/exec_migrations/`): leer y escribir, nada mas.

Un solo escritor (el ejecutor). Todo lo que importa a una regla (posiciones, cierres del dia, la foto del saldo, el
modo CAPITAL enclavado) vive aqui y no en memoria: el servicio lleva `Restart=always` y lo que vive en memoria se
pierde al reiniciar (CLAUDE.md, trampas).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from execution.equity import Foto
from execution.riesgo import CierreDemo, EntradaDemo, PosicionDemo

MIGRATIONS = Path(__file__).resolve().parent.parent / "data" / "store" / "exec_migrations"


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
    for ruta in sorted(MIGRATIONS.glob("*.sql")):
        version = int(ruta.name.split("_", 1)[0])
        if version in hechas:
            continue
        with conn:
            conn.executescript(ruta.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (version, ruta.name))
        aplicadas.append(ruta.name)
    return aplicadas


# --- La foto ----------------------------------------------------------------------------------------------------


def foto(conn: sqlite3.Connection) -> tuple[int, float, Foto] | None:
    r = conn.execute("SELECT ts_ms, capital_usd, datos FROM exec_foto WHERE id = 1").fetchone()
    return None if r is None else (r["ts_ms"], r["capital_usd"], Foto.de_dict(json.loads(r["datos"])))


def guardar_foto(conn: sqlite3.Connection, ts_ms: int, capital_usd: float, f: Foto) -> None:
    """Una sola vez: una segunda foto con posiciones abiertas contaria como ajeno lo que es del bot."""
    with conn:
        conn.execute("INSERT INTO exec_foto (id, ts_ms, capital_usd, datos) VALUES (1, ?, ?, ?)",
                     (ts_ms, capital_usd, json.dumps(f.a_dict())))


# --- Decisiones tratadas ----------------------------------------------------------------------------------------


def tratadas(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute("SELECT decision_id FROM exec_tratadas"))


def tratar(conn: sqlite3.Connection, decision_id: str, ts_ms: int, que: str, motivo: str,
           cantidad_papel: float | None = None, cantidad: float | None = None) -> None:
    with conn:
        conn.execute("INSERT OR IGNORE INTO exec_tratadas VALUES (?, ?, ?, ?, ?, ?)",
                     (decision_id, ts_ms, que, motivo, cantidad_papel, cantidad))


# --- Entradas, posiciones y cierres -----------------------------------------------------------------------------


def entradas(conn: sqlite3.Connection) -> list[EntradaDemo]:
    return [EntradaDemo(r["decision_id"], r["simbolo"], r["cantidad"], r["limite"], r["stop"], r["creada_ms"])
            for r in conn.execute("SELECT * FROM exec_entradas ORDER BY creada_ms, decision_id")]


def entrada_completa(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM exec_entradas WHERE decision_id = ?", (decision_id,)).fetchone()


def guardar_entrada(conn: sqlite3.Connection, decision_id: str, simbolo: str, cantidad: float, limite: float,
                    stop: float, objetivo: float, creada_ms: int, enviada_ms: int) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO exec_entradas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (decision_id, simbolo, cantidad, limite, stop, objetivo, creada_ms, enviada_ms))


def borrar_entrada(conn: sqlite3.Connection, decision_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM exec_entradas WHERE decision_id = ?", (decision_id,))


def posiciones(conn: sqlite3.Connection) -> list[PosicionDemo]:
    return [PosicionDemo(r["decision_id"], r["simbolo"], r["cantidad"], r["entrada"], r["stop"], r["objetivo"],
                         r["abierta_ms"])
            for r in conn.execute("SELECT * FROM exec_posiciones ORDER BY abierta_ms, decision_id")]


def posicion_completa(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM exec_posiciones WHERE decision_id = ?", (decision_id,)).fetchone()


def vendiendo(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute(
        "SELECT decision_id FROM exec_posiciones WHERE vendiendo_ms IS NOT NULL"))


def guardar_posicion(conn: sqlite3.Connection, decision_id: str, simbolo: str, cantidad: float, entrada: float,
                     stop: float, objetivo: float, abierta_ms: int, comision_entrada_usd: float) -> None:
    """Crea o pone al dia (un llenado parcial que crece): idempotente."""
    with conn:
        conn.execute(
            "INSERT INTO exec_posiciones (decision_id, simbolo, cantidad, entrada, stop, objetivo, abierta_ms,"
            " comision_entrada_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(decision_id) DO UPDATE SET"
            " cantidad = excluded.cantidad, entrada = excluded.entrada,"
            " comision_entrada_usd = excluded.comision_entrada_usd",
            (decision_id, simbolo, cantidad, entrada, stop, objetivo, abierta_ms, comision_entrada_usd))


def marcar_vendiendo(conn: sqlite3.Connection, decision_id: str, ts_ms: int) -> None:
    with conn:
        conn.execute("UPDATE exec_posiciones SET vendiendo_ms = ? WHERE decision_id = ?", (ts_ms, decision_id))


def cerrar(conn: sqlite3.Connection, decision_id: str, *, salida: float, cerrada_ms: int, motivo: str,
           comision_salida_usd: float, estimada: bool) -> CierreDemo | None:
    """De posicion a cierre, en una transaccion. Devuelve el cierre (o None si no habia posicion)."""
    p = posicion_completa(conn, decision_id)
    if p is None:
        return None
    pnl = (salida - p["entrada"]) * p["cantidad"] - p["comision_entrada_usd"] - comision_salida_usd
    por_stop = motivo == "sl"
    with conn:
        conn.execute("INSERT OR REPLACE INTO exec_cierres VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (decision_id, p["simbolo"], p["cantidad"], p["entrada"], salida, p["abierta_ms"], cerrada_ms,
                      motivo, pnl, int(por_stop), int(estimada)))
        conn.execute("DELETE FROM exec_posiciones WHERE decision_id = ?", (decision_id,))
    return CierreDemo(decision_id, p["simbolo"], cerrada_ms, pnl, por_stop)


def cierres(conn: sqlite3.Connection, desde_ms: int = 0) -> list[CierreDemo]:
    return [CierreDemo(r["decision_id"], r["simbolo"], r["cerrada_ms"], r["pnl_usd"], bool(r["por_stop"]))
            for r in conn.execute("SELECT * FROM exec_cierres WHERE cerrada_ms >= ? ORDER BY cerrada_ms",
                                  (desde_ms,))]


# --- Journal, pasadas, equity y modos ---------------------------------------------------------------------------


def apuntar(conn: sqlite3.Connection, ts_ms: int, decision_id: str | None, que: str, resultado: str,
            detalle: str = "", peticion: Any = None) -> None:
    with conn:
        conn.execute("INSERT INTO exec_journal (ts_ms, decision_id, que, peticion, resultado, detalle)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (ts_ms, decision_id, que, None if peticion is None else json.dumps(peticion, default=str),
                      resultado, detalle))


def guardar_pasada(conn: sqlite3.Connection, ts_ms: int, cuadra: bool, acciones: list, descuadres: list,
                   sin_oco: list) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO exec_pasadas VALUES (?, ?, ?, ?, ?)",
                     (ts_ms, int(cuadra), json.dumps(acciones), json.dumps(descuadres), json.dumps(sorted(sin_oco))))


def ultima_pasada(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM exec_pasadas ORDER BY ts_ms DESC LIMIT 1").fetchone()


def guardar_equity(conn: sqlite3.Connection, ts_ms: int, equity_usd: float, fiable: bool, usdc_usd: float,
                   valor_usd: float) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO exec_equity VALUES (?, ?, ?, ?, ?)",
                     (ts_ms, equity_usd, int(fiable), usdc_usd, valor_usd))


def ultima_equity(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM exec_equity ORDER BY ts_ms DESC LIMIT 1").fetchone()


def guardar_modo(conn: sqlite3.Connection, ts_ms: int, modo: str, activo: bool, motivo: str) -> None:
    with conn:
        conn.execute("INSERT INTO exec_modos (ts_ms, modo, activo, motivo) VALUES (?, ?, ?, ?)",
                     (ts_ms, modo, int(activo), motivo))


def modos_activos(conn: sqlite3.Connection) -> dict[str, str]:
    """El ultimo cambio de cada modo, si lo dejo activo: modo -> motivo (CAPITAL enclavado sobrevive al reinicio)."""
    activos = {}
    for r in conn.execute("SELECT modo, activo, motivo FROM exec_modos ORDER BY id"):
        if r["activo"]:
            activos[r["modo"]] = r["motivo"]
        else:
            activos.pop(r["modo"], None)
    return activos
