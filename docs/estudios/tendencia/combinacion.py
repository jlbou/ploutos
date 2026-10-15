"""La combinacion J (el propietario, 09/10): un tercio del capital a 2 + D, F y H, sin rebalancear. Criterio fijado antes de
calcularla: `docs/archivo/diseno-tendencia.md` seccion 0 (las 5 condiciones; en la 5, N = 7 con la V de `umbral.json`).

    python combinacion.py > J.txt

Aproximacion: cada parte se midio con 50 $; aqui se suman sus curvas a un tercio (las reglas que no escalan y el
limite de 3 posiciones en total no se aplican a la combinacion).
"""
import json
import math
import statistics
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from tendencia import CAPITAL, INICIO, dsr, metricas  # noqa: E402

N = 7
GAMMA = 0.5772156649


def cargar(nombre):
    return json.loads((AQUI / nombre).read_text(encoding="utf-8"))


def reescalada(curva):
    antes = [e for d, e in curva if int(d) < INICIO]
    e0 = antes[-1] if antes else CAPITAL
    return {int(d): float(e) * CAPITAL / e0 for d, e in curva if int(d) >= INICIO}


partes = {"2 + D": reescalada(cargar("curva-2d.json")["curva"]),
          "F": {int(d): float(e) for d, e in cargar("F.json")["curva"]},
          "H": {int(d): float(e) for d, e in cargar("H.json")["curva"]}}
dias = sorted(set.intersection(*(set(p) for p in partes.values())))
curva = [(d, sum(p[d] for p in partes.values()) / 3) for d in dias]
met = metricas(curva)
btc = cargar("F.json")["btc"]

v = cargar("umbral.json")["DECIDIDO"]["V_sharpe_diario"]
z = statistics.NormalDist().inv_cdf
sr0 = math.sqrt(v) * ((1 - GAMMA) * z(1 - 1 / N) + GAMMA * z(1 - 1 / (N * math.e)))
d = dsr(met, sr0)
cond = {
    "1. gana dinero": met["rendimiento"] > 0,
    "2. caida <= 2/3 de la de BTC": met["caida_max"] <= 2 / 3 * btc["caida_max"],
    "3. Sharpe >= el de BTC": met["sharpe_anual"] >= btc["sharpe_anual"],
    "4. en 2022 pierde <= 1/3 de BTC": -met["por_anyo"].get(2022, 0.0) <= -btc["por_anyo"]["2022"] / 3,
    "5. Sharpe deflactado >= 0,95": d >= 0.95,
}
print(f"J (un tercio a 2 + D, F y H; {len(dias)} dias): 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), "
      f"caida max {100 * met['caida_max']:.1f} %, Sharpe {met['sharpe_anual']:.2f}")
print("  por anyo (J / BTC): " + ", ".join(f"{a} {100 * x:+.1f} % / {100 * btc['por_anyo'].get(str(a), 0):+.1f} %"
                                        for a, x in met["por_anyo"].items()))
print(f"  BTC mantenido: 50 $ -> {btc['final']:.2f} $, caida {100 * btc['caida_max']:.1f} %, Sharpe {btc['sharpe_anual']:.2f}")
print(f"  Sharpe deflactado {d:.3f} (N = {N}, Sharpe por suerte {sr0 * math.sqrt(365):.2f} al anyo)")
for k, ok in cond.items():
    print(f"  {'si' if ok else 'NO'}  {k}")
print(f"VEREDICTO J: {'PASA la exploracion (lo que mandaria: la reserva y el anyo USDC)' if all(cond.values()) else 'NO PASA'}")
