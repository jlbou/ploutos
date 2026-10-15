"""El juez de la segunda tanda de tendencia (`docs/archivo/diseno-tendencia-2.md`, aprobada por el propietario el 10/10 antes de medir).

    python segunda_tanda.py > veredicto-segunda-tanda.txt

Lee las cinco variantes en la exploracion ampliada (14/12/2020 - 20/08/2025): H, K y L (`tendencia.py medir ...
--base var/estudios/exploracion-ampliada.db`), 2 + D (`curva_2d.py var/estudios/exploracion-ampliada.db`) y M (mitad K,
mitad 2 + D: las dos curvas sumadas a la mitad, la aproximacion de J).

Condiciones (cada variante): 1 gana dinero; 2 caida <= 2/3 de la de BTC mantenido; 3 Sharpe >= el de BTC; 4 en 2022
pierde <= 1/3 de lo de BTC; 5 en el tramo de la reserva (07/2024 - 08/2025) gana dinero. El Sharpe deflactado
(N = 10, la V de `umbral.json`) NO elimina (opcion b del propietario): de las que pasan 1-5, va al anyo USDC la de mayor
deflactado. Si no pasa ninguna, no se retoca nada.
"""
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from tendencia import CAPITAL, INICIO, dsr, metricas  # noqa: E402

N = 10                      # la familia (6), J y K, L y M
GAMMA = 0.5772156649
TRAMO_RESERVA = int(datetime(2024, 7, 1, tzinfo=UTC).timestamp() * 1000)


def cargar(nombre):
    return json.loads((AQUI / nombre).read_text(encoding="utf-8"))


def reescalada(curva):
    antes = [e for d, e in curva if int(d) < INICIO]
    e0 = antes[-1] if antes else CAPITAL
    return {int(d): float(e) * CAPITAL / e0 for d, e in curva if int(d) >= INICIO}


def tramo(curva: dict[int, float]):
    dias = sorted(curva)
    antes = [d for d in dias if d < TRAMO_RESERVA]
    return curva[dias[-1]] / curva[antes[-1]] - 1


def anyo(met, a):
    return met["por_anyo"].get(a, met["por_anyo"].get(str(a), 0.0))


k_json, h_json, l_json = cargar("K-ampliada.json"), cargar("H-ampliada.json"), cargar("L-ampliada.json")
d2 = cargar("curva-2d-ampliada.json")
curvas = {
    "H": {int(d): float(e) for d, e in h_json["curva"]},
    "2 + D": reescalada(d2["curva"]),
    "K": {int(d): float(e) for d, e in k_json["curva"]},
    "L": {int(d): float(e) for d, e in l_json["curva"]},
}
comunes = sorted(set(curvas["K"]) & set(curvas["2 + D"]))
curvas["M"] = {d: (curvas["K"][d] + curvas["2 + D"][d]) / 2 for d in comunes}
operaciones = {"H": h_json["operaciones"], "K": k_json["operaciones"], "L": l_json["operaciones"],
               "2 + D": d2["todo"].get("n") if isinstance(d2.get("todo"), dict) else None}
operaciones["M"] = None if operaciones["2 + D"] is None else operaciones["K"] + operaciones["2 + D"]

btc = k_json["btc"]
v = cargar("umbral.json")["DECIDIDO"]["V_sharpe_diario"]
z = statistics.NormalDist().inv_cdf
sr0 = math.sqrt(v) * ((1 - GAMMA) * z(1 - 1 / N) + GAMMA * z(1 - 1 / (N * math.e)))

print(f"Exploracion ampliada, {len(curvas['K'])} dias (14/12/2020 - 20/08/2025). Sharpe por suerte con N = {N}: "
      f"{sr0 * math.sqrt(365):.2f} al anyo (solo para elegir, opcion b)")
print(f"BTC mantenido: 50 $ -> {btc['final']:.2f} $ ({100 * btc['rendimiento']:+.1f} %), caida max "
      f"{100 * btc['caida_max']:.1f} % (2/3 = {200 / 3 * btc['caida_max']:.1f} %), Sharpe {btc['sharpe_anual']:.2f}, "
      f"2022 {100 * anyo(btc, 2022):+.1f} %; BTC + ETH {100 * k_json['btc_eth']['rendimiento']:+.1f} %")
resultados = []
for nombre, curva in curvas.items():
    serie = sorted(curva.items())
    met = metricas(serie)
    d = dsr(met, sr0)
    r_tramo = tramo(curva)
    cond = {
        "1. gana dinero": met["rendimiento"] > 0,
        "2. caida <= 2/3 de la de BTC": met["caida_max"] <= 2 / 3 * btc["caida_max"],
        "3. Sharpe >= el de BTC": met["sharpe_anual"] >= btc["sharpe_anual"],
        "4. en 2022 pierde <= 1/3 de BTC": -anyo(met, 2022) <= -anyo(btc, 2022) / 3,
        "5. gana en el tramo de la reserva (07/2024-08/2025)": r_tramo > 0,
    }
    pasa = all(cond.values())
    resultados.append((nombre, pasa, d))
    ops = operaciones.get(nombre)
    print(f"\n=== {nombre}: 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), caida max "
          f"{100 * met['caida_max']:.1f} %, Sharpe {met['sharpe_anual']:.2f}"
          + (f", {ops} operaciones" if ops is not None else ""))
    print("    por anyo (estrategia / BTC): " + ", ".join(
        f"{a} {100 * x:+.1f} % / {100 * anyo(btc, a):+.1f} %" for a, x in met["por_anyo"].items()))
    print(f"    tramo de la reserva: {100 * r_tramo:+.1f} %")
    print(f"    Sharpe deflactado {d:.3f} (para elegir)")
    for k, ok in cond.items():
        print(f"    {'si' if ok else 'NO'}  {k}")
    print(f"    -> {'PASA' if pasa else 'NO PASA'}")

pasan = [r for r in resultados if r[1]]
if pasan:
    elegida = max(pasan, key=lambda r: r[2])
    print(f"\nPASAN: {', '.join(r[0] for r in pasan)}. VA AL ANYO USDC: {elegida[0]} (la de mayor Sharpe deflactado, "
          f"{elegida[2]:.3f}); las demas se miden alli como informacion.")
else:
    print("\nNO PASA NINGUNA: no se retoca nada y no va ninguna al anyo USDC.")
