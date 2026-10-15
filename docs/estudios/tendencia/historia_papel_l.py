"""La historia del papel de L (`docs/diseno-papel-l.md`): la base del anyo USDC calentada, reducida a lo que usa L.

    python historia_papel_l.py      # -> var/papel-l/historia.db (se sube una vez al VPS, a /opt/ploutos/var/papel-l/)

Solo velas de 1 h y 4 h, los instrumentos y la ULTIMA medida de spread de cada moneda (la que lee el simulador).
"""
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ORIGEN = REPO / "var/estudios/anyo-usdc-calentado.db"
DEST = REPO / "var/papel-l/historia.db"

if DEST.exists():
    sys.exit(f"{DEST} ya existe: no se pisa")
DEST.parent.mkdir(parents=True, exist_ok=True)
o = sqlite3.connect(f"file:{ORIGEN}?mode=ro", uri=True)
d = sqlite3.connect(DEST)
for (sql,) in o.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name IN "
                        "('candles', 'instruments', 'book_metrics')"):
    d.execute(sql)
d.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              o.execute("SELECT * FROM candles WHERE timeframe IN ('1h', '4h')"))
d.executemany("INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", o.execute("SELECT * FROM instruments"))
d.executemany("INSERT INTO book_metrics VALUES (?,?,?,?,?,?,?,?,?,?)",
              o.execute("SELECT b.* FROM book_metrics b JOIN (SELECT symbol, MAX(ts_ms) m FROM book_metrics "
                        "GROUP BY symbol) u ON b.symbol = u.symbol AND b.ts_ms = u.m"))
d.commit()
d.execute("VACUUM")
print(d.execute("SELECT timeframe, COUNT(*), MIN(ts_open_ms), MAX(ts_open_ms) FROM candles GROUP BY 1").fetchall())
print(d.execute("SELECT symbol, spread_pct FROM book_metrics").fetchall())
d.close()
