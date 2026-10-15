"""Calculo del tamanyo de la posicion (PRD regla 12, informe seccion 1.6).

LA IDEA QUE MAS SE MALENTIENDE: "arriesgar el 1 %" no es "invertir el 1 %".
Es que si la operacion salta a su stop, se pierde el 1 % del equity.

    nocional = riesgo_en_dolares / distancia_al_stop_en_tanto_por_uno

Con 0,50 $ de riesgo: un stop al 1,35 % da una posicion de 37 $, y uno al
3,33 % da una de 15 $. Stop cerca, posicion grande. Stop lejos, posicion
pequenya. El riesgo es el mismo.

Decision del 22/09/2026: se mantiene el 1 % de riesgo y las posiciones salen de
~15 $, lo que obliga a stops del orden del 3,3 % y por tanto a setups de 4 h.
Los numeros del PRD cuadran exactos con eso: 3 x 15 $ = 45 $ = el 90 % de
exposicion maxima, y 6 operaciones x 0,50 $ = 3 $ = el limite diario.
"""

from __future__ import annotations

from dataclasses import dataclass

from risk.limits import Limits
from risk.types import EntryRequest


@dataclass(frozen=True, slots=True)
class Sizing:
    qty: float
    notional_usd: float
    risk_usd: float
    ok: bool
    detail: str


def compute_size(
    req: EntryRequest, lim: Limits, *, exposure_usd: float
) -> Sizing:
    """Cuanto comprar. Devuelve `ok=False` si no sale una orden valida.

    `exposure_usd` es lo que YA esta expuesto (posiciones mas pendientes), y no
    tiene valor por defecto a proposito. Con un cero por defecto, quien se
    olvidase de pasarlo obtendria un tamanyo que se salta la regla 15 sin que
    nada chille. Obligar a decirlo convierte ese olvido en un error al instante.
    """
    instrument = req.instrument
    entry = req.entry_price
    stop_distance = entry - req.stop_price

    if stop_distance <= 0:
        return Sizing(0, 0, 0, False, "el stop no esta por debajo de la entrada")

    # 1. Riesgo permitido, ya modulado por drawdown y slider, y reducido por la
    #    IA si lo pidio (solo puede reducir: [0,5; 1,0]).
    risk_usd = lim.risk_per_trade_usd * req.size_multiplier

    # 2. Nocional que corresponde a ese riesgo.
    notional = risk_usd / (stop_distance / entry)

    # 3. Topes de nocional. El cinturon de `max_notional_usd` existe para que un
    #    stop anormalmente estrecho no genere una posicion enorme.
    capped_by = ""
    if notional > lim.max_notional_usd:
        notional = lim.max_notional_usd
        capped_by = f"tope de nocional {lim.max_notional_usd:.2f} $"

    # 4. Regla 15: el tope del 90 % es sobre la exposicion TOTAL, no sobre esta
    #    orden suelta. Hay que recortar contra el margen que queda, no contra
    #    el tope entero: con 30 $ ya expuestos y un tope de 45 $, esta orden no
    #    puede pasar de 15 $ aunque 20 $ cupiesen "en el tope".
    headroom = lim.max_exposure_usd - exposure_usd
    if headroom <= 0:
        return Sizing(
            0, 0, 0, False,
            f"sin margen de exposicion: ya hay {exposure_usd:.2f} $ expuestos "
            f"y el tope son {lim.max_exposure_usd:.2f} $",
        )
    if notional > headroom:
        notional = headroom
        capped_by = (
            f"margen de exposicion {headroom:.2f} $ "
            f"({lim.max_exposure_usd:.2f} $ menos {exposure_usd:.2f} $ ya expuestos)"
        )

    # 5. Cantidad, redondeada al lote SIEMPRE HACIA ABAJO.
    qty = instrument.round_amount_down(notional / entry)
    if qty <= 0:
        return Sizing(
            0, 0, 0, False,
            f"la cantidad redondeada al lote ({instrument.lot_size}) queda en cero",
        )

    final_notional = qty * entry
    final_risk = qty * stop_distance

    # 6. Minimos del instrumento.
    if qty < instrument.min_amount:
        return Sizing(
            qty, final_notional, final_risk, False,
            f"cantidad {qty} por debajo del minimo del instrumento "
            f"{instrument.min_amount}",
        )
    min_notional = instrument.min_notional_usd(entry)
    if final_notional < min_notional:
        return Sizing(
            qty, final_notional, final_risk, False,
            f"nocional {final_notional:.2f} $ por debajo del minimo por orden "
            f"{min_notional:.2f} $",
        )

    # 7. El redondeo hacia abajo solo puede bajar el riesgo, nunca subirlo.
    #    Si lo subiera seria un error de calculo, no un caso limite.
    if final_risk > risk_usd + 1e-9:
        return Sizing(
            qty, final_notional, final_risk, False,
            f"el riesgo resultante {final_risk:.4f} $ supera el permitido "
            f"{risk_usd:.4f} $",
        )

    detail = (
        f"riesgo {final_risk:.3f} $ sobre {final_notional:.2f} $ "
        f"(stop a {req.stop_distance_pct:.2f} %)"
    )
    if capped_by:
        detail += f", limitado por {capped_by}"
    return Sizing(qty, final_notional, final_risk, True, detail)
