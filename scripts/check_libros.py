"""El juez del recolector de libros (V5): ¿sigue recogiendo? Sale con 0 (en orden o terminado), 1 (FALLA) o 2 (aun no
empezo). Lo pasa `jueces_diarios.py` cada noche.

- FALLA si en las ultimas 24 h hay menos de 20 libros de cualquiera de los dos pares, o el ultimo tiene mas de 2 h.
- Desde el FIN, dice cuantos hay y sale con 0.
"""
from __future__ import annotations

import gzip
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from recolector_libros import DESTINO, FIN, PARES  # noqa: E402

H = 3600_000


def leer(directorio: Path) -> list[tuple[str, int]]:
    out = []
    for f in sorted(directorio.glob("libros-*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as g:
            out += [(d["par"], int(d["ms"])) for d in map(json.loads, filter(None, g.read().splitlines()))]
    return out


def juzgar(libros: list[tuple[str, int]], ahora_ms: int) -> tuple[int, str]:
    if not libros:
        return 2, "sin libros todavia"
    fin_ms = int(datetime.fromisoformat(FIN).replace(tzinfo=UTC).timestamp() * 1000)
    total = {p: sum(1 for x, _ in libros if x == p) for p in PARES}
    if ahora_ms >= fin_ms + 2 * H:
        return 0, f"V5 terminada: {total}"
    malos = []
    for p in PARES:
        dia = sum(1 for x, ms in libros if x == p and ms > ahora_ms - 24 * H)
        ultimo = max((ms for x, ms in libros if x == p), default=0)
        if dia < 20 or ahora_ms - ultimo > 2 * H:
            malos.append(f"{p}: {dia} en 24 h, el ultimo hace {(ahora_ms - ultimo) / H:.1f} h")
    if malos:
        return 1, "FALLA: el recolector no recoge: " + "; ".join(malos)
    return 0, f"recogiendo: {total}"


def main() -> int:
    codigo, texto = juzgar(leer(DESTINO), int(time.time() * 1000))
    print(f"Libros de ordenes (V5, hasta el {FIN}): {texto}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
