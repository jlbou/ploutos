"""Baja la RESERVA (la unica vez): velas de 4 h y 1 h de las 8 monedas contra USDT, del 01/05/2024 (calentamiento, ya
de la exploracion) al 20/08/2025 00:00 UTC (exclusivo). Decision del propietario del 09/10: F va a la reserva
(`docs/archivo/diseno-tendencia.md` 00). Igual que `revision-estrategia/bajar_exploracion.py`: API publica de OKX EEA, sin
cuenta ni claves; se guardan con el nombre del par USDC; instrumentos y spread, los de la base de exploracion.

    python bajar_reserva.py <base de salida> <base de exploracion>
"""
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from core.config import load_settings  # noqa: E402
from data.store.db import open_database  # noqa: E402

DESDE = 1_714_521_600_000          # 01/05/2024 00:00 UTC (calentamiento)
HASTA = 1_755_648_000_000          # 20/08/2025 00:00 UTC: de aqui en adelante, nada (empieza la historia USDC)
UA = {"User-Agent": "Mozilla/5.0 ploutos-research"}

salida, exploracion = Path(sys.argv[1]), Path(sys.argv[2])
if salida.exists():
    raise SystemExit(f"{salida} ya existe: no se mezcla con otra")
db = open_database(salida)
db.close()
con = sqlite3.connect(salida)
ex = sqlite3.connect(f"file:{exploracion}?mode=ro", uri=True)
ex.row_factory = sqlite3.Row
for tabla in ("instruments", "book_metrics"):
    filas = [dict(r) for r in ex.execute(f"SELECT * FROM {tabla}")]
    cols = [c for c in filas[0] if c != "id"]
    con.executemany(f"INSERT INTO {tabla} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [tuple(f[c] for c in cols) for f in filas])
con.commit()


def pedir(inst, barra, after):
    url = f"https://eea.okx.com/api/v5/market/history-candles?instId={inst}&bar={barra}&limit=100&after={after}"
    for intento in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                d = json.load(r)
            if d.get("code") == "0":
                return d["data"]
        except Exception:
            pass
        time.sleep(1 + intento)
    raise RuntimeError(f"no hay forma: {url}")


ahora = int(time.time() * 1000)
for simbolo in load_settings().whitelist:
    inst = simbolo.replace("/USDC", "-USDT")
    for tf, barra in (("4h", "4H"), ("1h", "1H")):
        after = HASTA
        while True:
            filas = pedir(inst, barra, after)
            if not filas:
                break
            buenas = [f for f in filas if f[8] == "1" and DESDE <= int(f[0]) < HASTA]
            con.executemany(
                "INSERT OR IGNORE INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close,"
                " volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,1,'rest',?)",
                [(simbolo, tf, int(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[4]),
                  float(f[5]), ahora) for f in buenas])
            mas_vieja = int(filas[-1][0])
            if mas_vieja <= DESDE:
                break
            after = mas_vieja
            time.sleep(0.12)      # history-candles: 20 peticiones / 2 s
        con.commit()
        c, lo, hi = con.execute("SELECT COUNT(*), MIN(ts_open_ms), MAX(ts_open_ms) FROM candles "
                                "WHERE symbol=? AND timeframe=?", (simbolo, tf)).fetchone()
        dt = lambda ms: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"  # noqa: E731
        print(f"{inst:10s} {tf}: {c:6d} velas, {dt(lo)} -> {dt(hi)}", flush=True)
con.close()
print(f"tamanyo: {salida.stat().st_size / 1e6:.1f} MB")
