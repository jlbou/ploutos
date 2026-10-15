"""Las tres candidatas (2 + D, F y H) con las mismas metricas, sobre el mismo periodo (14/12/2020-30/06/2024).

    python comparar.py

Todas con el equity diario (vela de las 20:00) reescalado a 50 $ el 14/12/2020; Sharpe con rendimientos diarios.
Ademas, la correlacion entre sus rendimientos diarios (para saber si combinarlas diversifica). Solo describe.
"""
import json
import math
import statistics
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from tendencia import CAPITAL, INICIO, metricas  # noqa: E402


def cargar(nombre):
    return json.loads((AQUI / nombre).read_text(encoding="utf-8"))


def reescalar(curva):
    c = [(int(d), float(e)) for d, e in curva if int(d) >= INICIO - 86_400_000 * 0]
    base = [e for d, e in curva if int(d) < INICIO]
    e0 = base[-1] if base else CAPITAL
    return [(d, e * CAPITAL / e0) for d, e in c]


d2 = cargar("curva-2d.json")
curvas = {"2 + D": reescalar(d2["curva"]), "F": cargar("F.json")["curva"], "H": cargar("H.json")["curva"],
          "BTC mantenido": None}
curvas["F"] = [(int(d), float(e)) for d, e in curvas["F"]]
curvas["H"] = [(int(d), float(e)) for d, e in curvas["H"]]
btc = cargar("F.json")["btc"]
ops = {"2 + D": d2["todo"]["n"], "F": cargar("F.json")["operaciones"], "H": cargar("H.json")["operaciones"]}

print(f"{'':14} {'50 $ ->':>9} {'rend.':>8} {'caida':>7} {'Sharpe':>7} {'op.':>5}   por anyo")
filas = {}
for k in ("2 + D", "F", "H"):
    m = metricas(curvas[k])
    filas[k] = m
    print(f"{k:14} {m['final']:9.2f} {100 * m['rendimiento']:+7.0f}% {100 * m['caida_max']:6.1f}% "
          f"{m['sharpe_anual']:7.2f} {ops[k]:5}   " + ", ".join(f"{a} {100 * v:+.0f}%" for a, v in m["por_anyo"].items()))
print(f"{'BTC mantenido':14} {btc['final']:9.2f} {100 * btc['rendimiento']:+7.0f}% {100 * btc['caida_max']:6.1f}% "
      f"{btc['sharpe_anual']:7.2f} {1:5}   " + ", ".join(f"{a} {100 * v:+.0f}%" for a, v in btc["por_anyo"].items()))

# Correlacion de los rendimientos diarios, en los dias comunes.
rend = {}
for k in ("2 + D", "F", "H"):
    c = dict(curvas[k])
    dias = sorted(c)
    rend[k] = {dias[i]: c[dias[i]] / c[dias[i - 1]] - 1 for i in range(1, len(dias))}
comunes = sorted(set(rend["2 + D"]) & set(rend["F"]) & set(rend["H"]))
print(f"\ncorrelacion de los rendimientos diarios ({len(comunes)} dias):")
for a, b in (("2 + D", "F"), ("2 + D", "H"), ("F", "H")):
    x, y = [rend[a][d] for d in comunes], [rend[b][d] for d in comunes]
    print(f"  {a} y {b}: {statistics.correlation(x, y):+.2f}")
print(f"\n(Sharpe anual = medio / desviacion diarios x raiz de 365 = {math.sqrt(365):.1f})")
