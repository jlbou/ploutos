"""Baja SOLO el tramo de EXPLORACION de la revision de la estrategia (docs/archivo/propuesta-revision-estrategia.md).

Velas de 4 h y 1 h de las 8 monedas CONTRA USDT, desde el 01/11/2020 (calentamiento) hasta el
30/06/2024 23:59 UTC, a una base NUEVA que no es la del bot. Se guardan con el nombre del par USDC
(`BTC/USDC`...) para que el recorrido del bot (`scripts/replay_baseline.py`) las lea sin cambios:
son precios contra USDT, parecidos a los de USDC (0,05-0,36 % de media, medido el 25/09).

LA RESERVA (01/07/2024 -> 20/08/2025) NO SE BAJA: se pide hacia atras desde el 01/07/2024 y el
script PARA si llegara una sola vela de ese dia o posterior. Se mira una vez, al final.

Instrumentos (tick, lote, minimos) y spread: los del bot, de una copia de su base.

    python bajar_exploracion.py <base de salida> <copia de ploutos.db>
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

DESDE = 1_604_188_800_000          # 01/11/2020 00:00 UTC (calentamiento antes del 02/12/2020)
RESERVA = 1_719_792_000_000        # 01/07/2024 00:00 UTC: de aqui en adelante, NADA
UA = {"User-Agent": "Mozilla/5.0 ploutos-research"}

salida, copia = Path(sys.argv[1]), Path(sys.argv[2])
if salida.exists():
    raise SystemExit(f"{salida} ya existe: no se mezcla con otra")
db = open_database(salida)
db.close()
con = sqlite3.connect(salida)
bot = sqlite3.connect(f"file:{copia}?mode=ro", uri=True)
bot.row_factory = sqlite3.Row
for tabla in ("instruments",):
    filas = [dict(r) for r in bot.execute(f"SELECT * FROM {tabla}")]
    cols = list(filas[0])
    con.executemany(f"INSERT INTO {tabla} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [tuple(f[c] for c in cols) for f in filas])
# El ultimo spread medido de cada moneda: es el que usa el recorrido para todo el periodo.
filas = [dict(r) for r in bot.execute(
    "SELECT * FROM book_metrics b WHERE ts_ms = (SELECT MAX(ts_ms) FROM book_metrics WHERE symbol = b.symbol)")]
cols = list(filas[0])
con.executemany(f"INSERT INTO book_metrics ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
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
        after = RESERVA
        while True:
            filas = pedir(inst, barra, after)
            if not filas:
                break
            if any(int(f[0]) >= RESERVA for f in filas):
                raise SystemExit("PARADO: ha llegado una vela de la RESERVA. No se guarda nada mas.")
            buenas = [f for f in filas if f[8] == "1" and int(f[0]) >= DESDE]
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

maximo = con.execute("SELECT MAX(ts_open_ms) FROM candles").fetchone()[0]
assert maximo < RESERVA, "hay velas de la reserva en la base"
print(f"ultima vela guardada: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(maximo / 1000))} UTC (reserva intacta)")
con.close()
