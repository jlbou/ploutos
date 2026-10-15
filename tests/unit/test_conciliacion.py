"""La conciliacion (`execution/conciliacion.py`): los casos de caos del disenyo de la fase 4.

Cada test es una fila de la tabla de caos de docs/archivo/diseno-fase-4.md (seccion 4) o un caso
de la decision 5 del propietario (que es un descuadre). Fotos inventadas, sin red.
"""

from __future__ import annotations

from execution import ids
from execution.conciliacion import (
    Accion, Descuadre, EntradaLocal, Exchange, Local, OcoEx, OrdenEx, PosicionLocal, conciliar,
)
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS

T0 = 1_790_035_200_000
NEAR = make_decision_id("NEAR/USDC", "pullback_trend", T0)
SOL = make_decision_id("SOL/USDC", "range_breakout", T0)
LOTES = {s: i.lot_size for s, i in INSTRUMENTS.items()}


def oco(did, simbolo, cantidad, estado="live", pata=None, precio=None):
    return OcoEx(ids.algo_cl_ord_id(did), simbolo, cantidad, estado, pata, precio)


def orden(did, simbolo, cantidad, llenado=0.0, estado="live"):
    return OrdenEx(ids.cl_ord_id(did), simbolo, cantidad, llenado, estado)


def acciones(r):
    return [(p.accion, p.decision_id) for p in r.acciones]


def tipos(r):
    return [f.tipo for f in r.descuadres]


# --------------------------------------------------------------------------
# Lo normal: todo cuadra
# --------------------------------------------------------------------------


def test_posicion_con_su_oco_y_saldos_iguales_cuadra():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0, ocos=(oco(NEAR, "NEAR/USDC", 5.0),))
    r = conciliar(local, ex, lotes=LOTES)
    assert r.cuadra and r.acciones == [] and r.sin_oco == frozenset()


def test_entrada_pendiente_viva_cuadra():
    local = Local(entradas=(EntradaLocal(SOL, "SOL/USDC", 0.1),), usdc=50.0)
    ex = Exchange(saldos={}, usdc=50.0, ordenes=(orden(SOL, "SOL/USDC", 0.1),))
    r = conciliar(local, ex, lotes=LOTES)
    assert r.cuadra and r.acciones == []


# --------------------------------------------------------------------------
# La tabla de caos (diseno-fase-4, seccion 4)
# --------------------------------------------------------------------------


def test_matar_el_proceso_justo_despues_de_enviar_la_entrada_la_encuentra_por_su_id():
    """Ni duplicada ni perdida: se adopta la que ya esta en OKX."""
    r = conciliar(Local(usdc=50.0), Exchange(saldos={}, usdc=50.0,
                                               ordenes=(orden(SOL, "SOL/USDC", 0.1),)), lotes=LOTES)
    assert acciones(r) == [(Accion.ADOPTAR_ENTRADA, SOL)]
    assert r.cuadra, "explicado en la misma pasada: no es un descuadre"


def test_matarlo_con_la_entrada_llenada_y_sin_oco_crea_la_oco():
    local = Local(entradas=(EntradaLocal(NEAR, "NEAR/USDC", 5.0),), usdc=50.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0,
                  ordenes=(orden(NEAR, "NEAR/USDC", 5.0, 5.0, "filled"),))
    r = conciliar(local, ex, lotes=LOTES)
    assert acciones(r) == [(Accion.APUNTAR_LLENADO, NEAR), (Accion.CREAR_OCO, NEAR)]
    assert r.cuadra and r.sin_oco == {NEAR}
    assert not any(f.tipo is Descuadre.SALDO_USDC for f in r.descuadres), \
        "hubo un llenado: la caja local se pone al dia al aplicarlo"


def test_si_a_la_pasada_siguiente_sigue_sin_oco_es_un_descuadre():
    """Decision 5: una posicion sin OCO durante mas de una pasada."""
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0)
    r = conciliar(local, ex, lotes=LOTES, sin_oco_antes=frozenset({NEAR}))
    assert (Accion.CREAR_OCO, NEAR) in acciones(r)
    assert tipos(r) == [Descuadre.SIN_OCO_REPETIDO]


def test_llenado_parcial_se_cancela_el_resto_y_no_se_crea_otra_oco():
    """Decision del propietario del 02/10: OKX crea la OCO adjunta por lo llenado al cancelar el resto (prueba 4 del demo).
    Una OCO propia con el mismo `algoClOrdId` chocaria con la de OKX."""
    local = Local(entradas=(EntradaLocal(NEAR, "NEAR/USDC", 5.0),), usdc=50.0)
    ex = Exchange(saldos={"NEAR": 2.0}, usdc=44.0,
                  ordenes=(orden(NEAR, "NEAR/USDC", 5.0, 2.0, "partially_filled"),))
    r = conciliar(local, ex, lotes=LOTES)
    [llenado, cancelar] = r.acciones
    assert (llenado.accion, llenado.cantidad) == (Accion.APUNTAR_LLENADO, 2.0)
    assert (cancelar.accion, cancelar.cantidad) == (Accion.CANCELAR_RESTO, 3.0)
    assert r.cuadra and r.sin_oco == {NEAR}, "sin OCO en esta pasada: la siguiente tiene que verla"


def test_tras_cancelar_el_resto_la_oco_de_okx_cubre_lo_llenado():
    local = Local(entradas=(EntradaLocal(NEAR, "NEAR/USDC", 5.0),), usdc=50.0)
    ex = Exchange(saldos={"NEAR": 2.0}, usdc=44.0,
                  ordenes=(orden(NEAR, "NEAR/USDC", 5.0, 2.0, "canceled"),), ocos=(oco(NEAR, "NEAR/USDC", 2.0),))
    r = conciliar(local, ex, lotes=LOTES, sin_oco_antes=frozenset({NEAR}))
    assert acciones(r) == [(Accion.APUNTAR_LLENADO, NEAR)] and r.cuadra and r.sin_oco == frozenset()


def test_si_okx_no_creo_la_oco_al_cancelar_se_crea_la_propia_y_es_un_descuadre():
    local = Local(entradas=(EntradaLocal(NEAR, "NEAR/USDC", 5.0),), usdc=50.0)
    ex = Exchange(saldos={"NEAR": 2.0}, usdc=44.0, ordenes=(orden(NEAR, "NEAR/USDC", 5.0, 2.0, "canceled"),))
    r = conciliar(local, ex, lotes=LOTES, sin_oco_antes=frozenset({NEAR}))
    assert (Accion.CREAR_OCO, NEAR) in acciones(r)
    assert tipos(r) == [Descuadre.SIN_OCO_REPETIDO]


def test_si_el_resto_sigue_vivo_a_la_pasada_siguiente_es_un_descuadre():
    """La cancelacion no llego: lo llenado sigue sin stop. Se vuelve a cancelar y se avisa."""
    local = Local(entradas=(EntradaLocal(NEAR, "NEAR/USDC", 5.0),), usdc=50.0)
    ex = Exchange(saldos={"NEAR": 2.0}, usdc=44.0,
                  ordenes=(orden(NEAR, "NEAR/USDC", 5.0, 2.0, "partially_filled"),))
    r = conciliar(local, ex, lotes=LOTES, sin_oco_antes=frozenset({NEAR}))
    assert (Accion.CANCELAR_RESTO, NEAR) in acciones(r) and (Accion.CREAR_OCO, NEAR) not in acciones(r)
    assert tipos(r) == [Descuadre.SIN_OCO_REPETIDO]


def test_una_entrada_adoptada_a_medias_tambien_se_cancela():
    ex = Exchange(saldos={"SOL": 0.04}, usdc=44.0, ordenes=(orden(SOL, "SOL/USDC", 0.1, 0.04, "partially_filled"),))
    r = conciliar(Local(usdc=50.0), ex, lotes=LOTES)
    assert acciones(r) == [(Accion.ADOPTAR_ENTRADA, SOL), (Accion.APUNTAR_LLENADO, SOL),
                           (Accion.CANCELAR_RESTO, SOL)]
    assert r.cuadra


def test_la_oco_que_cubre_menos_de_lo_que_hay_se_ajusta():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0, ocos=(oco(NEAR, "NEAR/USDC", 2.0),))
    r = conciliar(local, ex, lotes=LOTES)
    assert acciones(r) == [(Accion.AJUSTAR_OCO, NEAR)] and r.cuadra


def test_cancelar_a_mano_la_oco_desde_la_web_la_vuelve_a_crear():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0,
                  ocos=(oco(NEAR, "NEAR/USDC", 5.0, "canceled"),))
    r = conciliar(local, ex, lotes=LOTES)
    assert acciones(r) == [(Accion.CREAR_OCO, NEAR)] and r.cuadra


def test_la_oco_salto_mientras_el_proceso_no_estaba_y_se_cierra_en_local():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={}, usdc=45.5,
                  ocos=(oco(NEAR, "NEAR/USDC", 5.0, "effective", "tp", 3.1),))
    r = conciliar(local, ex, lotes=LOTES)
    [paso] = r.acciones
    assert paso.accion is Accion.CERRAR_LOCAL and "tp" in paso.detalle
    assert r.cuadra


def test_la_entrada_que_nunca_llego_se_olvida():
    local = Local(entradas=(EntradaLocal(SOL, "SOL/USDC", 0.1),), usdc=50.0)
    r = conciliar(local, Exchange(saldos={}, usdc=50.0), lotes=LOTES)
    assert acciones(r) == [(Accion.OLVIDAR_ENTRADA, SOL)] and r.cuadra


def test_la_entrada_caducada_sin_llenar_se_olvida():
    local = Local(entradas=(EntradaLocal(SOL, "SOL/USDC", 0.1),), usdc=50.0)
    ex = Exchange(saldos={}, usdc=50.0, ordenes=(orden(SOL, "SOL/USDC", 0.1, 0.0, "canceled"),))
    assert acciones(conciliar(local, ex, lotes=LOTES)) == [(Accion.OLVIDAR_ENTRADA, SOL)]


def test_una_oco_nuestra_sin_posicion_local_se_adopta():
    """Gana el exchange: la posicion existe aunque lo local la haya perdido."""
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0, ocos=(oco(NEAR, "NEAR/USDC", 5.0),))
    r = conciliar(Local(usdc=35.0), ex, lotes=LOTES)
    assert acciones(r) == [(Accion.ADOPTAR_POSICION, NEAR)] and r.cuadra


# --------------------------------------------------------------------------
# Lo que NO se explica: descuadres (decision 5)
# --------------------------------------------------------------------------


def test_una_orden_que_no_es_nuestra_es_un_descuadre_y_no_se_toca():
    ex = Exchange(saldos={}, usdc=50.0,
                  ordenes=(OrdenEx("6b9ad766b55dBCDE1b2d8ac3998c7b54", "BTC/USDC", 0.0001, 0.0, "live"),))
    r = conciliar(Local(usdc=50.0), ex, lotes=LOTES)
    assert tipos(r) == [Descuadre.ORDEN_AJENA] and r.acciones == []


def test_una_oco_que_no_es_nuestra_es_un_descuadre():
    ex = Exchange(saldos={}, usdc=50.0, ocos=(OcoEx("manual123", "BTC/USDC", 0.0001, "live"),))
    assert tipos(conciliar(Local(usdc=50.0), ex, lotes=LOTES)) == [Descuadre.OCO_AJENA]


def test_la_moneda_desaparece_sin_que_salte_la_oco_es_un_descuadre():
    """Alguien vendio a mano (o algo peor): se cierra en local, pero se avisa."""
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    r = conciliar(local, Exchange(saldos={}, usdc=50.0), lotes=LOTES)
    assert tipos(r) == [Descuadre.CIERRE_SIN_EXPLICAR]
    assert acciones(r) == [(Accion.CERRAR_LOCAL, NEAR)]


def test_un_saldo_de_moneda_que_no_cuadra_es_un_descuadre():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 6.0}, usdc=35.0, ocos=(oco(NEAR, "NEAR/USDC", 5.0),))
    assert tipos(conciliar(local, ex, lotes=LOTES)) == [Descuadre.SALDO_BASE]


def test_media_unidad_de_lote_de_diferencia_no_es_un_descuadre():
    lote = LOTES["XRP/USDC"]
    xrp = make_decision_id("XRP/USDC", "pullback_trend", T0)
    local = Local(posiciones=(PosicionLocal(xrp, "XRP/USDC", 30.0),), usdc=35.0)
    ex = Exchange(saldos={"XRP": 30.0 + lote * 0.4}, usdc=35.0, ocos=(oco(xrp, "XRP/USDC", 30.0),))
    assert conciliar(local, ex, lotes=LOTES).cuadra


def test_usdc_que_no_cuadra_sin_nada_que_lo_explique_es_un_descuadre():
    r = conciliar(Local(usdc=50.0), Exchange(saldos={}, usdc=49.0), lotes=LOTES)
    assert tipos(r) == [Descuadre.SALDO_USDC]
    assert conciliar(Local(usdc=50.0), Exchange(saldos={}, usdc=49.995), lotes=LOTES).cuadra, \
        "menos de un centimo: redondeos"


# --------------------------------------------------------------------------
# La venta a mercado de salida (flag critica, "cerrar todo"; decision del 02/10)
# --------------------------------------------------------------------------


def test_una_posicion_vendida_por_su_salida_se_cierra_sin_descuadre():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={}, usdc=49.9, ordenes=(OrdenEx(ids.cl_ord_id_salida(NEAR), "NEAR/USDC", 5.0, 5.0, "filled"),),
                  ocos=(oco(NEAR, "NEAR/USDC", 5.0, "canceled"),))
    r = conciliar(local, ex, lotes=LOTES)
    [paso] = r.acciones
    assert paso.accion is Accion.CERRAR_LOCAL and "a mercado" in paso.detalle
    assert r.cuadra


def test_sin_la_salida_la_misma_desaparicion_es_un_descuadre():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={}, usdc=49.9, ocos=(oco(NEAR, "NEAR/USDC", 5.0, "canceled"),))
    assert Descuadre.CIERRE_SIN_EXPLICAR in tipos(conciliar(local, ex, lotes=LOTES))


def test_una_salida_en_curso_no_se_adopta_como_entrada():
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 5.0),), usdc=35.0)
    ex = Exchange(saldos={"NEAR": 5.0}, usdc=35.0,
                  ordenes=(OrdenEx(ids.cl_ord_id_salida(NEAR), "NEAR/USDC", 5.0, 0.0, "live"),),
                  ocos=(oco(NEAR, "NEAR/USDC", 5.0),))
    r = conciliar(local, ex, lotes=LOTES)
    assert (Accion.ADOPTAR_ENTRADA, NEAR) not in acciones(r) and r.cuadra
