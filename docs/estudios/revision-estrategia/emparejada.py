"""La comparacion EMPAREJADA con la referencia (solo como informacion; decision del propietario del 26/09).

R total de cada dia (suma de las operaciones que cierran ese dia), idea menos referencia, sobre todos los
dias en que alguna de las dos cierra algo; intervalo del 90 % por bootstrap de esos dias.

    python emparejada.py referencia.json ideas/idea2.json [...]
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

random.seed(20250926)


def por_dia(x):
    s = defaultdict(float)
    for dia, r in x["operaciones"]:
        s[dia] += r
    return s


ref = por_dia(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
for ruta in sys.argv[2:]:
    idea = por_dia(json.loads(Path(ruta).read_text(encoding="utf-8")))
    dias = sorted(set(ref) | set(idea))
    dif = [idea.get(k, 0.0) - ref.get(k, 0.0) for k in dias]
    tot = sorted(sum(random.choices(dif, k=len(dif))) for _ in range(10_000))
    print(f"{Path(ruta).stem:10s} R total de mas: {sum(dif):+.1f} R (IC 90 %: {tot[500]:+.1f} a {tot[9500]:+.1f}), "
          f"{len(dias)} dias con operaciones")
