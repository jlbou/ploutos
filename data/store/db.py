"""Conexion a SQLite en modo WAL y ejecutor de migraciones.

Decisiones:

* WAL (PRD/informe seccion 1.2): lectores concurrentes sin bloquear al escritor.
  Importa porque en la fase 5 la API leera mientras la ingesta escribe.
* UN SOLO ESCRITOR LOGICO: todas las escrituras pasan por `execute` /
  `executemany`, que serializan con un lock y corren en un hilo aparte para no
  bloquear el bucle de asyncio. Las lecturas van directas (WAL lo permite).
* Sin `aiosqlite`: con un unico escritor y unas pocas escrituras por segundo no
  aporta nada que justifique la dependencia.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from core.logging import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA temp_store=MEMORY",
)


class Database:
    """Conexion unica a SQLite con escrituras serializadas."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._write_lock = asyncio.Lock()

    # --- ciclo de vida ---

    def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if mode.lower() != "wal":
            raise RuntimeError(
                f"se esperaba journal_mode=WAL y quedo {mode!r}; "
                "revisa el sistema de ficheros (WAL no funciona en algunos "
                "recursos de red)"
            )
        self._conn = conn
        log.info("base de datos abierta en %s (WAL)", self.path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("la base de datos no esta conectada; llama a connect()")
        return self._conn

    # --- lecturas (directas, WAL permite concurrencia) ---

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    # --- escrituras (serializadas) ---

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._write_lock:
            return await asyncio.to_thread(self._execute_sync, sql, params)

    async def executemany(
        self, sql: str, rows: Iterable[Sequence[Any]]
    ) -> int:
        batch = list(rows)
        if not batch:
            return 0
        async with self._write_lock:
            return await asyncio.to_thread(self._executemany_sync, sql, batch)

    def _execute_sync(self, sql: str, params: Sequence[Any]) -> int:
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def _executemany_sync(self, sql: str, rows: list[Sequence[Any]]) -> int:
        with self.conn:
            cur = self.conn.executemany(sql, rows)
            return cur.rowcount

    def execute_sync(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Escritura sincrona. Solo para arranque, migraciones y tests."""
        return self._execute_sync(sql, params)

    def executemany_sync(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        batch = list(rows)
        if not batch:
            return 0
        return self._executemany_sync(sql, batch)


# --- migraciones ---


def _ensure_schema_table(db: Database) -> None:
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_ms INTEGER NOT NULL
        )
        """
    )


def applied_versions(db: Database) -> set[int]:
    _ensure_schema_table(db)
    return {row["version"] for row in db.query("SELECT version FROM schema_version")}


def migrate(db: Database, migrations_dir: Path | None = None) -> list[str]:
    """Aplica las migraciones pendientes en orden. Idempotente.

    Devuelve los nombres aplicados en esta llamada.
    """
    from core.clock import utcnow_ms

    directory = migrations_dir or MIGRATIONS_DIR
    _ensure_schema_table(db)
    done = applied_versions(db)
    applied: list[str] = []

    for path in sorted(directory.glob("*.sql")):
        try:
            version = int(path.name.split("_", 1)[0])
        except ValueError:
            raise RuntimeError(
                f"migracion mal nombrada: {path.name} (se espera NNN_nombre.sql)"
            ) from None
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        with db.conn:
            db.conn.executescript(sql)
            db.conn.execute(
                "INSERT INTO schema_version (version, name, applied_ms) VALUES (?, ?, ?)",
                (version, path.name, utcnow_ms()),
            )
        applied.append(path.name)
        log.info("migracion aplicada: %s", path.name)

    return applied


def open_database(path: str | Path, run_migrations: bool = True) -> Database:
    """Abre la base de datos y la deja lista para usar."""
    db = Database(path)
    db.connect()
    if run_migrations:
        migrate(db)
    return db
