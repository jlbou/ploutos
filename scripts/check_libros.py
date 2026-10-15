"""El juez del recolector de libros (V5): ¿sigue recogiendo? Sale con 0 (en orden o terminado), 1 (FALLA) o 2 (aun no
empezo). Lo pasa `jueces_diarios.py` cada noche.

- FALLA si en las ultimas 24 h hay menos de 20 libros de cualquiera de los dos pares, o el ultimo tiene mas de 2 h.
- Desde el FIN, dice cuantos hay y sale con 0.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from recolector_libros import BASE, FIN, PARES  # noqa: E402

H = 3600_000


def leer(ruta: Path) -> list[tuple[str, int]]:
    """Los (par, ms) guardados, en solo lectura; sin base, ninguno."""
    if not ruta.exists():
        return []
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=30)
    try:
        return [(p, int(ms)) for p, ms in conn.execute("SELECT par, ms FROM libros")]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def juzgar(libros: list[tuple[str, int]], ahora_ms: int) -> tuple[int, str]:
    if not libros:
        return 2, "sin libros todavia"
    fin_ms = int(datetime.fromisoformat(FIN).replace(tzinfo=UTC).timestamp() * 1000)
    total = {p: sum(1 for x, _ in libros if x == p) for p in PARES}
    if ahora_ms >= fin_ms + 2 * H:
        return 0, f"V5 terminada: {total}"
    malos = []
    # Las primeras 24 h no puede haber 20: se piden las horas que lleva (menos 4 de margen). 16/10: el primer dia daba
    # FALLA a los pocos minutos de arrancar.
    horas = min(24.0, (ahora_ms - min(ms for _, ms in libros)) / H)
    minimo = max(0, min(20, int(horas) - 4))
    for p in PARES:
        dia = sum(1 for x, ms in libros if x == p and ms > ahora_ms - 24 * H)
        ultimo = max((ms for x, ms in libros if x == p), default=0)
        if dia < minimo or ahora_ms - ultimo > 2 * H:
            malos.append(f"{p}: {dia} en 24 h, el ultimo hace {(ahora_ms - ultimo) / H:.1f} h")
    if malos:
        return 1, "FALLA: el recolector no recoge: " + "; ".join(malos)
    return 0, f"recogiendo: {total}"


def main() -> int:
    codigo, texto = juzgar(leer(BASE), int(time.time() * 1000))
    print(f"Libros de ordenes (V5, hasta el {FIN}): {texto}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
