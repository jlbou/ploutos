"""Comprobacion de solo lectura (07/10): con la cartera de la IA llena, habria salido algun candidato en sombra?

Para cada (vela, moneda) que la cartera de la IA descarto SOLO por "3/3 huecos ocupados" desde el 02/10 12:00, se
vuelve a pasar el generador de candidatos con las velas cerradas hasta esa vela (lo mismo que hace la sombra: la
criba con el tope abierto pasa, porque el hueco era el unico rechazo). Para validar el montaje, se hace lo mismo
con las monedas que SI pasaron la criba de verdad: tiene que reproducir los candidatos y los "sin senyal" apuntados.
Abre las bases en mode=ro: no escribe nada. Se corre en el VPS:

    cd /opt/ploutos && sudo -u ploutos .venv/bin/python docs/estudios/candidatos-sombra/comprobar_vivo.py
"""
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime

import pandas as pd

sys.path.insert(0, "/opt/ploutos")
from core.config import load_settings  # noqa: E402
from risk.limits import Limits  # noqa: E402
from strategy.candidates import generate_for_symbol  # noqa: E402
from strategy.costs import CostModel  # noqa: E402

TF, PASO, HISTORY_BARS = "4h", 4 * 3600_000, 200
DESDE = int(datetime(2026, 10, 2, 12, 0, tzinfo=UTC).timestamp() * 1000)

settings = load_settings()
main = sqlite3.connect("file:/opt/ploutos/var/ploutos.db?mode=ro", uri=True)
main.row_factory = sqlite3.Row
ai = sqlite3.connect("file:/opt/ploutos/var/ploutos-paper-ai.db?mode=ro", uri=True)

rows = settings.exchange.fees.apply([dict(r) for r in main.execute("SELECT * FROM instruments")])
cost = CostModel.from_repo(type("R", (), {"all": lambda _s: rows})(), now_ms=max(r["fetched_ms"] for r in rows))


def t(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%d/%m %H:%M")


def historia(symbol, stamp):
    filas = main.execute(
        "SELECT * FROM (SELECT * FROM candles WHERE symbol=? AND timeframe=? AND closed=1 AND ts_open_ms<=? "
        "ORDER BY ts_open_ms DESC LIMIT ?) ORDER BY ts_open_ms", (symbol, TF, stamp, HISTORY_BARS)).fetchall()
    return pd.DataFrame([dict(r) for r in filas])


def spread(symbol, stamp):
    # La lectura del libro mas reciente al cerrar la vela (el bucle usa la ultima que hay al procesar).
    r = main.execute("SELECT spread_pct FROM book_metrics WHERE symbol=? AND ts_ms<=? ORDER BY ts_ms DESC LIMIT 1",
                     (symbol, stamp + PASO + 60_000)).fetchone()
    return float(r["spread_pct"]) if r else 99.0


def equity(stamp):
    r = ai.execute("SELECT equity_usd FROM paper_equity WHERE ts_ms<=? ORDER BY ts_ms DESC LIMIT 1", (stamp,)).fetchone()
    return float(r[0]) if r else 50.0


def generar(symbol, stamp):
    velas = historia(symbol, stamp)
    if velas.empty or int(velas["ts_open_ms"].iloc[-1]) != stamp:
        return None
    limits = Limits.for_state(settings, equity(stamp), 3)
    now = datetime.fromtimestamp((stamp + PASO) / 1000, UTC)
    return generate_for_symbol(symbol, TF, velas, spread(symbol, stamp), cost, limits, settings, now=now)


decisiones = ai.execute("SELECT ts_ms, symbol, kind, detail FROM paper_decisions WHERE ts_ms>=? ORDER BY ts_ms",
                        (DESDE,)).fetchall()

# --- 1. Validacion: lo que paso la criba de verdad tiene que salir igual ---
apuntados = {(ts, s) for ts, s, k, _ in decisiones if k == "candidate"}
sin_senyal = {(ts, s) for ts, s, k, _ in decisiones if k == "sin_senyal"}
coinciden = fallan = 0
for ts, s in sorted(apuntados | sin_senyal):
    g = generar(s, ts)
    hay = bool(g and g.candidates)
    esperado = (ts, s) in apuntados
    if hay == esperado:
        coinciden += 1
    else:
        fallan += 1
        print(f"  VALIDACION NO COINCIDE: {t(ts)} {s} apuntado={'candidato' if esperado else 'sin senyal'} "
              f"recalculado={'candidato' if hay else 'nada'}")
print(f"1. Validacion: {coinciden} de {coinciden + fallan} coinciden con lo apuntado en vivo "
      f"({len(apuntados)} candidatos, {len(sin_senyal)} sin senyal)")

# --- 2. La sombra: solo por llena ---
solo_llena = [(ts, s) for ts, s, k, d in decisiones
              if k == "filtered" and d and d.startswith("hueco libre:") and "huecos ocupados" in d and ";" not in d]
print(f"\n2. Casos descartados SOLO por cartera llena: {len(solo_llena)} "
      f"en {len({ts for ts, _ in solo_llena})} velas")
motivos = Counter()
salen = []
for ts, s in solo_llena:
    g = generar(s, ts)
    if g is None:
        motivos["sin la vela de esa hora"] += 1
        continue
    if g.candidates:
        salen.append((ts, s, [c.setup for c in g.candidates]))
        continue
    for r in g.rejections:
        motivos[f"{r.setup} / {r.gate}"] += 1
print(f"   habrian dado candidato en sombra: {len(salen)}")
for ts, s, setups in salen:
    print(f"     {t(ts)} {s} {setups}")
print("   por que no salio nada (rechazos del generador, uno por setup y moneda):")
for k, v in motivos.most_common():
    print(f"     {v:3} {k}")
