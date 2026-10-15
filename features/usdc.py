"""Paridad de USDC con el dolar, para la regla 17 (PRD seccion 4).

Operando contra USDC, el "efectivo" ES USDC. En marzo de 2023 llego a 0,88 $ un
fin de semana (informe seccion 2.4).

OKX no tiene un par USDC/USD, asi que el precio se DEDUCE:

    A: USDC/USDT x USDT/USD
        Dos libros muy estrechos. Si el que se despega es USDT, los dos factores
        se mueven en sentido contrario y se compensan: A sigue midiendo USDC.

Historia de la decision:
- 22/09/2026 (el propietario): "A con control C", con C = BTC/USD / BTC/USDC, independiente de
  USDT; si A y C discrepaban mas del 0,5 %, la paridad quedaba DESCONOCIDA.
- 30/09/2026 ~08:00-12:00 UTC: OKX RETIRO el par BTC/USD (eea y www; solo queda
  USDT/USD contra USD). C dejo de existir y la regla 17 bloqueo todas las entradas
  de las dos carteras durante 5 velas (30/09 08:00 - 01/10 04:00).
- 01/10/2026 (el propietario): SOLO A, con el mismo umbral. En OKX ya no queda ningun control
  independiente de USDT. Lo que A no veria es que USDC y USDT cayeran A LA VEZ y en
  la misma medida (dos emisores distintos); el riesgo que cubria C (que el "USD" de
  OKX estuviera atado a USDC) es remoto desde que OKX quito el USDC del par USDT/USD
  (anuncio del 20/05/2026).

DESCONOCIDA = NO SE ENTRA (regla 17 en `risk/rules.py`). La misma regla que en
el resto del proyecto: NaN antes que un numero inventado.

Medido el 22/09/2026, 6 muestras: A 0,99986, C entre 0,99985 y 1,00005; y del 25 al
30/09, A entre -0,012 y -0,015 % con C dentro del 0,02 %. El umbral es el 1,5 %.

Calculo puro: sin red, sin reloj. Los precios los trae quien llama
(`data/usdc.py` en el bucle de papel).
"""

from __future__ import annotations

from dataclasses import dataclass

# Los libros que hacen falta. Ninguno necesita cuenta ni clave.
BOOKS = ("USDC/USDT", "USDT/USD")


@dataclass(frozen=True, slots=True)
class UsdcReading:
    """Una lectura de la paridad. `deviation_pct` None = desconocida."""

    primary: float | None        # A, precio de 1 USDC en dolares
    check: float | None          # el control C; None desde el 01/10/2026 (OKX retiro BTC/USD)
    deviation_pct: float | None  # (A - 1) * 100
    detail: str


def _valido(x: float | None) -> bool:
    return x is not None and x > 0 and x == x  # x == x descarta NaN


def bloquea_paridad(deviation_pct: float | None, tope_pct: float) -> bool:
    """Si esa lectura deja la regla 17 sin entradas: desconocida, o desviada mas del tope (igual que
    `risk/rules.rule_17`). Solo para AVISAR; quien veta es el motor de riesgo."""
    return deviation_pct is None or abs(deviation_pct) > tope_pct


def usdc_parity(mids: dict[str, float | None]) -> UsdcReading:
    """Deduce el precio de USDC en dolares a partir de los precios medios."""
    faltan = [b for b in BOOKS if not _valido(mids.get(b))]
    if faltan:
        return UsdcReading(None, None, None, f"faltan precios: {', '.join(faltan)}")

    primary = mids["USDC/USDT"] * mids["USDT/USD"]
    desviacion = (primary - 1.0) * 100
    return UsdcReading(primary, None, desviacion, f"USDC = {primary:.5f} $ ({desviacion:+.3f} %)")
