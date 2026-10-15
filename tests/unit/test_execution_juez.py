"""El juez de la fase 4 (execution/juez.py): una semana limpia en el demo y cada forma de romperla."""

from __future__ import annotations

from dataclasses import replace

import pytest

from execution import ids
from execution import juez as j

MIN = 60_000
T0 = 1_790_352_000_000                      # 25/09/2026 16:00 UTC
SEMANA = 7 * 24 * 60 * MIN
DID = "d-20260925T1600-btc-pb"
WL = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC", "NEAR/USDC")
LOTES = {s: 0.00001 for s in WL}
QTY, ENTRADA, SALIDA, COM = 0.0002, 80_000.0, 84_000.0, 0.02


def semana(**cambios):
    """Una operacion de BTC en el demo, protegida y cerrada por su OCO, con 7 dias de conciliacion."""
    fin = T0 + SEMANA
    okx = j.Okx(
        ordenes=(j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "post_only", "cash", QTY, QTY, "filled", T0 + MIN),),
        ocos=(j.Oco(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", "cash", QTY, "effective", T0 + 31 * MIN,
                    T0 + 600 * MIN),),
        fills=(j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),
               j.Fill(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", QTY, SALIDA, COM, T0 + 600 * MIN)),
        saldos_inicio={"USDC": 5_000.0, "BTC": 1.0, "USDT": 5_000.0},
        saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA + QTY * SALIDA - COM, "BTC": 1.0, "USDT": 5_000.0},
    )
    bot = j.Bot(operaciones=(j.Operacion(DID, "BTC/USDC", QTY, ENTRADA, QTY, SALIDA),),
                pasadas=tuple(j.Pasada(T0 + i * 5 * MIN) for i in range(SEMANA // (5 * MIN) + 1)))
    args = {"whitelist": WL, "lotes": LOTES, "espejo": {DID}, "hasta_ms": fin}
    for k, val in cambios.items():
        if k in ("ordenes", "ocos", "fills", "saldos_inicio", "saldos_fin"):
            okx = replace(okx, **{k: val})
        elif k in ("operaciones", "pasadas"):
            bot = replace(bot, **{k: val})
        else:
            args[k] = val
    return j.juzgar(okx, bot, **args)


def falla(v, texto):
    return any(texto in f for f in v.fallas)


def test_una_semana_limpia_es_cumplido():
    v = semana()
    assert v.fallas == [] and v.codigo == 0
    assert v.medidas == {"enviadas en papel": 1, "mandadas al demo": 1, "adoptadas": 0, "salidas a mercado": 0,
                         "salidas por precio pasado": 0, "pasadas": 2017, "operaciones completas": 1}


def semana_con_salida(**cambios):
    """La misma operacion cerrada por una VENTA A MERCADO de salida (flag critica, decision del 02/10): la OCO se
    cancela antes y la salida vende lo que hay."""
    sal = ids.cl_ord_id_salida(DID)
    base = {
        "ordenes": (j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "post_only", "cash", QTY, QTY, "filled", T0 + MIN),
                    j.Orden(sal, "BTC/USDC", "sell", "market", "cash", QTY, QTY, "filled", T0 + 600 * MIN)),
        "ocos": (j.Oco(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", "cash", QTY, "canceled", T0 + 31 * MIN,
                       T0 + 600 * MIN - 2000),),
        "fills": (j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),
                  j.Fill(sal, "BTC/USDC", "sell", QTY, SALIDA, COM, T0 + 600 * MIN)),
        "salidas_espejo": {DID},
    }
    return semana(**{**base, **cambios})


def test_una_salida_a_mercado_que_la_ia_hizo_en_papel_es_cumplido():
    v = semana_con_salida()
    assert v.fallas == [] and v.medidas["salidas a mercado"] == 1


def test_una_salida_que_la_ia_no_hizo_en_papel_falla():
    assert falla(semana_con_salida(salidas_espejo=set()), "que la cartera de la IA no hizo en papel")


def test_la_salida_es_una_venta_a_mercado_y_una_sola():
    sal = ids.cl_ord_id_salida(DID)
    entrada = j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "post_only", "cash", QTY, QTY, "filled", T0 + MIN)
    limit = j.Orden(sal, "BTC/USDC", "sell", "limit", "cash", QTY, QTY, "filled", T0 + 600 * MIN)
    assert falla(semana_con_salida(ordenes=(entrada, limit)), "las salidas son ventas a mercado")
    dos = (entrada, replace(limit, tipo="market"), replace(limit, tipo="market", creada_ms=T0 + 601 * MIN))
    assert falla(semana_con_salida(ordenes=dos), "2 ventas de salida")


def test_una_salida_sin_entrada_falla():
    sal = j.Orden(ids.cl_ord_id_salida(DID), "BTC/USDC", "sell", "market", "cash", QTY, QTY, "filled", T0)
    assert falla(semana_con_salida(ordenes=(sal,)), "sin entrada en el demo")


def test_comprar_con_el_id_de_salida_falla():
    sal = ids.cl_ord_id_salida(DID)
    fills = (j.Fill(sal, "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),)
    assert falla(semana_con_salida(fills=fills), "que no sale de donde deberia")


def test_menos_de_una_semana_es_aun_no():
    v = semana(pasadas=tuple(j.Pasada(T0 + i * 5 * MIN) for i in range(100)), hasta_ms=T0 + 500 * MIN)
    assert v.fallas == [] and v.codigo == 2


@pytest.mark.parametrize("cambio, texto", [
    ({"td_mode": "cross"}, "regla 1"),
    ({"simbolo": "XRP/USDC"}, "regla 3"),
    ({"tipo": "limit"}, "compras post-only"),
    ({"lado": "sell"}, "compras post-only"),
])
def test_la_guardia_vista_desde_okx_en_las_entradas(cambio, texto):
    base = j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "post_only", "cash", QTY, QTY, "filled", T0 + MIN)
    v = semana(ordenes=(replace(base, **cambio),))
    assert v.codigo == 1 and falla(v, texto)


@pytest.mark.parametrize("cambio, texto", [
    ({"td_mode": "cross"}, "regla 1"), ({"simbolo": "TRX/USDC"}, "regla 3"), ({"lado": "buy"}, "las OCO venden"),
])
def test_la_guardia_vista_desde_okx_en_las_oco(cambio, texto):
    base = j.Oco(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", "cash", QTY, "effective", T0 + 31 * MIN, T0 + 600 * MIN)
    v = semana(ocos=(replace(base, **cambio),))
    assert v.codigo == 1 and falla(v, texto)


def test_nada_ajeno_y_una_sola_entrada_por_decision():
    buena = j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "post_only", "cash", QTY, QTY, "filled", T0 + MIN)
    ajena = replace(buena, cl_ord_id="manual123", llenado=0, estado="canceled")
    v = semana(ordenes=(buena, ajena))
    assert falla(v, "orden ajena en OKX: manual123")
    v = semana(ordenes=(buena, replace(buena, llenado=0, estado="canceled")))
    assert falla(v, "2 entradas en OKX para una sola decision")
    oco = j.Oco("otraOCO", "BTC/USDC", "sell", "cash", QTY, "canceled", T0, T0 + MIN)
    v = semana(ocos=semana_ocos() + (oco,))
    assert falla(v, "OCO ajena en OKX: otraOCO")


def semana_ocos():
    return (j.Oco(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", "cash", QTY, "effective", T0 + 31 * MIN,
                  T0 + 600 * MIN),)


def test_el_espejo_de_la_cartera_de_la_ia():
    v = semana(espejo=set())
    assert falla(v, "que la cartera de la IA no envio")
    v = semana(espejo={DID, "d-20260925T2000-eth-pb", "d-20260926T0000-sol-rb"})
    assert v.fallas == [] and v.medidas["enviadas en papel"] == 3 and v.medidas["mandadas al demo"] == 1


@pytest.mark.parametrize("creada_min, falla_", [(38, False), (41, True)])
def test_la_oco_llega_como_mucho_dos_pasadas_despues_del_fill(creada_min, falla_):
    oco = replace(semana_ocos()[0], creada_ms=T0 + creada_min * MIN)        # el fill fue a los 30 min
    v = semana(ocos=(oco,))
    assert falla(v, "sin OCO con la posicion abierta") is falla_


@pytest.mark.parametrize("hueco_min, falla_", [(3, False), (15, True)])
def test_una_oco_cancelada_a_mano_y_vuelta_a_crear(hueco_min, falla_):
    primera = replace(semana_ocos()[0], estado="canceled", fin_ms=T0 + 200 * MIN)
    segunda = replace(semana_ocos()[0], creada_ms=T0 + (200 + hueco_min) * MIN)
    v = semana(ocos=(primera, segunda))
    assert falla(v, "sin OCO con la posicion abierta") is falla_


def test_una_posicion_abierta_sin_ninguna_oco():
    v = semana(ocos=(), fills=(j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),),
               saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA, "BTC": 1.0 + QTY, "USDT": 5_000.0},
               operaciones=(j.Operacion(DID, "BTC/USDC", QTY, ENTRADA),))
    assert v.codigo == 1 and falla(v, "sin OCO con la posicion abierta")


def test_la_oco_tiene_que_cubrir_lo_llenado():
    v = semana(ocos=(replace(semana_ocos()[0], cantidad=QTY / 2),))
    assert falla(v, "la OCO cubre 0.0001 y se lleno 0.0002")


@pytest.mark.parametrize("op, texto", [
    (j.Operacion(DID, "BTC/USDC", QTY / 2, ENTRADA, QTY, SALIDA), "entrada de 0.0002 en OKX y 0.0001 en el bot"),
    (j.Operacion(DID, "BTC/USDC", QTY, ENTRADA + 1, QTY, SALIDA), "precio de entrada"),
    (j.Operacion(DID, "BTC/USDC", QTY, ENTRADA, QTY, SALIDA - 5), "precio de salida"),
    (j.Operacion(DID, "BTC/USDC", QTY, ENTRADA), "OKX vendio y el bot la sigue teniendo abierta"),
])
def test_los_fills_contra_lo_que_apunto_el_bot(op, texto):
    v = semana(operaciones=(op,))
    assert v.codigo == 1 and falla(v, texto)


def test_operaciones_que_solo_estan_en_un_lado():
    assert falla(semana(operaciones=()), "OKX tiene fills y el bot no tiene la operacion")
    otra = j.Operacion("d-20260925T2000-eth-pb", "ETH/USDC", 0.01, 2_500.0)
    assert falla(semana(operaciones=(j.Operacion(DID, "BTC/USDC", QTY, ENTRADA, QTY, SALIDA), otra)),
                 "el bot tiene la operacion y OKX no tiene ningun fill")


def test_una_salida_de_la_ultima_pasada_aun_no_tiene_que_estar_apuntada():
    fin = T0 + SEMANA
    fills = (j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),
             j.Fill(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", QTY, SALIDA, COM, fin - 2 * MIN))
    v = semana(fills=fills, ocos=(replace(semana_ocos()[0], fin_ms=fin - 2 * MIN),),
               operaciones=(j.Operacion(DID, "BTC/USDC", QTY, ENTRADA),))
    assert v.fallas == []


def test_los_saldos_solo_se_mueven_por_nuestros_fills():
    buenos = semana().fallas == []
    manual = semana(saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA + QTY * SALIDA - COM, "BTC": 1.001, "USDT": 5_000.0})
    usdc = semana(saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA + QTY * SALIDA - COM - 0.05, "BTC": 1.0, "USDT": 5_000.0})
    otra = semana(saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA + QTY * SALIDA - COM, "BTC": 1.0, "USDT": 4_000.0})
    assert buenos and falla(manual, "saldo de BTC") and falla(usdc, "saldo de USDC") and falla(otra, "saldo de USDT")


def test_fills_ajenos_o_del_lado_equivocado():
    raro = j.Fill("manual123", "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0)
    assert falla(semana(fills=semana_fills() + (raro,)), "fill ajeno en OKX: manual123")
    compra_de_oco = replace(semana_fills()[0], id_propio=ids.algo_cl_ord_id(DID))
    assert falla(semana(fills=(compra_de_oco, semana_fills()[1])), "no sale de donde deberia")


def semana_fills():
    return (j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),
            j.Fill(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", QTY, SALIDA, COM, T0 + 600 * MIN))


def test_la_conciliacion_tiene_que_correr_y_no_apuntar_descuadres():
    todas = [j.Pasada(T0 + i * 5 * MIN) for i in range(SEMANA // (5 * MIN) + 1)]
    con_hueco = tuple(p for p in todas if not T0 + 100 * MIN < p.ts_ms < T0 + 120 * MIN)
    assert falla(semana(pasadas=con_hueco), "sin conciliar 20 min")
    assert semana(pasadas=tuple(p for p in todas if p.ts_ms != T0 + 100 * MIN)).fallas == []   # 10 min: vale
    assert falla(semana(pasadas=tuple(todas[:-10])), "sin conciliar desde")
    con_descuadre = tuple(todas[:50]) + (j.Pasada(todas[50].ts_ms, ("orden_ajena: x",)),) + tuple(todas[51:])
    assert falla(semana(pasadas=con_descuadre), "descuadre de la conciliacion")
    assert falla(semana(pasadas=()), "no ha corrido nunca")


def test_una_salida_con_el_precio_ya_pasado_el_objetivo_vale_sin_hacerla_en_papel():
    """Decision del propietario del 03/10: OKX rechaza crear la OCO y el ejecutor vende a mercado. El juez lo mira con el precio
    del llenado (SALIDA = 84.000) y los niveles de papel, no con lo que apunto el bot."""
    v = semana_con_salida(salidas_espejo=set(), niveles={DID: (76_000.0, 83_900.0)})
    assert v.fallas == [] and v.medidas["salidas por precio pasado"] == 1
    v = semana_con_salida(salidas_espejo=set(), niveles={DID: (76_000.0, 88_000.0)})
    assert falla(v, "que la cartera de la IA no hizo en papel") and falla(v, "entre stop")
    assert falla(semana_con_salida(salidas_espejo=set()), "que la cartera de la IA no hizo en papel"), "sin niveles"


def test_una_semana_sin_ninguna_operacion_completa_no_vale():
    """Decision del propietario del 03/10: siete dias sin descuadres y sin actividad no prueban nada de las ordenes."""
    vacia = semana(ordenes=(), ocos=(), fills=(), operaciones=(), espejo=set(),
                   saldos_fin={"USDC": 5_000.0, "BTC": 1.0, "USDT": 5_000.0})
    assert vacia.fallas == [] and vacia.cubierto_ms >= j.SEMANA_MS and vacia.completas == 0
    assert vacia.codigo == 2, "aun no: sin una operacion completa"


def test_una_compra_aun_abierta_no_es_una_operacion_completa():
    abierta = semana(ocos=(j.Oco(ids.algo_cl_ord_id(DID), "BTC/USDC", "sell", "cash", QTY, "live", T0 + 31 * MIN,
                                 None),),
                     fills=(j.Fill(ids.cl_ord_id(DID), "BTC/USDC", "buy", QTY, ENTRADA, 0.0, T0 + 30 * MIN),),
                     operaciones=(j.Operacion(DID, "BTC/USDC", QTY, ENTRADA),),
                     saldos_fin={"USDC": 5_000.0 - QTY * ENTRADA, "BTC": 1.0 + QTY, "USDT": 5_000.0})
    assert abierta.fallas == [] and abierta.completas == 0 and abierta.codigo == 2


def test_una_posicion_adoptada_entra_con_limit_y_se_cuenta_aparte():
    """Decision del propietario del 03/10: las posiciones de papel abiertas en la foto se adoptan una vez (compra limit que
    cruza). No son una orden que la IA 'no envio' ni una entrada que no sea post-only, y se cuentan aparte."""
    limit = (j.Orden(ids.cl_ord_id(DID), "BTC/USDC", "buy", "limit", "cash", QTY, QTY, "filled", T0 + MIN),)
    v = semana(ordenes=limit, espejo=set(), adoptadas={DID})
    assert v.fallas == [] and v.medidas["adoptadas"] == 1 and v.medidas["mandadas al demo"] == 0
    assert v.completas == 1, "su OCO y su cierre cuentan como operacion completa (condicion 3 del 03/10)"
    v = semana(ordenes=limit, espejo=set())
    assert falla(v, "que la cartera de la IA no envio") and falla(v, "post-only")
    v = semana(ordenes=limit)
    assert falla(v, "post-only"), "una copia normal sigue siendo post-only"
