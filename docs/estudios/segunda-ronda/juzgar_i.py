"""Aplica el criterio de la idea I (aprobado por el propietario el 09/10, antes de medir: `docs/archivo/plan-segunda-ronda-estrategia.md`).

    python juzgar_i.py resultados/

Sobre 2 + D, en cada contabilidad (maker y taker): IC 90 % de la diferencia de R por operacion (con la regla menos
sin ella), emparejada por dias como en la C (la misma funcion que `juzgar.py`), entero por encima de 0; y la
diferencia de R medio positiva en al menos 3 de los anyos con >= 20 operaciones en las dos. Pasa solo si pasa en las
dos contabilidades. Sobre la referencia, solo informativo.
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ITER = 10_000
MIN_ANYO = 20
carpeta = Path(sys.argv[1])


def cargar(n):
    return json.loads((carpeta / f"{n}.json").read_text(encoding="utf-8"))


def media(xs):
    return sum(xs) / len(xs) if xs else 0.0


def diferencia_emparejada(idea, ref, semilla=20261007):
    """Igual que `juzgar.py`: remuestrea los MISMOS dias para las dos."""
    rnd = random.Random(semilla)
    a, b = defaultdict(list), defaultdict(list)
    for d, r in idea["operaciones"]:
        a[d].append(r)
    for d, r in ref["operaciones"]:
        b[d].append(r)
    dias = sorted(set(a) | set(b))
    difs = []
    for _ in range(ITER):
        muestra = rnd.choices(dias, k=len(dias))
        difs.append(media([r for d in muestra for r in a.get(d, ())]) - media([r for d in muestra for r in b.get(d, ())]))
    difs.sort()
    total = media([r for _d, r in idea["operaciones"]]) - media([r for _d, r in ref["operaciones"]])
    return total, difs[int(0.05 * ITER)], difs[int(0.95 * ITER)]


veredictos = []
for objetivo in ("maker", "taker"):
    for con, sin, cuenta in ((f"2+D+I-{objetivo}", f"2+D-{objetivo}", True),
                             (f"ref+I-{objetivo}", f"referencia-{objetivo}", False)):
        a, b = cargar(con), cargar(sin)
        dif, lo, hi = diferencia_emparejada(a, b)
        anyos = sorted(k for k in a["por_anyo"] if k in b["por_anyo"]
                       and a["por_anyo"][k]["n"] >= MIN_ANYO and b["por_anyo"][k]["n"] >= MIN_ANYO)
        difs = {k: a["por_anyo"][k]["r_medio"] - b["por_anyo"][k]["r_medio"] for k in anyos}
        positivos = sum(v > 0 for v in difs.values())
        pasa = lo > 0 and positivos >= 3
        if cuenta:
            veredictos.append(pasa)
        print(f"{con:14} {a['todo']['n']} op., R {a['todo']['r_medio']:+.3f} (sin la regla {b['todo']['n']} op., "
              f"{b['todo']['r_medio']:+.3f}); diferencia {dif:+.3f} (IC {lo:+.3f} a {hi:+.3f}); por anyo "
              + ", ".join(f"{k} {v:+.2f}" for k, v in difs.items()) + f" ({positivos}/{len(difs)}); "
              f"stop movido {a['asegurar']}; equity {a['equity'].replace('equity', '').strip()} "
              f"(sin la regla {b['equity'].replace('equity', '').strip()}); "
              f"{'PASA' if pasa else 'no pasa'}{'' if cuenta else ' [informativo]'}")

print(f"\nVEREDICTO idea I (sobre 2 + D): {'PASA' if all(veredictos) else 'NO PASA'}"
      f"  (maker {'si' if veredictos[0] else 'no'}, taker {'si' if veredictos[1] else 'no'})")
