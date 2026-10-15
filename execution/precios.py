"""Precios y cantidad al paso de OKX, justo antes de construir la orden (fase 4).

POR QUE HACE FALTA (verificado en ccxt 4.5.82, 24/09/2026): `ccxt` redondea el precio
AL MAS CERCANO (`price_to_precision` usa ROUND) y la cantidad hacia abajo (TRUNCATE).
Si se le pasan los precios del candidato tal cual, puede subir la entrada o bajar el
stop medio tick, y el riesgo real pasaria del que aprobo el motor. Poco dinero, pero
es justo lo que las reglas duras existen para impedir. Asi que se redondea AQUI, cada
precio hacia su lado seguro, y a ccxt le llega un precio que ya esta en el tick: su
redondeo no cambia nada (hay un test que lo comprueba con el ccxt de verdad).

EL LADO SEGURO DE CADA UNO:
- entrada (compra limit, post-only): hacia ABAJO. Se compra igual o mas barato, sigue
  por debajo del mercado (post-only) y el riesgo por unidad baja.
- stop (disparo de venta, bajo la entrada): hacia ARRIBA, hacia la entrada. El riesgo
  por unidad baja; hacia abajo lo subiria por encima de lo aprobado.
- objetivo (venta limit, sobre la entrada): hacia ARRIBA. La recompensa no baja, asi
  que el R:R minimo y la regla 16 (objetivo >= 3x el coste) siguen cumpliendose.
- cantidad: al lote, hacia abajo (como en `risk/sizing.py`; aqui se repite, idempotente).

Despues se COMPRUEBA, no se supone: stop < entrada < objetivo, minimos del par, y que
el riesgo real no pasa del aprobado. Si algo falla, no hay orden (`PreciosInvalidos`).
Con los ticks de las 8 (de 0,1 $ en BTC a 0,00001 en DOGE y TRX) casi nunca pasara: el
caso es un stop a menos de un tick de la entrada, que ademas seria un stop absurdo.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from risk.types import Instrument

# Holgura de coma flotante al comparar dolares (una millonesima de centimo).
EPS_USD = 1e-9


class PreciosInvalidos(Exception):
    """Con los precios al tick la orden ya no es la que aprobo el motor: no se envia."""

    def __init__(self, simbolo: str, motivos: list[str]):
        self.motivos = motivos
        super().__init__(f"{simbolo}: " + "; ".join(motivos))


@dataclass(frozen=True, slots=True)
class PreciosOrden:
    entrada: float
    stop: float
    objetivo: float
    cantidad: float

    @property
    def riesgo_usd(self) -> float:
        return (self.entrada - self.stop) * self.cantidad


def techo_al_paso(valor: float, paso: float) -> float:
    """El multiplo de `paso` mas pequenyo que no queda por debajo de `valor`.

    Con Decimal y `repr`, como `risk.types._floor_to_step`: en coma flotante,
    0,58 / 0,01 da 57,999... y se colaria un paso de mas o de menos.
    """
    if paso <= 0:
        return valor
    p = Decimal(repr(paso))
    pasos = (Decimal(repr(valor)) / p).to_integral_value(rounding=ROUND_CEILING)
    return float(pasos * p)


def al_tick(
    instrumento: Instrument, *, entrada: float, stop: float, objetivo: float, cantidad: float,
    riesgo_aprobado_usd: float,
) -> PreciosOrden:
    """Los precios y la cantidad que se mandan a OKX, o `PreciosInvalidos`."""
    p = PreciosOrden(
        entrada=instrumento.round_price_down(entrada),
        stop=techo_al_paso(stop, instrumento.tick_size),
        objetivo=techo_al_paso(objetivo, instrumento.tick_size),
        cantidad=instrumento.round_amount_down(cantidad),
    )
    motivos: list[str] = []
    if not 0 < p.stop < p.entrada < p.objetivo:
        motivos.append(f"al tick ya no se cumple 0 < stop < entrada < objetivo "
                       f"({p.stop} / {p.entrada} / {p.objetivo})")
    if p.cantidad < instrumento.min_amount:
        motivos.append(f"cantidad {p.cantidad} por debajo del minimo {instrumento.min_amount}")
    elif p.cantidad * p.entrada < instrumento.min_notional_usd(p.entrada) - EPS_USD:
        motivos.append(f"nocional {p.cantidad * p.entrada:.4f} $ por debajo del minimo")
    if p.riesgo_usd > riesgo_aprobado_usd + EPS_USD:
        motivos.append(f"riesgo real {p.riesgo_usd:.6f} $ por encima del aprobado "
                       f"{riesgo_aprobado_usd:.6f} $")
    if motivos:
        raise PreciosInvalidos(instrumento.symbol, motivos)
    return p
