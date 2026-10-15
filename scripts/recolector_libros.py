"""Recolector de libros de ordenes (paso 2, comprobacion V5; propietario, 15/10/2026): cada hora, el libro de BTC-EUR y
ETH-EUR de OKX (400 niveles por lado, la API PUBLICA: sin claves, solo lee) y lo guarda, para medir el deslizamiento
con 10.000 € en momentos distintos (no una foto). Se para solo a partir del FIN.

    .venv/bin/python scripts/recolector_libros.py          # lo lanza ploutos-libros.timer cada hora
"""
from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESTINO = REPO / "var" / "libros"
PARES = ("BTC-EUR", "ETH-EUR")
FIN = "2026-10-30"          # 2 semanas desde el 16/10
HOST = "https://eea.okx.com"


def terminado(ahora: datetime) -> bool:
    return ahora.date().isoformat() >= FIN


def fichero(ahora: datetime) -> Path:
    return DESTINO / f"libros-{ahora:%Y-%m-%d}.jsonl.gz"


def linea(par: str, ms: int, libro: dict) -> str:
    """Solo precio y cantidad de cada nivel (lo demas no hace falta)."""
    return json.dumps({"par": par, "ms": ms, "ts_libro": int(libro["ts"]),
                       "asks": [[float(p), float(q)] for p, q, *_ in libro["asks"]],
                       "bids": [[float(p), float(q)] for p, q, *_ in libro["bids"]]}, separators=(",", ":"))


def main() -> int:
    ahora = datetime.now(UTC)
    if terminado(ahora):
        print(f"V5 terminada el {FIN}: no se recoge nada mas")
        return 0
    DESTINO.mkdir(parents=True, exist_ok=True)
    ms, fallos, lineas = int(ahora.timestamp() * 1000), 0, []
    for par in PARES:
        try:
            req = urllib.request.Request(f"{HOST}/api/v5/market/books?instId={par}&sz=400",
                                         headers={"User-Agent": "Mozilla/5.0"})
            libro = json.loads(urllib.request.urlopen(req, timeout=20).read())["data"][0]
            lineas.append(linea(par, ms, libro))
        except Exception as exc:  # noqa: BLE001 - una moneda que falla no tumba la otra
            fallos += 1
            print(f"{par}: no se pudo leer ({type(exc).__name__})")
        time.sleep(0.5)
    if lineas:
        with gzip.open(fichero(ahora), "at", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")
    print(f"{ahora:%Y-%m-%d %H:%M} UTC: {len(lineas)} libros guardados, {fallos} fallos")
    return 1 if fallos == len(PARES) else 0


if __name__ == "__main__":
    sys.exit(main())
