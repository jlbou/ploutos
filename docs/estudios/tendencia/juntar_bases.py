"""La exploracion ampliada (`docs/archivo/diseno-tendencia-2.md` 3): exploracion.db + reserva.db en una sola base.

    python juntar_bases.py      # -> var/estudios/exploracion-ampliada.db

Antes de juntar, comprueba que las velas que estan en las dos (05-06/2024, el calentamiento de la reserva) son
IDENTICAS; si no, no junta nada. Instrumentos y spread, los de la exploracion (como en la reserva).
"""
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXPL, RES = REPO / "var/estudios/exploracion.db", REPO / "var/estudios/reserva.db"
DEST = REPO / "var/estudios/exploracion-ampliada.db"
CLAVE = "symbol, timeframe, ts_open_ms"
COLS = "symbol, timeframe, ts_open_ms, open, high, low, close, volume"

if DEST.exists():
    sys.exit(f"{DEST} ya existe: no se pisa")
e = sqlite3.connect(f"file:{EXPL}?mode=ro", uri=True)
r = sqlite3.connect(f"file:{RES}?mode=ro", uri=True)
comunes = distintas = 0
ex = {(s, tf, t): v for s, tf, t, *v in e.execute(f"SELECT {COLS} FROM candles WHERE ts_open_ms >= 1714521600000")}
for s, tf, t, *v in r.execute(f"SELECT {COLS} FROM candles"):
    if (s, tf, t) in ex:
        comunes += 1
        if [float(a) for a in ex[(s, tf, t)]] != [float(b) for b in v]:
            distintas += 1
print(f"velas en las dos bases: {comunes}; distintas: {distintas}")
if distintas or not comunes:
    sys.exit("NO SE JUNTA: el solape no es identico")
e.close()
r.close()
shutil.copyfile(EXPL, DEST)
d = sqlite3.connect(DEST)
d.execute("ATTACH DATABASE ? AS res", (str(RES),))
antes = d.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
d.execute("INSERT OR IGNORE INTO candles SELECT * FROM res.candles")
d.commit()
despues = d.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
print(f"velas: {antes} -> {despues} (+{despues - antes})")
for fila in d.execute("SELECT timeframe, COUNT(DISTINCT symbol), MIN(ts_open_ms), MAX(ts_open_ms) FROM candles GROUP BY 1"):
    print("  ", fila)
d.close()
