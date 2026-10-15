"""Dimensionado con los parametros REALES de las 8 monedas de la whitelist.

POR QUE EXISTE: el demo de OKX solo tiene 5 de los 8 pares contra USDC (faltan
XRP, AVAX y TRX), asi que la fase 4 nunca mandara una orden de esos tres. Y el
redondeo al lote y el minimo por orden son justo donde se cometen los errores
caros. No hace falta poder operar un par para comprobar que se le calcula bien
el tamanyo: los parametros estan en la tabla `instruments` desde la fase 1, y
`tests/risk_fixtures.INSTRUMENTS` es una copia exacta (comprobada campo a campo
contra el VPS el 22/09/2026).

HALLAZGO que motivo parte de esto (22/09/2026): `round_amount_down` dividia en
coma flotante y perdia un lote entero sin motivo. 0,58 TRX salia 0,57 porque
0,58 / 0,01 = 57,999... en binario; 0,3 AVAX salia 0,2999.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from core.config import load_settings
from risk.limits import Limits
from risk.sizing import compute_size
from risk.types import EntryRequest
from tests.risk_fixtures import INSTRUMENTS

# Cierre de la ultima vela de 4 h, 22/09/2026, del VPS. Solo sirve para que los
# tamanyos salgan en el orden de magnitud real de cada moneda.
PRECIOS = {
    "BTC/USDC": 86229.1,
    "ETH/USDC": 2751.23,
    "SOL/USDC": 118.28,
    "XRP/USDC": 1.5883,
    "DOGE/USDC": 0.1,
    "AVAX/USDC": 10.975,
    "TRX/USDC": 0.3416,
    "NEAR/USDC": 4.349,
}
SIMBOLOS = sorted(PRECIOS)
SETTINGS = load_settings()


def test_los_fixtures_cubren_la_whitelist_entera():
    assert set(INSTRUMENTS) == set(SETTINGS.whitelist) == set(PRECIOS)


def _es_multiplo(qty: float, lot: float) -> bool:
    """Multiplo EXACTO del lote, mirando la representacion decimal."""
    return Decimal(repr(qty)) % Decimal(repr(lot)) == 0


# --------------------------------------------------------------------------
# El redondeo al lote
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "simbolo, pedido, esperado",
    [
        ("TRX/USDC", 0.58, 0.58),      # 0,58 / 0,01 = 57,999... en binario
        ("AVAX/USDC", 0.3, 0.3),       # 0,3 / 0,0001 = 2999,999...
        ("XRP/USDC", 1.0, 1.0),        # justo el minimo: perder un lote lo tumba
        ("DOGE/USDC", 10.0, 10.0),     # idem
        ("TRX/USDC", 58.549, 58.54),   # lo normal: se recorta lo que sobra
    ],
)
def test_un_multiplo_exacto_no_pierde_un_lote(simbolo, pedido, esperado):
    assert INSTRUMENTS[simbolo].round_amount_down(pedido) == esperado


@hsettings(max_examples=400, deadline=None)
@given(simbolo=st.sampled_from(SIMBOLOS), lotes=st.integers(1, 10**9))
def test_cualquier_multiplo_del_lote_sale_intacto(simbolo, lotes):
    lot = INSTRUMENTS[simbolo].lot_size
    cantidad = float(Decimal(lotes) * Decimal(repr(lot)))
    assert INSTRUMENTS[simbolo].round_amount_down(cantidad) == cantidad


@hsettings(max_examples=400, deadline=None)
@given(
    simbolo=st.sampled_from(SIMBOLOS),
    cantidad=st.floats(1e-6, 1e7, allow_nan=False, allow_infinity=False),
)
def test_el_redondeo_nunca_sube_y_pierde_menos_de_un_lote(simbolo, cantidad):
    ins = INSTRUMENTS[simbolo]
    r = ins.round_amount_down(cantidad)
    assert r <= cantidad, "redondear hacia ARRIBA compraria mas de lo aprobado"
    assert cantidad - r < ins.lot_size * (1 + 1e-9)
    assert _es_multiplo(r, ins.lot_size), f"{r!r} no es multiplo limpio de {ins.lot_size}"


# --------------------------------------------------------------------------
# El tamanyo, moneda a moneda, a su precio real
# --------------------------------------------------------------------------


def _pedir(simbolo, precio, stop_pct):
    return EntryRequest(
        symbol=simbolo,
        instrument=INSTRUMENTS[simbolo],
        entry_price=precio,
        stop_price=precio * (1 - stop_pct / 100),
        target_price=precio * (1 + 3 * stop_pct / 100),
        setup="pullback_trend",
        decision_id=f"d-prueba-{simbolo}",
    )


@hsettings(max_examples=600, deadline=None)
@given(
    simbolo=st.sampled_from(SIMBOLOS),
    precio_rel=st.floats(0.5, 2.0),
    stop_pct=st.floats(0.3, 15.0),
    equity=st.floats(25.0, 60.0),
    expuesto=st.floats(0.0, 50.0),
    slider=st.sampled_from([1, 2, 3, 4, 5]),
)
def test_invariantes_del_tamanyo_con_parametros_reales(
    simbolo, precio_rel, stop_pct, equity, expuesto, slider
):
    ins = INSTRUMENTS[simbolo]
    precio = PRECIOS[simbolo] * precio_rel
    lim = Limits.for_state(SETTINGS, equity, slider)
    s = compute_size(_pedir(simbolo, precio, stop_pct), lim, exposure_usd=expuesto)
    if not s.ok:
        return

    assert s.risk_usd <= lim.risk_per_trade_usd + 1e-9, "regla 12"
    assert s.notional_usd <= lim.max_notional_usd + 1e-9, "cinturon de 20 $"
    assert expuesto + s.notional_usd <= lim.max_exposure_usd + 1e-9, "regla 15"
    assert s.qty >= ins.min_amount, "cantidad por debajo del minimo: polvo"
    assert s.notional_usd >= ins.min_notional_usd(precio) - 1e-9
    assert _es_multiplo(s.qty, ins.lot_size), f"{s.qty!r} no es multiplo de {ins.lot_size}"


@pytest.mark.parametrize("simbolo", SIMBOLOS)
def test_con_el_riesgo_normal_sale_una_orden_en_las_8(simbolo):
    """Un stop del 3,3 % y 50 $ de equity: el caso de diseno (CLAUDE.md,
    decision de dimensionado). Las 8 tienen que poder abrir."""
    lim = Limits.for_state(SETTINGS, 50.0, 3)
    s = compute_size(_pedir(simbolo, PRECIOS[simbolo], 3.3), lim, exposure_usd=0.0)
    assert s.ok, s.detail
    assert 10.0 <= s.notional_usd <= 20.0 + 1e-9, s.detail


def test_btc_con_poco_margen_se_rechaza_en_vez_de_dejar_polvo():
    """El minimo de BTC son 0,0001 BTC, unos 8,62 $ a este precio (hallazgo de
    la fase 1). Con menos margen que eso, la orden no puede salir: NO se
    manda una orden por debajo del minimo que el exchange rechazaria."""
    lim = Limits.for_state(SETTINGS, 50.0, 3)
    expuesto = lim.max_exposure_usd - 8.0
    s = compute_size(_pedir("BTC/USDC", PRECIOS["BTC/USDC"], 3.3), lim, exposure_usd=expuesto)
    assert not s.ok
    assert "minimo" in s.detail
