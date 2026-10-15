"""Las dos validaciones de `cortos_a.py`, ANTES de medir A' (`docs/archivo/diseno-cortos-bajistas.md` 7).

    python validar_a.py resultados/a-idea2.json resultados/a-espejo.json

1. Solo largos (la idea 2) = `revision-estrategia/ideas/idea2.json`, operacion a operacion (dia de cierre y R).
2. Solo el espejo sobre las gemelas = `revision-estrategia/cortos-operaciones.json` (simbolo, apertura, cierre, R).
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PRIMERA = AQUI.parent / "revision-estrategia"


def cargar(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def dia(ms):
    return str(datetime.fromtimestamp(ms / 1000, tz=UTC).date())


largos, espejo = cargar(sys.argv[1]), cargar(sys.argv[2])
ref2 = sorted((d, round(r, 4)) for d, r in cargar(PRIMERA / "ideas" / "idea2.json")["operaciones"])
nuevo2 = sorted((dia(o["cerrada_ms"]), round(o["r"], 4)) for o in largos)
ok1 = ref2 == nuevo2
print(f"1. idea 2: {len(nuevo2)} op. (primera ronda {len(ref2)}): {'IGUAL' if ok1 else 'DISTINTA'}")
if not ok1:
    print("   solo en la primera:", sorted(set(ref2) - set(nuevo2))[:10])
    print("   solo ahora:", sorted(set(nuevo2) - set(ref2))[:10])

clave = lambda o: (o["simbolo"], o["abierta_ms"], o["cerrada_ms"], round(o["r_con_financiacion"], 6))  # noqa: E731
refc = sorted(clave(o) for o in cargar(PRIMERA / "cortos-operaciones.json"))
nuevoc = sorted(clave(o) for o in espejo)
ok2 = refc == nuevoc
print(f"2. espejo: {len(nuevoc)} op. (28/09: {len(refc)}): {'IGUAL' if ok2 else 'DISTINTA'}")
if not ok2:
    print("   solo el 28/09:", sorted(set(refc) - set(nuevoc))[:10])
    print("   solo ahora:", sorted(set(nuevoc) - set(refc))[:10])
print("VALIDACION:", "PASA, se puede medir A'" if ok1 and ok2 else "NO PASA: no se mide nada")
raise SystemExit(0 if ok1 and ok2 else 1)
