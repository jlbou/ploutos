"""El espejo de la cartera de la IA en el demo (`execution/espejo.py`; decisiones del propietario del 02/10), sin red."""

from __future__ import annotations

from execution.espejo import VELAS_DE_VIDA, CierrePapel, Demo, OrdenPapel, Que, decidir, vence_ms
from portfolio.paper import Bar, OrderState, PaperBroker
from tests.risk_fixtures import INSTRUMENTS

TF = 4 * 3600_000
T0 = 1_790_352_000_000                      # 25/09/2026 16:00 UTC, apertura de una vela de 4 h
OPERABLES = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC")
BTC, ETH, NEAR = "d-20260925T1600-btc-pb", "d-20260925T1600-eth-pb", "d-20260925T1600-near-pb"


def orden(did=BTC, simbolo="BTC/USDC", creada=T0, estado="pending"):
    return OrdenPapel(did, simbolo, 0.0002, 80_000.0, 77_000.0, 86_000.0, creada, estado)


def que(acciones):
    return [(a.que, a.decision_id) for a in acciones]


VACIO = Demo()


def una_vuelta(ordenes=(), cierres=(), demo=VACIO, ahora=T0 + TF + 5_000, arranque=T0):
    return decidir(ordenes, cierres, demo, operables=OPERABLES, arranque_ms=arranque, ahora_ms=ahora, tf_ms=TF)


def test_una_orden_nueva_se_copia_tal_cual():
    [a] = una_vuelta([orden()])
    assert a.que is Que.COPIAR and a.orden == orden(), "la MISMA orden (decision 1 del 02/10)"


def test_cada_decision_se_trata_una_sola_vez():
    assert una_vuelta([orden()], demo=Demo(tratadas=frozenset({BTC}))) == []


def test_lo_que_no_se_copia_se_omite_con_su_motivo():
    acciones = una_vuelta([orden(NEAR, "NEAR/USDC")])
    assert que(acciones) == [(Que.OMITIR, NEAR)] and "no se opera en el demo" in acciones[0].motivo
    antigua = orden(creada=T0 - 3 * TF)
    assert "antes del arranque" in una_vuelta([antigua], arranque=T0)[0].motivo
    assert "cancelada en papel" in una_vuelta([orden(estado="cancelled")])[0].motivo
    assert "caducada antes" in una_vuelta([orden()], ahora=vence_ms(T0, TF))[0].motivo


def test_la_decision_justo_en_el_arranque_se_copia():
    """El ejecutor arranca entre el cierre de la vela y el envio: esa decision ya es suya."""
    assert una_vuelta([orden()], arranque=T0 + TF)[0].que is Que.COPIAR


def test_la_caducidad_es_la_del_simulador_de_papel():
    """El reloj propio (decision 3 del 02/10) tiene que coincidir con el papel: misma orden, misma vida.
    Se mide con el simulador DE VERDAD: la orden aun se llena en la ultima vela y caduca al cerrarla."""
    def broker_con_orden():
        b = PaperBroker(INSTRUMENTS)
        b.submit("d-test", "ETH/USDC", 0.15, 100.0, 97.0, 106.0, "pullback_trend", T0)
        return b
    def sin_llenar(i):
        return Bar(T0 + i * TF, 105.0, 106.0, 104.0, 105.0)
    b = broker_con_orden()
    for i in range(1, VELAS_DE_VIDA - 1):
        b.on_bar("ETH/USDC", sin_llenar(i))
    ultima = T0 + (VELAS_DE_VIDA - 1) * TF
    b.on_bar("ETH/USDC", Bar(ultima, 101.0, 102.0, 99.5, 101.0))
    assert "ETH/USDC" in b.positions, "en la ultima vela aun se llena"
    b = broker_con_orden()
    for i in range(1, VELAS_DE_VIDA):
        b.on_bar("ETH/USDC", sin_llenar(i))
    assert b.orders[0].state is OrderState.EXPIRED, "y al cerrarla caduca"
    assert vence_ms(T0, TF) == ultima + TF, "el demo la cancela justo al cierre de esa vela"


def test_una_entrada_del_demo_caduca_con_su_reloj_aunque_el_papel_la_llenara():
    demo = Demo(entradas_vivas=frozenset({BTC}), tratadas=frozenset({BTC}))
    llena = orden(estado="filled")
    assert una_vuelta([llena], demo=demo, ahora=vence_ms(T0, TF) - 1) == []
    acciones = una_vuelta([llena], demo=demo, ahora=vence_ms(T0, TF))
    assert que(acciones) == [(Que.CANCELAR, BTC)] and "caducada" in acciones[0].motivo


def test_lo_que_el_papel_cancela_el_demo_tambien():
    demo = Demo(entradas_vivas=frozenset({BTC}), tratadas=frozenset({BTC}))
    acciones = una_vuelta([orden(estado="cancelled")], demo=demo)
    assert que(acciones) == [(Que.CANCELAR, BTC)] and "cancelada en papel" in acciones[0].motivo


def test_una_salida_por_noticias_o_a_mano_se_vende_y_una_por_la_oco_no():
    demo = Demo(posiciones=frozenset({BTC, ETH}), tratadas=frozenset({BTC, ETH}))
    for motivo in ("news", "manual"):
        acciones = una_vuelta(cierres=[CierrePapel(BTC, motivo)], demo=demo)
        assert que(acciones) == [(Que.VENDER, BTC)] and motivo in acciones[0].motivo
    for motivo in ("stop", "target"):
        assert una_vuelta(cierres=[CierrePapel(BTC, motivo)], demo=demo) == [], "la OCO del demo hace lo suyo"
    assert una_vuelta(cierres=[CierrePapel(NEAR, "news")], demo=demo) == [], "sin posicion en el demo, nada"
    vendiendo = Demo(posiciones=frozenset({BTC}), vendiendo=frozenset({BTC}))
    assert una_vuelta(cierres=[CierrePapel(BTC, "news")], demo=vendiendo) == [], "una sola vez"


def test_el_orden_vender_cancelar_copiar():
    demo = Demo(posiciones=frozenset({ETH}), entradas_vivas=frozenset({BTC}), tratadas=frozenset({BTC, ETH}))
    sol = "d-20260925T2000-sol-pb"
    acciones = una_vuelta([orden(estado="cancelled"), orden(sol, "SOL/USDC", T0 + TF)], [CierrePapel(ETH, "news")],
                          demo, ahora=T0 + 2 * TF + 5_000)
    assert [a.que for a in acciones] == [Que.VENDER, Que.CANCELAR, Que.COPIAR]
