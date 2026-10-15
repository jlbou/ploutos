"""El motor del simulador del paso 2 (docs/estudios/paso2/sim/MOTOR.md), con casos hechos a mano. Escritos ANTES del
codigo. El primero es la condicion para medir nada: comprar y mantener tiene que dar EXACTAMENTE BTC mantenido."""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import motor as mo  # noqa: E402

DIA = 86_400
T0 = 1_609_459_200          # 01/01/2021 00:00 UTC (viernes)


def serie(cierres, abre=None, alto=None, bajo=None):
    n = len(cierres)
    abre = abre or [cierres[0]] + cierres[:-1]
    alto = alto or [max(a, c) * 1.001 for a, c in zip(abre, cierres, strict=True)]
    bajo = bajo or [min(a, c) * 0.999 for a, c in zip(abre, cierres, strict=True)]
    return {"t": [T0 + i * DIA for i in range(n)], "o": abre, "h": alto, "l": bajo, "c": cierres}


def paseo(n, semilla=7, p0=30_000.0):
    r = random.Random(semilla)
    x, out = p0, []
    for _ in range(n):
        x *= math.exp(r.gauss(0.0005, 0.03))
        out.append(x)
    return out


def test_validacion_comprar_y_mantener_es_exactamente_btc():
    btc, eth = serie(paseo(400)), serie(paseo(400, 9, 2_000.0))
    p = mo.Parametros.validacion()
    unos = {"BTC": [1.0] * 400, "ETH": [0.0] * 400}
    r = mo.simular({"BTC": btc, "ETH": eth}, unos, {"BTC": [None] * 400, "ETH": [None] * 400}, 1, 399, p)
    ref = mo.mantener(btc, 1, 399, p)
    assert len(r.equity) == len(ref) == 399
    assert max(abs(a - b) for a, b in zip(r.equity, ref, strict=True)) < 1e-9


def test_solo_da_resultados_dentro_de_la_ventana():
    """La guardia de la prueba limpia: con una ventana, ninguna fecha de fuera sale en el resultado."""
    btc = serie(paseo(100))
    p = mo.Parametros.validacion()
    r = mo.simular({"BTC": btc}, {"BTC": [1.0] * 100}, {"BTC": [None] * 100}, 40, 59, p)
    assert r.dias[0] == btc["t"][40] and r.dias[-1] == btc["t"][59] and len(r.dias) == 20


def _uno(cierres, fr, atr, p=None, **kw):
    s = serie(cierres, **kw)
    p = p or mo.Parametros()
    return mo.simular({"BTC": s}, {"BTC": fr}, {"BTC": atr}, 1, len(cierres) - 1, p), s


def test_el_riesgo_hasta_el_stop_recorta_el_tamanyo():
    # ATR = 20 sobre 100: stop a 3 ATR = 60 % por debajo -> 5 % / 60 % = 8,3 % del equity (menos que el 45 %).
    r, _ = _uno([100.0] * 10, [1.0] * 10, [20.0] * 10)
    op = r.operaciones[0]
    assert op["tipo"] == "compra" and math.isclose(op["nocional"] / 10_000, 0.05 / 0.60, rel_tol=1e-3)


def test_el_tope_por_moneda_es_45():
    r, _ = _uno([100.0] * 10, [1.0] * 10, [0.5] * 10)          # stop al 1,5 %: el riesgo no ata
    assert math.isclose(r.operaciones[0]["nocional"] / 10_000, 0.45, rel_tol=1e-3)


def test_el_stop_sale_a_la_apertura_si_abre_por_debajo():
    cierres = [100.0] * 5 + [80.0] * 5
    abre = [100.0] * 5 + [80.0] * 5                               # el dia 5 abre en 80, bajo el stop (97)
    r, _ = _uno(cierres, [1.0] * 10, [1.0] * 10, abre=abre)
    venta = [o for o in r.operaciones if o["tipo"] == "stop"][0]
    assert venta["dia"] == 5 and math.isclose(venta["precio"], 80.0 * (1 - mo.Parametros().deslizamiento))


def test_tras_un_stop_no_vuelve_hasta_una_senyal_nueva():
    cierres = [100.0] * 4 + [90.0] * 8
    abre = [100.0] * 4 + [90.0] * 8
    fr = [1.0] * 7 + [0.0] + [1.0] * 4                           # la senyal se apaga el dia 7 y vuelve el 8
    r, _ = _uno(cierres, fr, [1.0] * 12, abre=abre)
    tipos = [(o["dia"], o["tipo"]) for o in r.operaciones]
    assert (4, "stop") in tipos
    compras = [d for d, t in tipos if t == "compra"]
    assert compras == [1, 9]                                      # ni el 5, 6, 7 ni el 8: solo tras apagarse (orden el 9)


def test_escalon_menos_10_tope_a_la_mitad():
    p = mo.Parametros(capital=10_000.0)
    # El equity de referencia ya es 8.800 (-12 %): el tope pasa de 45 % a 22,5 %.
    s = serie([100.0] * 6)
    r = mo.simular({"BTC": s}, {"BTC": [1.0] * 6}, {"BTC": [0.5] * 6}, 1, 5, p, efectivo_inicial=8_800.0)
    assert math.isclose(r.operaciones[0]["nocional"] / 8_800.0, 0.225, rel_tol=1e-3)


def test_suelo_dos_cierres_seguidos_enclava_y_no_compra_mas():
    p = mo.Parametros(capital=10_000.0)
    s = serie([100.0] * 8)
    r = mo.simular({"BTC": s}, {"BTC": [0.0] * 3 + [1.0] * 5}, {"BTC": [0.5] * 8}, 1, 7, p, efectivo_inicial=4_900.0)
    assert r.enclavado and not [o for o in r.operaciones if o["tipo"] == "compra"]


def test_la_regla_8_no_deja_abrir_si_los_stops_bajan_del_suelo_mas_colchon():
    p = mo.Parametros(capital=10_000.0)
    s = serie([100.0] * 6)
    # Equity 5.300: un 45 % (con escalones, 22,5 %) con stop al 30 % perderia > 300 - 200 de colchon -> no abre.
    r = mo.simular({"BTC": s}, {"BTC": [1.0] * 6}, {"BTC": [10.0] * 6}, 1, 5, p, efectivo_inicial=5_300.0)
    assert not [o for o in r.operaciones if o["tipo"] == "compra"]


def test_las_comisiones_y_el_deslizamiento_se_cobran():
    p = mo.Parametros.validacion()
    s = serie([100.0] * 5)
    r = mo.simular({"BTC": s}, {"BTC": [1.0] * 5}, {"BTC": [None] * 5}, 1, 4, p)
    # compra con comision y deslizamiento, valoracion con la comision de salida: menos que el capital
    esperado = 10_000 / (1 + p.comision) / (100 * (1 + p.deslizamiento)) * 100 * (1 - p.comision)
    assert math.isclose(r.equity[-1], esperado, rel_tol=1e-12)


def test_con_impuestos_mantener_paga_igual_que_btc_mantenido():
    from dataclasses import replace
    btc = serie(paseo(800, 3))                       # cruza dos 31/12: sin ventas, ningun impuesto hasta el final
    p = replace(mo.Parametros.validacion(), impuestos=True)
    r = mo.simular({"BTC": btc}, {"BTC": [1.0] * 800}, {"BTC": [None] * 800}, 1, 799, p)
    ref = mo.mantener(btc, 1, 799, p)
    assert abs(r.equity[-1] - ref[-1]) < 1e-6
    assert all(v == 0 for a, v in r.impuestos.items() if a != max(r.impuestos))


def test_una_venta_con_ganancia_paga_el_impuesto_de_su_anyo():
    from dataclasses import replace
    from sim import impuestos as imp
    cierres = [100.0] * 3 + [200.0] * 3 + [200.0] * 400
    abre = [100.0] * 3 + [200.0] * 403
    fr = [1.0] * 4 + [0.0] * 402                      # compra el dia 1 a 100; vende el dia 5 a 200
    s = serie(cierres, abre=abre)
    p = replace(mo.Parametros.validacion(), impuestos=True)
    r = mo.simular({"BTC": s}, {"BTC": fr}, {"BTC": [None] * 406}, 1, 405, p)
    compra = [o for o in r.operaciones if o["tipo"] == "compra"][0]
    venta = [o for o in r.operaciones if o["tipo"] == "venta"][0]
    ganancia = venta["nocional"] * (1 - p.comision) - compra["nocional"] * (1 + p.comision)
    assert math.isclose(r.impuestos[2021], imp.cuota(ganancia), rel_tol=1e-9)
