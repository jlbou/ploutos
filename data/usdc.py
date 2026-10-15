"""Los precios que necesita la regla 17, sacados de OKX (solo datos publicos).

El calculo esta en `features/usdc.py`; aqui solo se van a buscar los libros
(`BOOKS`: dos desde el 01/10/2026). Un libro que falla devuelve `None`, y con un `None` la paridad queda
DESCONOCIDA y no se entra: un fallo de red cuesta oportunidades, nunca dinero.

Sincrono a proposito: el bucle de papel es sincrono y hace esto una vez por vela
de 4 h. En la fase 4 esto deberia salir de la ingesta, que es la capa de datos;
no se hizo ahi el 22/09/2026 porque habria obligado a reiniciar la ingesta en
mitad de las 72 h del criterio de la fase 1.
"""

from __future__ import annotations

import ccxt

from core.config import Settings
from core.logging import get_logger
from data.exchange import USER_AGENT
from features.usdc import BOOKS

log = get_logger(__name__)

TIMEOUT_MS = 10_000


def public_client(settings: Settings) -> ccxt.okx:
    return ccxt.okx(
        {
            "enableRateLimit": True,
            "timeout": TIMEOUT_MS,
            "options": {"defaultType": "spot"},
            # OKX responde 403 al User-Agent por defecto de Python (CLAUDE.md).
            "headers": {"User-Agent": USER_AGENT},
            "hostname": settings.exchange.hostname,
        }
    )


def fetch_mids(client: ccxt.okx) -> dict[str, float | None]:
    """Precio medio de cada libro, o `None` si no se pudo leer."""
    out: dict[str, float | None] = {}
    for symbol in BOOKS:
        try:
            book = client.fetch_order_book(symbol, 5)
            bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
            out[symbol] = (bid + ask) / 2 if 0 < bid < ask else None
        except Exception as exc:  # noqa: BLE001 - cualquier fallo es "sin dato"
            log.warning("no se pudo leer %s para la regla 17: %s", symbol, type(exc).__name__)
            out[symbol] = None
    return out
