"""Recolector de libros de ordenes (paso 2, comprobacion V5; propietario, 15/10/2026): cada hora, el libro de BTC-EUR y
ETH-EUR de OKX (400 niveles por lado, la API PUBLICA: sin claves, solo lee) y lo guarda, para medir el deslizamiento
con 10.000 € en momentos distintos (no una foto). Se para solo a partir del FIN.

Desde el 16/10 en una base SQLite (`var/ploutos-libros.db`), no en ficheros gzip: entra en la copia de cada noche con
su verificacion, y una escritura cortada no deja un fichero roto (revision del 16/10). `journal_mode=DELETE`, como el
embudo: el juez y la copia la leen en solo lectura.

    .venv/bin/python scripts/recolector_libros.py          # lo lanza ploutos-libros.timer cada hora
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "var" / "ploutos-libros.db"
PARES = ("BTC-EUR", "ETH-EUR")
FIN = "2026-10-30"          # 2 semanas desde el 16/10
HOST = "https://eea.okx.com"

ESQUEMA = """CREATE TABLE IF NOT EXISTS libros (
    par TEXT NOT NULL, ms INTEGER NOT NULL, ts_libro INTEGER NOT NULL,
    asks TEXT NOT NULL, bids TEXT NOT NULL, PRIMARY KEY (par, ms))"""


def terminado(ahora: datetime) -> bool:
    return ahora.date().isoformat() >= FIN


def abrir(ruta: Path = BASE) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=30)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute(ESQUEMA)
    return conn


def fila(par: str, ms: int, libro: dict) -> tuple:
    """Solo precio y cantidad de cada nivel (lo demas no hace falta)."""
    niveles = lambda lado: json.dumps([[float(p), float(q)] for p, q, *_ in libro[lado]], separators=(",", ":"))  # noqa: E731
    return par, ms, int(libro["ts"]), niveles("asks"), niveles("bids")


def guardar(conn: sqlite3.Connection, filas: list[tuple]) -> None:
    with conn:
        conn.executemany("INSERT OR IGNORE INTO libros VALUES (?, ?, ?, ?, ?)", filas)


def main() -> int:
    ahora = datetime.now(UTC)
    if terminado(ahora):
        print(f"V5 terminada el {FIN}: no se recoge nada mas")
        return 0
    ms, fallos, filas = int(ahora.timestamp() * 1000), 0, []
    for par in PARES:
        try:
            req = urllib.request.Request(f"{HOST}/api/v5/market/books?instId={par}&sz=400",
                                         headers={"User-Agent": "Mozilla/5.0"})
            filas.append(fila(par, ms, json.loads(urllib.request.urlopen(req, timeout=20).read())["data"][0]))
        except Exception as exc:  # noqa: BLE001 - una moneda que falla no tumba la otra
            fallos += 1
            print(f"{par}: no se pudo leer ({type(exc).__name__})")
        time.sleep(0.5)
    if filas:
        conn = abrir()
        try:
            guardar(conn, filas)
        finally:
            conn.close()
    print(f"{ahora:%Y-%m-%d %H:%M} UTC: {len(filas)} libros guardados, {fallos} fallos")
    return 1 if fallos == len(PARES) else 0


if __name__ == "__main__":
    sys.exit(main())
