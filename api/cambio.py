"""El cambio USDC/EUR de OKX, para el CSV fiscal (PRD: "el bot exporta un CSV fiscal desde el primer dia").

EXCEPCION ACOTADA a "el panel no habla con el exchange" (decision del propietario del 25/09; la excepcion, del 28/09):
SOLO datos publicos (velas de 1 h de USDC-EUR, sin claves ni cuenta), SOLO cuando se baja el CSV y con un
tope de peticiones. Si OKX no responde, el CSV sale igual, con las columnas en euros vacias.

El cambio de un instante es la APERTURA de la vela de 1 h en que cae (el precio al empezar esa hora). Si esa
hora no tiene vela (sin negociacion), vale la anterior mas cercana dentro de `HUECO_MAX_MS`; si no, no hay
cambio. OKX tiene USDC-EUR con historia (comprobado el 28/09/2026: velas de 1 h de enero de 2025).
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Iterable

# Propio y no el de `data.exchange`: el panel no importa el cliente del exchange (ni ccxt). OKX responde
# 403 al User-Agent por defecto de Python (CLAUDE.md), asi que hace falta uno.
USER_AGENT = "ploutos/0.1 (panel)"

HORA_MS = 3_600_000
HUECO_MAX_MS = 6 * HORA_MS
MAX_PETICIONES = 40                 # x 100 velas = 4.000 h (~5,5 meses de huecos entre operaciones)
TIMEOUT_S = 5
URL = "https://{host}/api/v5/market/history-candles?instId=USDC-EUR&bar=1H&limit=100&after={after}"

Pedir = Callable[[str, int], list[list[str]]]


def pedir_okx(host: str, after_ms: int) -> list[list[str]]:
    """Hasta 100 velas de 1 h ANTERIORES a `after_ms`, la mas reciente primero (formato de OKX)."""
    peticion = urllib.request.Request(URL.format(host=host, after=after_ms), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as r:
        datos = json.load(r)
    if datos.get("code") != "0":
        raise RuntimeError(f"OKX respondio {datos.get('code')}: {datos.get('msg')}")
    return datos["data"]


def hora(ms: int) -> int:
    return ms - ms % HORA_MS


def aperturas(instantes: Iterable[int], host: str, pedir: Pedir = pedir_okx,
              pausa_s: float = 0.12) -> dict[int, float]:
    """{inicio de la hora: apertura de USDC/EUR} de las horas que cubren `instantes`, bajando lo justo.

    Va de la hora mas reciente hacia atras: cada peticion trae las 100 horas anteriores y tacha las que
    cubre. Nunca lanza: un fallo de red deja sin cambio lo que falte.
    """
    faltan = sorted({hora(ms) for ms in instantes}, reverse=True)
    tabla: dict[int, float] = {}
    for n in range(MAX_PETICIONES):
        if not faltan:
            break
        if n:
            time.sleep(pausa_s)                     # history-candles: 20 peticiones cada 2 s
        try:
            velas = pedir(host, faltan[0] + HORA_MS)
        except Exception:  # noqa: BLE001 - sin cambio es un dato vacio, no un error del panel
            break
        if not velas:
            break
        for v in velas:
            tabla[int(v[0])] = float(v[1])
        mas_vieja = min(int(v[0]) for v in velas)
        # Las que quedan dentro de lo bajado ya tienen su vela (o la anterior mas cercana).
        faltan = [h for h in faltan if h < mas_vieja]
    return tabla


def cambio(instante_ms: int, tabla: dict[int, float]) -> float | None:
    """El cambio de un instante: su hora, o la anterior mas cercana dentro de `HUECO_MAX_MS`."""
    h = hora(instante_ms)
    for atras in range(0, HUECO_MAX_MS + 1, HORA_MS):
        if h - atras in tabla:
            return tabla[h - atras]
    return None
