"""La robustez de L (`robustez-l.md`, plan fijado el 10/10 antes de medir). Solo informacion.

    python robustez_l.py > robustez-l.txt

Corre L y sus 12 variantes en la exploracion ampliada y en el anyo USDC (4 a la vez), valida que L sin cambios da
EXACTO `L-ampliada.json` y `L-usdc.json`, y resume. Guarda cada medicion en `robustez/` (metricas y curva).
"""
import json
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[2]
TRAMO_RESERVA = int(datetime(2024, 7, 1, tzinfo=UTC).timestamp() * 1000)     # como `segunda_tanda.py`


def anyo(met, a):
    return met["por_anyo"].get(a, met["por_anyo"].get(str(a), 0.0))


SALIDA = AQUI / "robustez"
PERIODOS = {
    "exploracion": ["--base", str(REPO / "var/estudios/exploracion-ampliada.db")],
    "anyo-usdc": ["--base", str(REPO / "var/estudios/anyo-usdc-calentado.db"), "--desde", "2025-09-01",
                  "--hasta", "2026-09-28"],
}
REFERENCIA = {"exploracion": "L-ampliada.json", "anyo-usdc": "L-usdc.json"}
DIAS = ["martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
VARIANTES = {"L": []}
VARIANTES |= {f"dia {d}": ["--dia-rotacion", str(i + 1)] for i, d in enumerate(DIAS)}
VARIANTES |= {f"plazos x{f}": ["--plazos", p] for f, p in (("0,8", "16,40,80,160"), ("0,9", "18,45,90,180"),
                                                            ("1,1", "22,55,110,220"), ("1,25", "25,63,125,250"))}
VARIANTES |= {"BTC >= 1": ["--btc-min", "1"], "BTC >= 3": ["--btc-min", "3"]}


def medir(periodo, nombre):
    r = subprocess.run([sys.executable, str(AQUI / "tendencia.py"), "medir", "L", *PERIODOS[periodo],
                        *VARIANTES[nombre]], capture_output=True, text=True, cwd=AQUI, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"{periodo} {nombre}: {r.stderr[-1500:]}")
    return periodo, nombre, json.loads(r.stdout)


def tramo(curva):
    c = {int(d): float(e) for d, e in curva}
    dias = sorted(c)
    antes = [d for d in dias if d < TRAMO_RESERVA]
    return c[dias[-1]] / c[antes[-1]] - 1


def condiciones(x):
    met, btc = x["metricas"], x["btc"]
    return {
        "1": met["rendimiento"] > 0,
        "2": met["caida_max"] <= 2 / 3 * btc["caida_max"],
        "3": met["sharpe_anual"] >= btc["sharpe_anual"],
        "4": -anyo(met, 2022) <= -anyo(btc, 2022) / 3,
        "5": tramo(x["curva"]) > 0,
    }


def main():
    SALIDA.mkdir(exist_ok=True)
    trabajos = [(p, n) for p in PERIODOS for n in VARIANTES]
    with ThreadPoolExecutor(max_workers=4) as pool:
        res = {(p, n): x for p, n, x in pool.map(lambda pn: medir(*pn), trabajos)}
    for (p, n), x in res.items():
        nombre = n.replace(" ", "_").replace(">=", "min").replace(",", "")
        (SALIDA / f"{p}-{nombre}.json").write_text(json.dumps(
            {k: x[k] for k in ("variante", "metricas", "btc", "operaciones", "por_motivo", "tiempo_invertido",
                               "comisiones", "curva")}, default=str), encoding="utf-8")

    print(f"Robustez de L ({datetime.now(UTC):%d/%m/%Y %H:%M} UTC). Solo informacion: ninguna variante sustituye a L.")
    ok = True
    for p, ref in REFERENCIA.items():
        r = json.loads((AQUI / ref).read_text(encoding="utf-8"))
        igual = res[(p, "L")]["curva"] == r["curva"] and res[(p, "L")]["ops"] == r["ops"]
        ok &= igual
        print(f"validacion {p}: L sin cambios {'IGUAL' if igual else 'DISTINTO'} a {ref}")
    if not ok:
        print("VALIDACION NO PASA: no se lee nada")
        return 1

    print("\n== Exploracion ampliada (14/12/2020 - 20/08/2025)")
    print(f"{'':16} {'50 $ ->':>9} {'caida':>7} {'Sharpe':>7} {'2022':>7} {'tramo':>7} {'op.':>5}  1-5")
    pasan, sharpes = 0, []
    for n in VARIANTES:
        x = res[("exploracion", n)]
        met, c = x["metricas"], condiciones(x)
        if n != "L":
            pasan += all(c.values())
            sharpes.append(met["sharpe_anual"])
        fallos = ",".join(k for k, v in c.items() if not v)
        print(f"{n:16} {met['final']:9.2f} {100 * met['caida_max']:6.1f}% {met['sharpe_anual']:7.2f} "
              f"{100 * anyo(met, 2022):+6.1f}% {100 * tramo(x['curva']):+6.1f}% {x['operaciones']:5}  "
              f"{'pasa' if not fallos else 'falla ' + fallos}")
    sl = res[("exploracion", "L")]["metricas"]["sharpe_anual"]
    mediana = statistics.median(sharpes)
    print(f"pasan 1-5: {pasan} de 12; Sharpe de L {sl:.2f}; mediana de las 12 {mediana:.2f} "
          f"({100 * mediana / sl:.0f} % del de L); L queda por encima de {sum(s < sl for s in sharpes)} de 12")

    print("\n== Anyo USDC (01/09/2025 - 27/09/2026), se ensenya, no puntua")
    btc = res[("anyo-usdc", "L")]["btc"]
    print(f"BTC mantenido {100 * btc['rendimiento']:+.1f} %, caida {100 * btc['caida_max']:.1f} %")
    pierden = 0
    for n in VARIANTES:
        met = res[("anyo-usdc", n)]["metricas"]
        if n != "L":
            pierden += met["rendimiento"] < 0
        print(f"{n:16} {100 * met['rendimiento']:+6.1f}%  caida {100 * met['caida_max']:5.1f}%  "
              f"{res[('anyo-usdc', n)]['operaciones']:3} op.")
    print(f"pierden: {pierden} de 12")

    solida = pasan >= 9 and mediana >= 0.8 * sl
    print(f"\nLECTURA (fijada antes): L es {'SOLIDA' if solida else 'FRAGIL'} "
          f"(pasan {pasan} de 12, hace falta 9; mediana del Sharpe {100 * mediana / sl:.0f} % del de L, hace falta 80 %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
