"""Copia la base de exploracion y le anyade velas de 1 dia (idea 5), hechas con las de 4 h.

Dias UTC COMPLETOS (las 6 velas de 00:00 a 20:00): apertura de la primera, maximo y minimo de las
seis, cierre de la ultima. Asi el dia es el UTC, no el de Hong Kong de la vela "1D" de OKX.

    python agregar_1d.py <base de exploracion> <base de salida>
"""
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

origen, salida = Path(sys.argv[1]), Path(sys.argv[2])
if salida.exists():
    raise SystemExit(f"{salida} ya existe")
src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
dst = sqlite3.connect(salida)
src.backup(dst)
src.close()

DIA, H4 = 86_400_000, 4 * 3600_000
velas = defaultdict(list)
for sym, ts, o, h, lo, c, v in dst.execute(
        "SELECT symbol, ts_open_ms, open, high, low, close, volume FROM candles WHERE timeframe='4h' ORDER BY ts_open_ms"):
    velas[(sym, ts // DIA)].append((ts, o, h, lo, c, v))
filas = []
for (sym, d), vs in velas.items():
    if len(vs) != 6 or vs[0][0] != d * DIA or vs[-1][0] != d * DIA + 5 * H4:
        continue                                   # dia incompleto: fuera
    filas.append((sym, "1d", d * DIA, vs[0][1], max(x[2] for x in vs), min(x[3] for x in vs), vs[-1][4],
                  sum(x[5] for x in vs), 1, "agregada", 0))
dst.executemany("INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume, closed,"
                " source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)", filas)
dst.commit()
for sym, n in dst.execute("SELECT symbol, COUNT(*) FROM candles WHERE timeframe='1d' GROUP BY symbol"):
    print(f"{sym:10s} {n} dias")
dst.close()
