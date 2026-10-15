"""La base del anyo USDC con el calentamiento en USDT (`docs/archivo/diseno-tendencia-2.md` 00, el propietario, 10/10).

    python base_anyo_usdc.py      # -> var/estudios/anyo-usdc-calentado.db

Copia `time-stop/historia.db` (USDC desde el 21/08/2025) y le anyade, solo para calentar los indicadores, las velas
de 1 h y 4 h USDT de la exploracion ampliada desde el 01/12/2024 hasta la primera vela USDC. Las velas USDC no se
tocan (se comprueba). Instrumentos y spread, los de USDC.
"""
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
USDC = REPO / "docs/estudios/time-stop/historia.db"
AMPL = REPO / "var/estudios/exploracion-ampliada.db"
DEST = REPO / "var/estudios/anyo-usdc-calentado.db"
DESDE = int(datetime(2024, 12, 1, tzinfo=UTC).timestamp() * 1000)

if DEST.exists():
    sys.exit(f"{DEST} ya existe: no se pisa")
src = sqlite3.connect(f"file:{USDC}?mode=ro", uri=True)
primera = src.execute("SELECT MIN(ts_open_ms) FROM candles WHERE timeframe IN ('1h','4h')").fetchone()[0]
huella = src.execute("SELECT COUNT(*), SUM(close), SUM(volume) FROM candles").fetchone()
src.close()
d = sqlite3.connect(DEST)
s2 = sqlite3.connect(f"file:{USDC}?mode=ro", uri=True)
s2.backup(d)
s2.close()
d.execute("ATTACH DATABASE ? AS ampl", (str(AMPL),))
d.execute("INSERT INTO candles SELECT * FROM ampl.candles WHERE timeframe IN ('1h','4h') AND ts_open_ms >= ? "
          "AND ts_open_ms < ?", (DESDE, primera))
d.commit()
d.execute("DETACH DATABASE ampl")
usdc = d.execute("SELECT COUNT(*), SUM(close), SUM(volume) FROM candles WHERE ts_open_ms >= ? OR timeframe NOT IN "
                 "('1h','4h')", (primera,)).fetchone()
print(f"primera vela USDC: {datetime.fromtimestamp(primera / 1000, UTC)}; las USDC, intactas: {tuple(usdc) == tuple(huella)}")
for fila in d.execute("SELECT timeframe, COUNT(DISTINCT symbol), COUNT(*), MIN(ts_open_ms), MAX(ts_open_ms) FROM candles "
                      "WHERE timeframe IN ('1h','4h') GROUP BY 1"):
    print("  ", fila)
d.close()
