"""Una sola vez (16/10/2026): pasa los libros que el recolector guardo en gzip (var/libros/*.jsonl.gz, antes de pasar a
SQLite) a var/ploutos-libros.db, y dice cuantos. No borra los gzip: eso se hace a mano tras comprobarlo.

    .venv/bin/python docs/estudios/paso2/migrar_libros_gz.py
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from recolector_libros import abrir, guardar  # noqa: E402


def main() -> int:
    filas = []
    for f in sorted((REPO / "var" / "libros").glob("libros-*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as g:
            for d in map(json.loads, filter(None, g.read().splitlines())):
                filas.append((d["par"], int(d["ms"]), int(d["ts_libro"]),
                              json.dumps(d["asks"], separators=(",", ":")), json.dumps(d["bids"], separators=(",", ":"))))
    conn = abrir()
    guardar(conn, filas)
    total = conn.execute("SELECT COUNT(*) FROM libros").fetchone()[0]
    conn.close()
    print(f"migrados {len(filas)} libros; en la base, {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
