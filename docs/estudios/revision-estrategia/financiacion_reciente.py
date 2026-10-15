"""La financiacion (funding) de los perpetuos de OKX en los ultimos ~3 meses: el coste de un corto mantenido.

Segunda ronda de la estrategia, idea candidata de los cortos (el propietario, 28/09/2026). En un perpetuo, cada 8 h los
largos pagan a los cortos si la tasa es positiva, y al reves si es negativa. Un corto de dias puede COBRAR o
PAGAR segun el mercado: justo en los tramos bajistas (cuando interesaria el corto) la tasa suele bajar o ser
negativa, y el corto paga.

La API publica (`/api/v5/public/funding-rate-history`) solo da ~3 meses (medido el 28/09: desde el 22/06/2026).
La exploracion (2020-2024) necesitaria los ficheros del historial de OKX: bajarlos pide permiso del propietario.
Esto solo LEE datos publicos y ensenya el orden de magnitud; no guarda nada.

    .venv/Scripts/python.exe docs/estudios/revision-estrategia/financiacion_reciente.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from datetime import UTC, datetime

HOST = "https://eea.okx.com"
MONEDAS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "TRX", "NEAR")
COBROS_AL_ANYO = 3 * 365


def _get(ruta: str) -> dict:
    req = urllib.request.Request(HOST + ruta, headers={"User-Agent": "ploutos/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def historia(inst: str) -> list[tuple[int, float]]:
    """(fundingTime en ms, tasa) de lo que de la API, del mas reciente al mas viejo."""
    out: list[tuple[int, float]] = []
    despues = ""
    for _ in range(50):
        d = _get(f"/api/v5/public/funding-rate-history?instId={inst}&limit=400{despues}")
        filas = d.get("data") or []
        if not filas:
            break
        out += [(int(f["fundingTime"]), float(f["realizedRate"] or f["fundingRate"])) for f in filas]
        despues = f"&after={filas[-1]['fundingTime']}"
        time.sleep(0.25)
    return out


def resumen(tasas: list[float]) -> dict:
    return {
        "cobros": len(tasas),
        "media_por_8h_pct": round(statistics.fmean(tasas) * 100, 5),
        "anual_pct": round(statistics.fmean(tasas) * COBROS_AL_ANYO * 100, 2),
        "positivas_pct": round(100 * sum(t > 0 for t in tasas) / len(tasas), 1),
        "peor_para_el_corto_pct": round(min(tasas) * 100, 4),
    }


def main() -> int:
    print("Signo: positiva = el corto COBRA; negativa = el corto PAGA.")
    print(f"{'moneda':<7}{'cobros':>7}{'media/8h %':>12}{'al anyo %':>11}{'positivas':>11}{'peor/8h %':>11}  desde")
    for m in MONEDAS:
        h = historia(f"{m}-USDT-SWAP")
        if not h:
            print(f"{m:<7}  sin datos")
            continue
        r = resumen([t for _ts, t in h])
        desde = datetime.fromtimestamp(h[-1][0] / 1000, tz=UTC).strftime("%d/%m/%Y")
        print(f"{m:<7}{r['cobros']:>7}{r['media_por_8h_pct']:>12}{r['anual_pct']:>11}{r['positivas_pct']:>10}%"
              f"{r['peor_para_el_corto_pct']:>11}  {desde}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
