"""De la conciliacion a las peticiones (execution/plan.py), con la conciliacion y ccxt DE VERDAD.

Las fotos (lo local y lo de OKX) se pasan por `conciliar`, y lo que sale por `planear`: se prueba el
camino entero, no un `Resultado` hecho a mano.
"""

from __future__ import annotations

from core.config import load_settings
from execution import ids
from execution.conciliacion import Accion, Exchange, Local, OcoEx, OrdenEx, Paso, PosicionLocal, Resultado, conciliar
from execution.plan import CANCELAR_OCO, CANCELAR_RESTO, CREAR_OCO, planear
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS
from tests.unit.test_execution_peticiones import EX

WHITELIST = load_settings().whitelist
LOTES = {s: i.lot_size for s, i in INSTRUMENTS.items()}
T0 = 1_790_035_200_000
ETH = make_decision_id("ETH/USDC", "pullback_trend", T0)
SOL = make_decision_id("SOL/USDC", "range_breakout", T0)
PRECIOS = {ETH: (2515.0, 2808.0), SOL: (145.0, 162.0)}


def plan_de(local, ex, precios=PRECIOS):
    return planear(conciliar(local, ex, lotes=LOTES), precios=precios, ex=EX, whitelist=WHITELIST)


def test_una_posicion_sin_oco_recibe_su_oco_por_lo_que_hay():
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057),))
    p = plan_de(local, Exchange(saldos={"ETH": 0.0057}, usdc=35.0))
    [envio] = p.envios
    assert envio.que == CREAR_OCO and envio.decision_id == ETH
    assert envio.peticion["algoClOrdId"] == ids.algo_cl_ord_id(ETH) and envio.peticion["tdMode"] == "cash"
    assert float(envio.peticion["sz"]) == 0.0057
    assert float(envio.peticion["slTriggerPx"]) == 2515.0 and float(envio.peticion["tpTriggerPx"]) == 2808.0
    assert p.sin_proteger == {}


def test_una_oco_que_no_cubre_se_cancela_antes_de_crear_la_buena():
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057),))
    ex = Exchange(saldos={"ETH": 0.0057}, usdc=35.0,
                  ocos=(OcoEx(ids.algo_cl_ord_id(ETH), "ETH/USDC", 0.0030, "live"),))
    p = plan_de(local, ex)
    assert [e.que for e in p.envios] == [CANCELAR_OCO, CREAR_OCO]
    assert p.envios[0].peticion == {"instId": "ETH-USDC", "algoClOrdId": ids.algo_cl_ord_id(ETH)}
    assert float(p.envios[1].peticion["sz"]) == 0.0057


def test_una_oco_que_cubre_no_genera_nada():
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057),))
    ex = Exchange(saldos={"ETH": 0.0057}, usdc=35.0,
                  ocos=(OcoEx(ids.algo_cl_ord_id(ETH), "ETH/USDC", 0.0057, "live"),))
    p = plan_de(local, ex)
    assert p.envios == [] and p.sin_proteger == {}


def test_sin_stop_ni_objetivo_no_se_inventan_y_se_avisa_sin_parar_a_las_demas():
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057), PosicionLocal(SOL, "SOL/USDC", 0.1)))
    p = plan_de(local, Exchange(saldos={"ETH": 0.0057, "SOL": 0.1}, usdc=20.0), precios={SOL: PRECIOS[SOL]})
    assert [e.decision_id for e in p.envios] == [SOL]
    assert ETH in p.sin_proteger and "sin stop" in p.sin_proteger[ETH]


def test_si_la_guardia_rechaza_una_oco_las_demas_salen():
    """Stop por encima del objetivo: la guardia no la deja salir; la otra posicion si se protege."""
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057), PosicionLocal(SOL, "SOL/USDC", 0.1)))
    malos = {ETH: (2900.0, 2808.0), SOL: PRECIOS[SOL]}
    p = plan_de(local, Exchange(saldos={"ETH": 0.0057, "SOL": 0.1}, usdc=20.0), precios=malos)
    assert [e.decision_id for e in p.envios] == [SOL]
    assert "guardia" in p.sin_proteger[ETH]


def test_lo_que_solo_toca_lo_local_no_manda_nada():
    """Una entrada que se lleno sin que el bot lo viera: se apunta el llenado y se protege."""
    from execution.conciliacion import EntradaLocal
    local = Local(entradas=(EntradaLocal(ETH, "ETH/USDC", 0.0057),))
    ex = Exchange(saldos={"ETH": 0.0057}, usdc=35.0,
                  ordenes=(OrdenEx(ids.cl_ord_id(ETH), "ETH/USDC", 0.0057, 0.0057, "filled"),))
    p = plan_de(local, ex)
    assert [x.accion for x in p.locales] == [Accion.APUNTAR_LLENADO]
    assert [e.que for e in p.envios] == [CREAR_OCO]


def test_una_accion_desconocida_para_en_seco():
    import pytest
    r = Resultado(acciones=[Paso("inventada", ETH, "ETH/USDC")])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        planear(r, precios=PRECIOS, ex=EX, whitelist=WHITELIST)


def test_una_entrada_a_medias_se_cancela_lo_primero_y_no_se_crea_otra_oco():
    """Decision del propietario del 02/10: la cancelacion del resto va delante de todo (es lo que da el stop a lo llenado)."""
    from execution.conciliacion import EntradaLocal
    local = Local(posiciones=(PosicionLocal(ETH, "ETH/USDC", 0.0057),),
                  entradas=(EntradaLocal(SOL, "SOL/USDC", 0.1),))
    ex = Exchange(saldos={"ETH": 0.0057, "SOL": 0.04}, usdc=20.0,
                  ordenes=(OrdenEx(ids.cl_ord_id(SOL), "SOL/USDC", 0.1, 0.04, "partially_filled"),))
    p = plan_de(local, ex)
    assert [(e.que, e.decision_id) for e in p.envios] == [(CANCELAR_RESTO, SOL), (CREAR_OCO, ETH)]
    assert p.envios[0].peticion == {"instId": "SOL-USDC", "clOrdId": ids.cl_ord_id(SOL)}
    assert p.sin_proteger == {}
