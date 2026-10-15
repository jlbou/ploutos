"""El juez del anyo USDC de la segunda tanda (`docs/archivo/diseno-tendencia-2.md` 00, el propietario, 10/10, antes de mirar ese anyo).

    python anyo_usdc.py > veredicto-anyo-usdc.txt

Del lunes 01/09/2025 al 28/09/2026, con los indicadores calentados en USDT (`base_anyo_usdc.py`). Cuentan L y M:
pasa L -> L; L no y M si -> M (prueba algo mas floja); ninguna -> no se retoca. H, 2 + D y K, solo informacion.
Pasa si: rendimiento >= 0 Y caida maxima <= 2/3 de la de BTC mantenido en el mismo periodo.
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from tendencia import CAPITAL, metricas  # noqa: E402

INICIO = int(datetime(2025, 9, 1, tzinfo=UTC).timestamp() * 1000)


def cargar(nombre):
    return json.loads((AQUI / nombre).read_text(encoding="utf-8"))


def reescalada(curva):
    antes = [e for d, e in curva if int(d) < INICIO]
    e0 = antes[-1] if antes else CAPITAL
    return {int(d): float(e) * CAPITAL / e0 for d, e in curva if int(d) >= INICIO}


l_json, k_json, h_json, d2 = (cargar("L-usdc.json"), cargar("K-usdc.json"), cargar("H-usdc.json"),
                              cargar("curva-2d-usdc.json"))
curvas = {
    "L": {int(d): float(e) for d, e in l_json["curva"]},
    "K": {int(d): float(e) for d, e in k_json["curva"]},
    "H": {int(d): float(e) for d, e in h_json["curva"]},
    "2 + D": reescalada(d2["curva"]),
}
comunes = sorted(set(curvas["K"]) & set(curvas["2 + D"]))
curvas["M"] = {d: (curvas["K"][d] + curvas["2 + D"][d]) / 2 for d in comunes}
ops = {"L": l_json["operaciones"], "K": k_json["operaciones"], "H": h_json["operaciones"], "2 + D": d2["todo"]["n"]}
ops["M"] = ops["K"] + ops["2 + D"]
btc = l_json["btc"]
dia = lambda t: datetime.fromtimestamp(t / 1000, UTC).date()  # noqa: E731

print(f"Anyo USDC, {dia(min(curvas['L']))} - {dia(max(curvas['L']))} ({len(curvas['L'])} dias)")
print(f"BTC mantenido: 50 $ -> {btc['final']:.2f} $ ({100 * btc['rendimiento']:+.1f} %), caida max "
      f"{100 * btc['caida_max']:.1f} % (2/3 = {200 / 3 * btc['caida_max']:.1f} %), Sharpe {btc['sharpe_anual']:.2f}; "
      f"BTC + ETH {100 * l_json['btc_eth']['rendimiento']:+.1f} %")
pasa = {}
for nombre in ("L", "M", "H", "2 + D", "K"):
    met = metricas(sorted(curvas[nombre].items()))
    gana = met["rendimiento"] >= 0
    cae = met["caida_max"] <= 2 / 3 * btc["caida_max"]
    pasa[nombre] = gana and cae
    papel = "CUENTA" if nombre in ("L", "M") else "informacion"
    print(f"\n=== {nombre} ({papel}): 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), caida max "
          f"{100 * met['caida_max']:.1f} %, Sharpe {met['sharpe_anual']:.2f}, {ops[nombre]} operaciones")
    print(f"    {'si' if gana else 'NO'}  no pierde (>= 0)")
    print(f"    {'si' if cae else 'NO'}  caida <= 2/3 de la de BTC")
    print(f"    -> {'PASA' if pasa[nombre] else 'NO PASA'}")

if pasa["L"]:
    print("\nVEREDICTO: PASA L. L es la estrategia.")
elif pasa["M"]:
    print("\nVEREDICTO: L no pasa y M si. M es la estrategia, con una prueba algo mas floja (se probaron dos).")
else:
    print("\nVEREDICTO: NO PASA NINGUNA de las dos. No se retoca nada.")
