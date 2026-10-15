"""El puente de las noticias al filtro que ya existe (`strategy.filters.filter_event`).

El filtro esta desde la fase 2 y nadie le daba datos. Aqui se comprueba con el filtro DE
VERDAD, no con una copia: si alguien cambia el formato de `RiskState.event_flags` o el
filtro deja de mirarlo, estos tests se enteran.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.config import load_settings
from features.news import (
    HORA_MS, Anuncio, bases_de, event_flags, flags, pares_criticos,
)
from risk.limits import Limits
from strategy.costs import CostModel, Fees
from strategy.filters import MarketSnapshot, screen
from tests.risk_fixtures import INSTRUMENTS, MAKER, NOW, PRICES, TAKER, make_state

WHITELIST = load_settings().whitelist
BASES = bases_de(WHITELIST)
T = int(NOW.timestamp() * 1000)


def anuncio(titulo, horas=0.0, id_="a"):
    return Anuncio(id_, T + int(horas * HORA_MS), titulo)


@pytest.fixture
def cost() -> CostModel:
    return CostModel({s: Fees(s, MAKER, TAKER, T) for s in INSTRUMENTS}, now_ms=T)


@pytest.fixture
def limits(settings) -> Limits:
    return Limits.for_state(settings, equity_usd=50.0, slider_level=3)


def cribar(simbolo, estado, settings, limits, cost):
    snap = MarketSnapshot(symbol=simbolo, price=PRICES[simbolo], spread_pct=0.02,
                          depth_usd=5_000.0, atr_pct=1.5)
    return screen(snap, estado, limits, settings, cost, INSTRUMENTS[simbolo])


def test_las_flags_activas_llegan_con_el_par_y_una_etiqueta_legible():
    todas = flags([anuncio("OKX to delist NEAR", id_="d"),
                   anuncio("Announcement on the Price Volatility of NEAR", id_="v")], BASES)
    assert event_flags(todas, T + HORA_MS, WHITELIST) == {
        "NEAR/USDC": ("delisting (critica)", "volatility (alta)")}
    assert event_flags(todas, T + 25 * HORA_MS, WHITELIST) == {
        "NEAR/USDC": ("delisting (critica)",)}, "la volatilidad caduca a las 24 h; el deslistado no"


def test_con_el_filtro_de_verdad_la_moneda_con_aviso_no_pasa_y_las_demas_si(settings, limits, cost):
    todas = flags([anuncio("OKX to delist NEAR")], BASES)
    estado = replace(make_state(), event_flags=event_flags(todas, T + HORA_MS, WHITELIST))
    near = cribar("NEAR/USDC", estado, settings, limits, cost)
    assert not near.passed
    assert any(r.name == "evento" and "delisting" in r.detail for r in near.rejections)
    assert cribar("BTC/USDC", estado, settings, limits, cost).passed


def test_un_aviso_caducado_ya_no_bloquea(settings, limits, cost):
    todas = flags([anuncio("Announcement on the Price Volatility of Dogecoin (DOGE)")], BASES)
    estado = replace(make_state(), event_flags=event_flags(todas, T + 30 * HORA_MS, WHITELIST))
    assert cribar("DOGE/USDC", estado, settings, limits, cost).passed


def test_solo_las_criticas_mandan_salir_a_mercado():
    todas = flags([anuncio("OKX to delist NEAR", id_="d"),
                   anuncio("Announcement on the Price Volatility of Dogecoin (DOGE)", id_="v"),
                   anuncio("OKX to suspend XRP/USDC spot trading", id_="s")], BASES)
    assert pares_criticos(todas, T + HORA_MS, WHITELIST) == {"NEAR/USDC", "XRP/USDC"}


def test_sin_avisos_el_filtro_ve_lo_mismo_que_hoy():
    assert event_flags([], T, WHITELIST) == {}
    assert pares_criticos([], T, WHITELIST) == frozenset()
