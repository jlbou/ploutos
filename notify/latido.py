"""El latido para el vigilante externo (Healthchecks.io; decision del propietario del 24/09/2026).

Un bot caido no puede avisar de que se ha caido: lo avisa alguien de fuera que
echa en falta esta senyal. Cada servicio la manda **solo cuando va bien de
verdad** (el bucle de papel, al terminar una vuelta sin error; la ingesta, con
todas sus fuentes frescas). Si deja de llegar, Healthchecks.io avisa por Telegram.

Tres reglas:
- **Nunca lanza** y tiene un timeout corto: el vigilante no puede tumbar ni
  frenar lo que vigila.
- **La URL es un secreto** (quien la tenga puede mandar latidos falsos): va en
  `.env` y nunca sale en un log (`core.secrets.scrub_url`).
- **Como mucho uno cada `intervalo_s`**: Healthchecks.io limita a 5 por minuto por
  comprobacion, y el periodo configurado es de 5 min.
"""

from __future__ import annotations

import logging
import time
import urllib.request
from typing import Any

from core.secrets import scrub_url

log = logging.getLogger("ploutos.latido")

INTERVALO_S = 120.0
TIMEOUT_S = 5.0


class Latido:
    def __init__(
        self, url: str | None, nombre: str, *, intervalo_s: float = INTERVALO_S,
        _open: Any = urllib.request.urlopen, _reloj: Any = time.monotonic,
    ) -> None:
        self.url = (url or "").strip() or None
        self.nombre = nombre
        self.intervalo_s = intervalo_s
        self._open = _open
        self._reloj = _reloj
        self._ultimo: float | None = None
        if self.url is None:
            log.info("latido de %s desactivado: sin su URL en .env", nombre)

    def _pedir(self, sufijo: str = "") -> bool:
        peticion = urllib.request.Request(self.url + sufijo, headers={"User-Agent": "ploutos/0.1"})
        try:
            with self._open(peticion, timeout=TIMEOUT_S) as respuesta:
                return getattr(respuesta, "status", 200) == 200
        except Exception as exc:
            log.warning("latido de %s: no llego (%s)", self.nombre,
                        scrub_url(f"{type(exc).__name__}: {exc}", self.url))
            return False

    def enviar(self) -> bool | None:
        """Todo va bien. None = no tocaba (intervalo) o esta desactivado."""
        if self.url is None:
            return None
        ahora = self._reloj()
        if self._ultimo is not None and ahora - self._ultimo < self.intervalo_s:
            return None
        # Se apunta ANTES de pedir: si Healthchecks.io no contesta, no se insiste
        # en cada vuelta (el siguiente intento, dentro de `intervalo_s`).
        self._ultimo = ahora
        return self._pedir()

    def fallo(self) -> bool | None:
        """Algo ha fallado: aviso INMEDIATO, sin esperar a que falte el latido."""
        if self.url is None:
            return None
        return self._pedir("/fail")
