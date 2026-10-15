"""Modelo de costes.

Dos clases de test, porque atrapan cosas distintas:

  * **numeros calculados a mano**, para las formulas: si alguien cambia como se
    cuenta el spread o la comision de salida, estos se ponen rojos con el
    numero exacto que ha cambiado;
  * **propiedades**, para lo que no se me ocurrio: que taker nunca salga mas
    barato que maker, que mas spread nunca cueste menos, que el objetivo
    minimo devuelto cumpla de verdad la desigualdad de la que sale.

Las comisiones que se usan son las REALES medidas el 22/09/2026 con ccxt:
maker 0,10 %, taker 0,15 %.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strategy.costs import (
    MAX_FEE_AGE_MS,
    CostModel,
    Fees,
    Fill,
    MissingFeeError,
)

NOW_MS = 1_758_549_600_000          # 22/09/2026 14:00 UTC
MAKER = 0.0010
TAKER = 0.0015


def model(
    *,
    maker: float = MAKER,
    taker: float = TAKER,
    age_ms: int = 0,
    symbol: str = "BTC/USDC",
) -> CostModel:
    return CostModel(
        {symbol: Fees(symbol, maker, taker, NOW_MS - age_ms)}, now_ms=NOW_MS
    )


# --------------------------------------------------------------------------
# Las comisiones vienen del exchange, no del codigo
# --------------------------------------------------------------------------


def test_sin_fila_no_hay_precio():
    with pytest.raises(MissingFeeError, match="sin comisiones"):
        model().round_trip("ETH/USDC", 0.02)


def test_comisiones_caducadas_se_rechazan():
    """La ingesta refresca el catalogo en cada arranque. Una fila de hace mas
    de una semana significa que nadie ha releido las comisiones, y OKX las
    cambia el 25/09/2026."""
    viejo = model(age_ms=MAX_FEE_AGE_MS + 1)
    with pytest.raises(MissingFeeError, match="refrescar el catalogo"):
        viejo.round_trip("BTC/USDC", 0.02)


def test_comisiones_recien_leidas_valen():
    assert model(age_ms=MAX_FEE_AGE_MS - 1).knows("BTC/USDC")


def test_knows_no_lanza():
    assert model().knows("BTC/USDC") is True
    assert model().knows("DOGE/USDC") is False


def test_comision_negativa_es_un_error():
    with pytest.raises(ValueError, match="comision maker invalida"):
        Fees("BTC/USDC", -0.001, TAKER, NOW_MS)


def test_from_repo_lee_la_tabla_instruments(db):
    """La fuente de verdad es la tabla, no una constante."""
    from data.store.repos import InstrumentRepo

    repo = InstrumentRepo(db)
    db.executemany_sync(
        """
        INSERT INTO instruments
            (symbol, base, quote, active, tick_size, lot_size, min_amount,
             min_cost, maker_fee, taker_fee, raw, fetched_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("BTC/USDC", "BTC", "USDC", 1, 0.1, 1e-8, 0.0001, None,
             MAKER, TAKER, "{}", NOW_MS),
            # Sin comisiones: NO se carga, para que el fallo salga por su nombre.
            ("ETH/USDC", "ETH", "USDC", 1, 0.01, 1e-6, 0.001, None,
             None, None, "{}", NOW_MS),
        ],
    )

    cost = CostModel.from_repo(repo, now_ms=NOW_MS)
    assert cost.knows("BTC/USDC")
    assert not cost.knows("ETH/USDC")
    with pytest.raises(MissingFeeError, match="ETH/USDC"):
        cost.round_trip("ETH/USDC", 0.02)


def test_from_repo_filtra_por_simbolos(db):
    from data.store.repos import InstrumentRepo

    repo = InstrumentRepo(db)
    db.executemany_sync(
        """
        INSERT INTO instruments
            (symbol, base, quote, active, tick_size, lot_size, min_amount,
             min_cost, maker_fee, taker_fee, raw, fetched_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("BTC/USDC", "BTC", "USDC", 1, 0.1, 1e-8, 0.0001, None,
             MAKER, TAKER, "{}", NOW_MS),
            ("ADA/USDC", "ADA", "USDC", 1, 0.0001, 0.001, 10.0, None,
             MAKER, TAKER, "{}", NOW_MS),
        ],
    )
    cost = CostModel.from_repo(repo, now_ms=NOW_MS, symbols=["BTC/USDC"])
    assert cost.knows("BTC/USDC")
    assert not cost.knows("ADA/USDC")


# --------------------------------------------------------------------------
# Las formulas, con numeros a mano
# --------------------------------------------------------------------------


def test_ida_y_vuelta_por_defecto_es_maker_entrada_taker_salida():
    """0,10 % de entrada + 0,15 % de salida + medio spread de 0,02 %."""
    c = model().round_trip("BTC/USDC", 0.02)
    assert c.entry_fill is Fill.MAKER
    assert c.exit_fill is Fill.TAKER
    assert c.entry_fee_pct == pytest.approx(0.10)
    assert c.exit_fee_pct == pytest.approx(0.15)
    assert c.entry_spread_pct == pytest.approx(0.0)
    assert c.exit_spread_pct == pytest.approx(0.01)
    assert c.total_pct == pytest.approx(0.26)


def test_la_pata_maker_no_paga_spread():
    """Pones tu precio: o te llenan ahi o no hay operacion."""
    c = model().round_trip(
        "BTC/USDC", 0.08, entry_fill=Fill.MAKER, exit_fill=Fill.MAKER
    )
    assert c.slippage_pct == 0.0
    assert c.total_pct == pytest.approx(0.20)


def test_las_dos_patas_taker_pagan_el_spread_entero():
    c = model().round_trip(
        "BTC/USDC", 0.02, entry_fill=Fill.TAKER, exit_fill=Fill.TAKER
    )
    assert c.slippage_pct == pytest.approx(0.02)
    assert c.total_pct == pytest.approx(0.32)


def test_la_comision_de_salida_crece_con_el_movimiento():
    """Se cobra sobre el nocional de SALIDA: si el objetivo esta un 6,66 %
    arriba, esa comision es un 6,66 % mayor."""
    c = model().round_trip("BTC/USDC", 0.02, exit_move_pct=6.66)
    assert c.exit_fee_pct == pytest.approx(0.15 * 1.0666)
    assert c.total_pct == pytest.approx(0.26999, abs=1e-5)


def test_coste_en_dolares():
    c = model().round_trip("BTC/USDC", 0.02)
    assert c.usd(15.0) == pytest.approx(15.0 * 0.0026)


def test_spread_negativo_es_un_error():
    with pytest.raises(ValueError, match="spread negativo"):
        model().round_trip("BTC/USDC", -0.01)


# --------------------------------------------------------------------------
# Objetivo minimo (la parte circular)
# --------------------------------------------------------------------------


def test_objetivo_minimo_a_mano():
    """A = 0,10 + 0,01 = 0,11; B = 0,15; t = 3(A+B)/(1 - 3B/100)."""
    t = model().min_target_pct("BTC/USDC", 0.02, ratio=3.0)
    assert t == pytest.approx(3 * 0.26 / (1 - 0.0045))
    assert t == pytest.approx(0.783526, abs=1e-6)


def test_el_objetivo_minimo_cumple_su_propia_desigualdad():
    """La comprobacion que importa: sustituir el resultado y ver que sale 3x.

    Es circular a proposito (el coste depende del objetivo), y una formula mal
    despejada da un numero que parece razonable pero no cumple.
    """
    cost = model()
    t = cost.min_target_pct("BTC/USDC", 0.02, ratio=3.0)
    real = cost.round_trip("BTC/USDC", 0.02, exit_move_pct=t).total_pct
    assert t / real == pytest.approx(3.0)


def test_breakeven_es_el_objetivo_minimo_con_ratio_uno():
    cost = model()
    assert cost.breakeven_move_pct("BTC/USDC", 0.02) == pytest.approx(
        cost.min_target_pct("BTC/USDC", 0.02, ratio=1.0)
    )


def test_ratio_no_positivo_es_un_error():
    with pytest.raises(ValueError, match="ratio no positivo"):
        model().min_target_pct("BTC/USDC", 0.02, ratio=0.0)


def test_la_tabla_no_lleva_nada_que_no_sean_numeros():
    fila = model().as_table()[0]
    assert set(fila) == {"symbol", "maker_pct", "taker_pct", "age_hours"}
    assert fila["maker_pct"] == pytest.approx(0.10)
    assert fila["taker_pct"] == pytest.approx(0.15)


# --------------------------------------------------------------------------
# Propiedades
# --------------------------------------------------------------------------

spreads = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
fee_rates = st.floats(min_value=0.0, max_value=0.01, allow_nan=False)


@given(spread=spreads)
def test_taker_nunca_sale_mas_barato_que_maker(spread: float):
    cost = model()
    barato = cost.round_trip(
        "BTC/USDC", spread, entry_fill=Fill.MAKER, exit_fill=Fill.MAKER
    )
    caro = cost.round_trip(
        "BTC/USDC", spread, entry_fill=Fill.TAKER, exit_fill=Fill.TAKER
    )
    assert caro.total_pct >= barato.total_pct


@given(a=spreads, b=spreads)
def test_mas_spread_nunca_cuesta_menos(a: float, b: float):
    cost = model()
    low, high = sorted((a, b))
    assert (
        cost.round_trip("BTC/USDC", high).total_pct
        >= cost.round_trip("BTC/USDC", low).total_pct
    )


@given(spread=spreads, maker=fee_rates, taker=fee_rates)
def test_el_coste_nunca_es_negativo_ni_nan(spread, maker, taker):
    total = model(maker=maker, taker=taker).round_trip("BTC/USDC", spread).total_pct
    assert total >= 0.0
    assert not math.isnan(total)


@given(spread=spreads, ratio=st.floats(min_value=0.5, max_value=10.0))
def test_el_objetivo_minimo_siempre_cumple_el_ratio(spread: float, ratio: float):
    cost = model()
    t = cost.min_target_pct("BTC/USDC", spread, ratio=ratio)
    real = cost.round_trip("BTC/USDC", spread, exit_move_pct=t).total_pct
    assert t / real == pytest.approx(ratio, rel=1e-9)


@given(spread=spreads, notional=st.floats(min_value=1.0, max_value=1000.0))
def test_el_coste_en_dolares_escala_con_el_nocional(spread, notional):
    c = model().round_trip("BTC/USDC", spread)
    assert c.usd(notional) == pytest.approx(notional * c.total_pct / 100.0)
