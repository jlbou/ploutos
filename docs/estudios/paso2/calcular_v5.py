"""V5: el deslizamiento por lado para el simulador, de las fotos de los libros (plan, seccion 13; aclaracion 3, fijada
ANTES de verlas). En cada foto, el coste de 10.000 € a mercado de compra y de venta frente al precio medio; por par,
el percentil 90; el simulador usa el par mas caro. Una foto sin profundidad cuenta con un 1 %.

    .venv/Scripts/python.exe docs/estudios/paso2/calcular_v5.py <copia de var/ploutos-libros.db>

No corre antes del final del recolector (30/10/2026). Escribe `resultados/v5.json`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
NOCIONAL = 10_000.0
SIN_PROFUNDIDAD = 0.01
FIN = datetime(2026, 10, 30, tzinfo=UTC)


def comprobar_fecha(ahora: datetime) -> None:
    if ahora < FIN:
        raise PermissionError("V5 no se calcula antes del final del recolector (30/10/2026)")


def coste(lado: list[list[float]], nocional: float, mid: float) -> float | None:
    """Coste relativo (positivo) de mover `nocional` euros por un lado del libro; None si no llega."""
    falta, euros, cantidad = nocional, 0.0, 0.0
    for precio, q in lado:
        usa = min(falta, precio * q)
        euros += usa
        cantidad += usa / precio
        falta -= usa
        if falta <= 1e-9:
            return abs((euros / cantidad) / mid - 1)
    return None


def percentil(x: list[float], p: float) -> float:
    s = sorted(x)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def calcular(base: Path) -> dict:
    conn = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    filas = conn.execute("SELECT par, asks, bids FROM libros").fetchall()
    conn.close()
    pares: dict[str, dict] = {}
    for par, asks, bids in filas:
        a, b = json.loads(asks), json.loads(bids)
        if not a or not b:
            continue
        mid = (a[0][0] + b[0][0]) / 2
        d = pares.setdefault(par, {"costes": [], "sin_profundidad": 0, "fotos": 0})
        d["fotos"] += 1
        for lado in (a, b):
            c = coste(lado, NOCIONAL, mid)
            if c is None:
                d["sin_profundidad"] += 1
                c = SIN_PROFUNDIDAD
            d["costes"].append(c)
    salida = {"pares": {}, "nocional": NOCIONAL}
    for par, d in pares.items():
        salida["pares"][par] = {"fotos": d["fotos"], "sin_profundidad": d["sin_profundidad"],
                                "mediana": percentil(d["costes"], 0.5), "p90": percentil(d["costes"], 0.9),
                                "p99": percentil(d["costes"], 0.99), "maximo": max(d["costes"])}
    salida["deslizamiento_por_lado"] = max(x["p90"] for x in salida["pares"].values())
    return salida


def main() -> int:
    comprobar_fecha(datetime.now(UTC))
    r = calcular(Path(sys.argv[1]))
    (AQUI / "resultados").mkdir(exist_ok=True)
    (AQUI / "resultados" / "v5.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    for par, x in r["pares"].items():
        print(f"{par}: {x['fotos']} fotos, mediana {100 * x['mediana']:.4f} %, p90 {100 * x['p90']:.4f} %, "
              f"sin profundidad {x['sin_profundidad']}")
    print(f"deslizamiento por lado para el simulador: {100 * r['deslizamiento_por_lado']:.4f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
