"""Las reglas duras con el estado del demo antes de copiar (`execution/riesgo.py`; decision 2 del 02/10), sin red."""

from __future__ import annotations

import pytest

from core.config import load_settings
from core.modes import Mode
from execution import riesgo
from execution.espejo import OrdenPapel
from execution.riesgo import CierreDemo, EntradaDemo, Mercado, PosicionDemo, aprobar, estado
from portfolio.loop import TradingLoop
from risk.equity import EquityBreakdown
from tests.risk_fixtures import INSTRUMENTS, independent_pairs

S = load_settings()
T0 = 1_790_352_000_000 + 4 * 3600_000 + 5_000      # poco despues del cierre de la vela de las 16:00
BTC = INSTRUMENTS["BTC/USDC"]
ENTRADA, STOP, OBJETIVO = 80_000.0, 77_400.0, 88_000.0
MERCADO = Mercado(bids={s: 1.0 for s in INSTRUMENTS} | {"BTC/USDC": 80_500.0}, correlaciones=independent_pairs(),
                  usdc_desviacion_pct=0.01, flags={})


def equity(usd, fiable=True):
    return EquityBreakdown(free_quote_usd=usd, positions_value_usd=0.0, exit_fees_usd=0.0,
                           stale_symbols=() if fiable else ("SOL/USDC",))


def orden(cantidad, did="d-20260925T1600-btc-pb"):
    return OrdenPapel(did, "BTC/USDC", cantidad, ENTRADA, STOP, OBJETIVO, T0 - 4 * 3600_000 - 5_000, "pending",
                      "pullback_trend")


def foto(usd=50.0, modo=Mode.NORMAL, posiciones=(), entradas=(), cierres=(), mercado=MERCADO):
    return estado(ahora_ms=T0, equity=equity(usd), modo=modo, posiciones=posiciones, entradas=entradas,
                  cierres=cierres, mercado=mercado)


def lo_que_aprueba_el_motor(usd):
    """La cantidad que el motor da con ese equity (como la cartera de papel con el suyo)."""
    a = aprobar(orden(1.0), foto(usd), equity(usd), instrumento=BTC, spread_pct=0.004, settings=S)
    assert a.veredicto is not None and a.veredicto.approved
    return a.veredicto.qty


def test_con_el_mismo_equity_sale_la_misma_cantidad_que_en_papel():
    papel = lo_que_aprueba_el_motor(50.0)
    a = aprobar(orden(papel), foto(50.0), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert a.enviar and a.cantidad == pytest.approx(papel, abs=BTC.lot_size) and a.motivo == "aprobada"


def test_si_el_demo_tiene_menos_manda_la_regla_12():
    papel = lo_que_aprueba_el_motor(50.0)
    a = aprobar(orden(papel), foto(48.0), equity(48.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert a.enviar and a.cantidad < papel and "el motor del demo aprueba" in a.motivo
    assert a.cantidad <= a.veredicto.qty + 1e-12


def test_nunca_mas_de_lo_que_pide_el_papel():
    papel = lo_que_aprueba_el_motor(50.0) / 2
    a = aprobar(orden(papel), foto(50.0), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert a.cantidad <= papel + 1e-12


def test_el_modo_del_ejecutor_veta():
    for modo in (Mode.CLOSE_ONLY_CAPITAL, Mode.CLOSE_ONLY_DAILY, Mode.CLOSE_ONLY_DEGRADED, Mode.HALTED):
        a = aprobar(orden(0.0002), foto(modo=modo), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
        assert not a.enviar and "estado del demo" in a.motivo, modo


def test_la_regla_4_cuenta_lo_que_tiene_el_demo():
    e = tuple(EntradaDemo(f"d-20260925T1600-{x}-pb", f"{x.upper()}/USDC", 1.0, 1.0, 0.97, T0 - 3600_000)
              for x in ("eth", "sol", "doge"))
    a = aprobar(orden(0.0002), foto(entradas=e), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and 4 in a.veredicto.veto_numbers


def test_la_regla_10_con_las_perdidas_del_dia_del_demo():
    c = tuple(CierreDemo(f"d-20260925T{h}00-eth-pb", "ETH/USDC", T0 - 3600_000, -1.1, True) for h in ("08", "12", "13"))
    a = aprobar(orden(0.0002), foto(cierres=c), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and 10 in a.veredicto.veto_numbers


def test_el_mercado_tambien_cuenta_paridad_desconocida_veta():
    sin_paridad = Mercado(MERCADO.bids, MERCADO.correlaciones, None, {})
    a = aprobar(orden(0.0002), foto(mercado=sin_paridad), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and 17 in a.veredicto.veto_numbers


def test_una_posicion_del_demo_en_el_simbolo_veta():
    p = (PosicionDemo("d-20260925T0800-btc-pb", "BTC/USDC", 0.0002, 79_000.0, 76_500.0, 85_000.0, T0 - 8 * 3600_000),)
    a = aprobar(orden(0.0002), foto(posiciones=p), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and 4 in a.veredicto.veto_numbers


def test_sin_equity_fiable_no_se_copia_nada():
    a = aprobar(orden(0.0002), foto(), equity(50.0, fiable=False), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and "no fiable" in a.motivo and a.veredicto is None


def test_la_memoria_de_la_regla_14_es_la_del_papel():
    assert riesgo.MEMORIA == TradingLoop.RECENT_MEMORY



def test_la_cantidad_del_papel_llega_entera_a_la_peticion():
    """03/10: 0,006178 ETH (lote 0,000001) salia como 0,0061779999... y ccxt la truncaba a 0,006177."""
    from tests.okx_simulado import OkxSimulado
    ok = OkxSimulado({}, {}, [0])
    eth = INSTRUMENTS["ETH/USDC"]
    ins = type(eth)("ETH/USDC", 1.0, 1e-6, 0.001, eth.maker_fee, eth.taker_fee)
    o = OrdenPapel("d-20261002T1200-eth-pb", "ETH/USDC", 0.006178, 2687.0, 2625.0, 2900.0, T0, "filled", "pullback_trend")
    m = Mercado(bids={s: 1.0 for s in INSTRUMENTS}, correlaciones=independent_pairs(), usdc_desviacion_pct=0.01, flags={})
    a = aprobar(o, foto(mercado=m), equity(50.0), instrumento=ins, spread_pct=0.01, settings=S)
    assert a.enviar and a.cantidad == 0.006178
    assert ok.amount_to_precision("ETH/USDC", a.cantidad) == "0.006178"


def test_una_flag_de_noticias_puesta_despues_de_la_vela_veta_la_copia():
    """Revision del 15/10: las flags se miran otra vez justo antes de enviar (ninguna regla dura las mira)."""
    con_flag = Mercado(MERCADO.bids, MERCADO.correlaciones, MERCADO.usdc_desviacion_pct, {"BTC/USDC": ("delisting",)})
    a = aprobar(orden(0.0002), foto(mercado=con_flag), equity(50.0), instrumento=BTC, spread_pct=0.004, settings=S)
    assert not a.enviar and "noticias" in a.motivo
    otra = Mercado(MERCADO.bids, MERCADO.correlaciones, MERCADO.usdc_desviacion_pct, {"ETH/USDC": ("delisting",)})
    assert aprobar(orden(0.0002), foto(mercado=otra), equity(50.0), instrumento=BTC, spread_pct=0.004,
                   settings=S).enviar


@pytest.mark.parametrize("lotes", [1, 2, 3, 7, 199, 6178, 6177.9999999, 6178.0000001, 2.5, 0.9999999999])
def test_el_redondeo_nunca_pasa_de_lo_aprobado_mas_que_el_ruido(lotes):
    """Revision del 15/10 (hallazgo 9): el +1e-9 del redondeo sube como mucho 1e-9 lotes sobre lo aprobado, nunca un
    lote; y nunca baja mas de un lote (el error del 03/10)."""
    eth = INSTRUMENTS["ETH/USDC"]
    ins = type(eth)("ETH/USDC", 1.0, 1e-6, 1e-6, eth.maker_fee, eth.taker_fee)
    pedido = lotes * 1e-6
    o = OrdenPapel("d-20261002T1200-eth-pb", "ETH/USDC", pedido, 2687.0, 2625.0, 2900.0, T0, "filled", "pullback_trend")
    m = Mercado(bids={s: 1.0 for s in INSTRUMENTS}, correlaciones=independent_pairs(), usdc_desviacion_pct=0.01, flags={})
    a = aprobar(o, foto(mercado=m), equity(50.0), instrumento=ins, spread_pct=0.01, settings=S)
    if not a.enviar:
        assert "por debajo del minimo" in a.motivo
        return
    tope = min(pedido, a.veredicto.qty)
    assert a.cantidad <= tope + 1e-9 * ins.lot_size + 1e-15
    assert a.cantidad > tope - ins.lot_size
