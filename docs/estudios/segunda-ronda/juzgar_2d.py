"""Aplica el criterio de 2 + D (aprobado por el propietario el 08/10, ANTES de medir: `docs/archivo/plan-segunda-ronda-estrategia.md`).

    python juzgar_2d.py resultados/

Validacion primero: `idea2-maker` tiene que reproducir `revision-estrategia/ideas/idea2.json` EXACTA; si no, no se
juzga nada. Despues, en cada contabilidad (maker y taker): (1) IC 90 % del R medio entero por encima de +0,13;
(2) >= 100 operaciones; (3) R medio > 0 en cada anyo con >= 20 operaciones, y al menos 3 anyos asi. Pasa solo si
pasa en las dos. La reserva no se toca.
"""
import json
import sys
from pathlib import Path

LISTON = 0.13
MIN_ANYO = 20
carpeta = Path(sys.argv[1])
primera = Path(__file__).resolve().parent.parent / "revision-estrategia" / "ideas" / "idea2.json"


def cargar(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8-sig"))


ref2, nueva2 = cargar(primera), cargar(carpeta / "idea2-maker.json")
iguales = ref2["todo"] == nueva2["todo"] and ref2["operaciones"] == nueva2["operaciones"]
print(f"Validacion: la idea 2 sola (maker) {'REPRODUCE' if iguales else 'NO REPRODUCE'} la primera ronda "
      f"({nueva2['todo']['n']} op., R {nueva2['todo']['r_medio']:+.3f}; entonces {ref2['todo']['n']} op., "
      f"R {ref2['todo']['r_medio']:+.3f})")
if not iguales:
    raise SystemExit("validacion fallida: no se juzga nada")

veredictos = []
for objetivo in ("maker", "taker"):
    res = cargar(carpeta / f"2+D-{objetivo}.json")
    lo, hi = res["todo"]["ic90"]
    anyos = {a: v for a, v in res["por_anyo"].items() if v["n"] >= MIN_ANYO}
    anyos_ok = all(v["r_medio"] > 0 for v in anyos.values()) and len(anyos) >= 3
    pasa = lo > LISTON and res["todo"]["n"] >= 100 and anyos_ok
    veredictos.append(pasa)
    print(f"\n2 + D, objetivo {objetivo}: {res['todo']['n']} op., aciertos {res['todo']['aciertos_pct']} %, "
          f"R {res['todo']['r_medio']:+.3f} (IC {lo:+.3f} a {hi:+.3f}); "
          f"equity {res['equity'].replace('equity', '').strip()}; caida {res['drawdown'].replace('drawdown maximo', '').strip()}")
    print("  por anyo: " + ", ".join(f"{a} {v['n']} op. {v.get('r_medio', 0):+.2f}" for a, v in res["por_anyo"].items()))
    print("  por setup: " + ", ".join(f"{s} {v['n']} op. {v['r_medio']:+.2f}" for s, v in res["por_setup"].items()))
    print(f"  (1) IC sobre +0,13: {'si' if lo > LISTON else 'no'}; (2) >= 100 op.: "
          f"{'si' if res['todo']['n'] >= 100 else 'no'}; (3) anyos con >= {MIN_ANYO} op. todos > 0 y al menos 3: "
          f"{'si' if anyos_ok else 'no'} ({len(anyos)} anyos) -> {'PASA' if pasa else 'no pasa'}")
    otra = cargar(carpeta / f"idea2-{objetivo}.json")
    print(f"  [informativo: la idea 2 sola, {otra['todo']['n']} op., R {otra['todo']['r_medio']:+.3f} "
          f"(IC {otra['todo']['ic90'][0]:+.3f} a {otra['todo']['ic90'][1]:+.3f})]")

print(f"\nVEREDICTO 2 + D: {'PASA en la exploracion (la reserva, al final de la segunda ronda)' if all(veredictos) else 'NO PASA'}"
      f"  (maker {'si' if veredictos[0] else 'no'}, taker {'si' if veredictos[1] else 'no'})")
