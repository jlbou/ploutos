"""Precios al tick (`execution/precios.py`), contra el ccxt DE VERDAD y sin red.

Lo que se protege: que el riesgo real nunca pase del aprobado por culpa de un
redondeo, y que el redondeo que ccxt hace despues (al mas cercano) ya no cambie nada.
"""

from __future__ import annotations

from decimal import Decimal

import ccxt
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from execution.precios import PreciosInvalidos, al_tick, techo_al_paso
from tests.risk_fixtures import INSTRUMENTS

BTC = INSTRUMENTS["BTC/USDC"]
XRP = INSTRUMENTS["XRP/USDC"]


def en_paso(valor: float, paso: float) -> bool:
    return (Decimal(repr(valor)) / Decimal(repr(paso))) % 1 == 0


def okx_con_los_ticks_reales():
    """Un mercado por moneda con su tick y su lote reales (tests/risk_fixtures = los de OKX)."""
    ex = ccxt.okx({"hostname": "eea.okx.com"})
    mercados = []
    for simbolo, i in INSTRUMENTS.items():
        base, quote = simbolo.split("/")
        mercados.append({
            "id": f"{base}-{quote}", "symbol": simbolo, "base": base, "quote": quote,
            "baseId": base, "quoteId": quote, "type": "spot", "spot": True, "margin": False,
            "swap": False, "future": False, "option": False, "contract": False, "linear": None,
            "inverse": None, "settle": None, "active": True,
            "precision": {"amount": i.lot_size, "price": i.tick_size},
            "limits": {"amount": {"min": i.min_amount}, "cost": {"min": None}}, "info": {},
        })
    ex.set_markets(mercados)
    return ex


OKX = okx_con_los_ticks_reales()


def test_ccxt_redondea_el_precio_al_mas_cercano_y_por_eso_existe_esta_pieza():
    """Si una version nueva de ccxt cambia esto, este test lo dice."""
    assert OKX.price_to_precision("BTC/USDC", 65000.07) == "65000.1", "hacia ARRIBA: compraria mas caro"
    assert OKX.price_to_precision("BTC/USDC", 63712.33) == "63712.3", "hacia ABAJO: el stop se alejaria"
    assert OKX.amount_to_precision("XRP/USDC", 12.3456) == "12.345", "la cantidad si trunca"


def test_cada_precio_va_a_su_lado_seguro():
    p = al_tick(BTC, entrada=65000.07, stop=63712.33, objetivo=68000.01, cantidad=0.000230009,
                riesgo_aprobado_usd=0.5)
    assert (p.entrada, p.stop, p.objetivo, p.cantidad) == (65000.0, 63712.4, 68000.1, 0.00023)


def test_el_techo_no_pierde_un_paso_por_la_coma_flotante():
    assert techo_al_paso(0.58, 0.01) == 0.58
    assert techo_al_paso(0.581, 0.01) == 0.59
    assert techo_al_paso(0.3, 0.1) == 0.3


def test_un_stop_a_menos_de_un_tick_de_la_entrada_no_da_orden():
    with pytest.raises(PreciosInvalidos, match="stop < entrada"):
        al_tick(XRP, entrada=0.50004, stop=0.50001, objetivo=0.52, cantidad=30,
                riesgo_aprobado_usd=0.5)


def test_por_debajo_del_minimo_del_par_no_da_orden():
    with pytest.raises(PreciosInvalidos, match="minimo"):
        al_tick(XRP, entrada=0.5, stop=0.48, objetivo=0.56, cantidad=0.9999,
                riesgo_aprobado_usd=0.5)


def test_si_el_riesgo_ya_venia_por_encima_de_lo_aprobado_no_da_orden():
    """Segundo sitio de la comprobacion: el motor ya lo miro, esto no lo supone."""
    with pytest.raises(PreciosInvalidos, match="riesgo real"):
        al_tick(BTC, entrada=65000, stop=63000, objetivo=70000, cantidad=0.0003,
                riesgo_aprobado_usd=0.5)


# Rangos de precio realistas por moneda (de un tercio a tres veces el de septiembre de 2026):
# con un rango comun, XRP a 150.000 $ no llegaba a la cantidad minima y hypothesis
# descartaba tantos casos que paraba el test (FailedHealthCheck, 24/09).
RANGOS = {"BTC/USDC": (30_000, 300_000), "ETH/USDC": (1_000, 12_000), "SOL/USDC": (50, 600),
          "XRP/USDC": (0.7, 9), "DOGE/USDC": (0.08, 0.9), "AVAX/USDC": (8, 90),
          "TRX/USDC": (0.1, 1.0), "NEAR/USDC": (1, 12)}


@settings(max_examples=400, deadline=None)
@given(
    simbolo=st.sampled_from(sorted(INSTRUMENTS)),
    posicion=st.floats(min_value=0.0, max_value=1.0),
    stop_pct=st.floats(min_value=0.005, max_value=0.08),
    rr=st.floats(min_value=2.0, max_value=7.0),
    nocional=st.floats(min_value=10.0, max_value=20.0),
)
def test_para_cualquier_orden_el_riesgo_real_no_pasa_del_aprobado_y_ccxt_no_la_toca(
    simbolo, posicion, stop_pct, rr, nocional,
):
    i = INSTRUMENTS[simbolo]
    lo, hi = RANGOS[simbolo]
    entrada = lo * (hi / lo) ** posicion
    stop = entrada * (1 - stop_pct)
    objetivo = entrada + rr * (entrada - stop)
    cantidad = i.round_amount_down(nocional / entrada)
    assume(cantidad >= i.min_amount)
    # Que los precios esten a varios ticks entre si, como en cualquier candidato real.
    assume(entrada - stop > 3 * i.tick_size)
    riesgo = (entrada - stop) * cantidad
    p = al_tick(i, entrada=entrada, stop=stop, objetivo=objetivo, cantidad=cantidad,
                riesgo_aprobado_usd=riesgo)

    assert p.riesgo_usd <= riesgo + 1e-9
    assert p.entrada <= entrada and p.stop >= stop and p.objetivo >= objetivo
    assert (p.objetivo - p.entrada) / (p.entrada - p.stop) >= rr - 1e-9, "el R:R no baja"
    for v in (p.entrada, p.stop, p.objetivo):
        assert en_paso(v, i.tick_size)
        assert float(OKX.price_to_precision(simbolo, v)) == v, "el redondeo de ccxt ya no cambia nada"
    assert float(OKX.amount_to_precision(simbolo, p.cantidad)) == p.cantidad
