"""V4 (paso 2): ¿se parece Bitstamp a OKX en euros donde coinciden? Criterio fijado y subido ANTES de mirar
(`docs/plan-estudio-paso-2.md`, 15/10/2026): mediana de |diferencia| del cierre diario < 0,10 % y el 99 % de los
dias < 1 %, en BTC/EUR y en ETH/EUR.

    .venv/Scripts/python.exe docs/estudios/paso2/comprobar_v4.py
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

DATOS = Path(__file__).resolve().parents[3] / "var" / "estudios" / "paso2"


def cierres(nombre: str) -> dict[int, float]:
    return {int(v[0]): float(v[4]) for v in json.loads((DATOS / f"{nombre}.json").read_text(encoding="utf-8"))}


def main() -> int:
    ok = True
    for par in ("btceur", "etheur"):
        b, o = cierres(f"bitstamp-{par}"), cierres(f"okx-{par}")
        comunes = sorted(set(b) & set(o))
        dif = sorted(abs(b[t] / o[t] - 1) * 100 for t in comunes)
        mediana, p99, maxima = statistics.median(dif), dif[int(0.99 * (len(dif) - 1))], dif[-1]
        pasa = mediana < 0.10 and p99 < 1.0
        ok &= pasa
        print(f"{par}: {len(comunes)} dias en comun; |dif| mediana {mediana:.3f} %, p99 {p99:.3f} %, maxima "
              f"{maxima:.3f} % -> {'PASA' if pasa else 'NO PASA'}")
    print("V4:", "se acepta Bitstamp" if ok else "NO se acepta: estudiar por que antes de usarla")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
