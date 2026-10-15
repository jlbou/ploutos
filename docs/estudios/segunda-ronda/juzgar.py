"""Aplica el criterio de C y D (fijado ANTES de medir: `docs/archivo/plan-segunda-ronda-estrategia.md`) a los resultados.

    python juzgar.py resultados/

Para cada contabilidad (maker y taker):
- C (cada variante): IC 90 % de la diferencia de R medio por operacion (idea menos referencia) con bootstrap
  EMPAREJADO por dias, >= 100 operaciones y diferencia positiva en al menos 3 de los 4 anyos.
- D: IC 90 % del R medio (el de `medir.py`) entero por encima de +0,13, >= 100 operaciones y R medio > 0 en al
  menos 3 de los 4 anyos.
Una idea pasa solo si pasa en LAS DOS contabilidades.
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ITER = 10_000
ANYOS = ("2021", "2022", "2023", "2024")
LISTON_D = 0.13
carpeta = Path(sys.argv[1])


def cargar(nombre):
    return json.loads((carpeta / f"{nombre}.json").read_text(encoding="utf-8"))


def por_dia(res):
    d = defaultdict(list)
    for dia, r in res["operaciones"]:
        d[dia].append(r)
    return d


def media(xs):
    return sum(xs) / len(xs) if xs else 0.0


def diferencia_emparejada(idea, ref, semilla=20261007):
    """IC 90 % de media(R idea) - media(R ref), remuestreando los MISMOS dias para las dos."""
    rnd = random.Random(semilla)
    a, b = por_dia(idea), por_dia(ref)
    dias = sorted(set(a) | set(b))
    difs = []
    for _ in range(ITER):
        muestra = rnd.choices(dias, k=len(dias))
        ra = [r for d in muestra for r in a.get(d, ())]
        rb = [r for d in muestra for r in b.get(d, ())]
        difs.append(media(ra) - media(rb))
    difs.sort()
    total = media([r for _d, r in idea["operaciones"]]) - media([r for _d, r in ref["operaciones"]])
    return total, difs[int(0.05 * ITER)], difs[int(0.95 * ITER)]


def anyo(res, a):
    x = res["por_anyo"].get(a, {"n": 0})
    return x.get("r_medio", 0.0) if x["n"] else None


resumen = {}
for objetivo in ("maker", "taker"):
    ref = cargar(f"referencia-{objetivo}")
    print(f"\n=== objetivo {objetivo}: referencia {ref['todo']['n']} op., R {ref['todo']['r_medio']:+.3f} "
          f"(IC {ref['todo']['ic90'][0]:+.3f} a {ref['todo']['ic90'][1]:+.3f})")
    for variante in ("C-siempre", "C-sin-avance"):
        res = cargar(f"{variante}-{objetivo}")
        dif, lo, hi = diferencia_emparejada(res, ref)
        difs_anyo = {a: (anyo(res, a) or 0.0) - (anyo(ref, a) or 0.0) for a in ANYOS}
        positivos = sum(v > 0 for v in difs_anyo.values())
        pasa = lo > 0 and res["todo"]["n"] >= 100 and positivos >= 3
        resumen.setdefault(variante, []).append(pasa)
        print(f"{variante:13} {res['todo']['n']} op., R {res['todo']['r_medio']:+.3f}; diferencia {dif:+.3f} "
              f"(IC {lo:+.3f} a {hi:+.3f}); por anyo " + ", ".join(f"{a} {v:+.2f}" for a, v in difs_anyo.items())
              + f" ({positivos}/4); cortadas {res['time_stop']['cortadas']} a {res['time_stop']['r_medio_cortadas']}"
              f" R; equity {res['equity'].replace('equity', '').strip()}; {'PASA' if pasa else 'no pasa'}")
    res = cargar(f"D-{objetivo}")
    lo, hi = res["todo"]["ic90"]
    anyos = {a: anyo(res, a) for a in ANYOS}
    positivos = sum((v or 0) > 0 for v in anyos.values())
    pasa = lo > LISTON_D and res["todo"]["n"] >= 100 and positivos >= 3
    resumen.setdefault("D", []).append(pasa)
    dif, dlo, dhi = diferencia_emparejada(res, ref)
    print(f"{'D':13} {res['todo']['n']} op., R {res['todo']['r_medio']:+.3f} (IC {lo:+.3f} a {hi:+.3f}); por anyo "
          + ", ".join(f"{a} {(v or 0):+.2f}" for a, v in anyos.items()) + f" ({positivos}/4); "
          f"equity {res['equity'].replace('equity', '').strip()}; caida {res['drawdown'].replace('drawdown maximo', '').strip()}; {'PASA' if pasa else 'no pasa'}"
          f"  [informativo: diferencia con la referencia {dif:+.3f}, IC {dlo:+.3f} a {dhi:+.3f}]")

print("\n=== VEREDICTO (tiene que pasar en las dos contabilidades)")
for k, v in resumen.items():
    print(f"{k:13} {'PASA' if all(v) else 'NO PASA'}  (maker {'si' if v[0] else 'no'}, taker {'si' if v[1] else 'no'})")
