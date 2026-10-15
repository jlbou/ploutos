"""Baja ~1 anyo de velas de 4 h y 1 h de las 8 monedas a una COPIA de la base (propuesta del time-stop).

Hacia ATRAS con /api/v5/market/history-candles (publica): `after` = devuelve las anteriores a esa
marca, 100 por peticion. Asi se sabe tambien desde cuando existe cada par. No toca var/ploutos.db.
"""
import json
import shutil
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from core.config import load_settings  # noqa: E402

AQUI = Path(__file__).parent
DB = AQUI / "historia.db"
if not DB.exists():
    shutil.copy(REPO / "var" / "ploutos.db", DB)
DESDE = 1_754_006_400_000          # 01/08/2025 00:00 UTC
UA = {"User-Agent": "Mozilla/5.0 ploutos-research"}


def pedir(inst, barra, after):
    url = (f"https://eea.okx.com/api/v5/market/history-candles?instId={inst}&bar={barra}&limit=100"
           + (f"&after={after}" if after else ""))
    for intento in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
                d = json.load(r)
            if d.get("code") == "0":
                return d["data"]
            time.sleep(1 + intento)
        except Exception:
            time.sleep(1 + intento)
    raise RuntimeError(f"no hay forma: {url}")


con = sqlite3.connect(DB)
ahora = int(time.time() * 1000)
for simbolo in load_settings().whitelist:
    inst = simbolo.replace("/", "-")
    for tf, barra in (("4h", "4H"), ("1h", "1H")):
        after, n, mas_vieja = None, 0, None
        while True:
            filas = pedir(inst, barra, after)
            if not filas:
                break
            # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]; confirm=1 = cerrada
            buenas = [f for f in filas if f[8] == "1"]
            con.executemany(
                "INSERT OR IGNORE INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close,"
                " volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,1,'rest',?)",
                [(simbolo, tf, int(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[4]),
                  float(f[5]), ahora) for f in buenas])
            n += len(buenas)
            mas_vieja = int(filas[-1][0])
            if mas_vieja <= DESDE:
                break
            after = mas_vieja
            time.sleep(0.12)      # history-candles: 20 peticiones / 2 s
        con.commit()
        c, lo, hi = con.execute("SELECT COUNT(*), MIN(ts_open_ms), MAX(ts_open_ms) FROM candles "
                                "WHERE symbol=? AND timeframe=?", (simbolo, tf)).fetchone()
        dt = lambda ms: time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
        print(f"{simbolo:10s} {tf}: {c:5d} velas, {dt(lo)} -> {dt(hi)}", flush=True)
con.close()
