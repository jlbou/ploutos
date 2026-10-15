"""El juez de la fase 6 (`portfolio/comparacion.py`) con datos inventados de resultado conocido.

Lo que dice el protocolo (seccion 9): antes de fiarse del juez, probarlo con "IAs" de
mentira. Una que elige al azar tiene que salir NO CONCLUYENTE; una que conoce el
futuro, APORTA; una que elige siempre lo peor, PERJUDICA.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from features.regime import Regime
from portfolio.comparacion import (
    APORTA, DIA_MS, MAX_DIAS, MIN_DIAS, NO_CONCLUYENTE, PERJUDICA, Calendario, Cand,
    Decision, Resultado, bootstrap_por_dias, evaluar, m2, m3, resolver, seleccion_baseline,
    seleccion_ia, veredicto,
)
from portfolio.paper import Bar
from strategy.baseline import rank
from strategy.candidates import Candidate, Generation

TF = 4 * 3600 * 1000
T0 = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp() * 1000)
MAKER, TAKER = 0.001, 0.002


def barra(i, o, h, l, c):
    return Bar(T0 + i * TF, o, h, l, c)


C = Cand("d-x", "X/USDC", entry=100.0, stop=95.0, target=110.0, regime="trend_up")


def res(bars, horizonte=42):
    return resolver(C, T0, bars, tf_ms=TF, maker=MAKER, taker=TAKER, horizonte=horizonte)


# --------------------------------------------------------------------------
# Resolucion: las mismas suposiciones que el simulador
# --------------------------------------------------------------------------


def test_objetivo_da_la_r_neta_con_salida_maker():
    r = res([barra(1, 101, 101, 99.5, 100), barra(2, 100, 111, 100, 110)])
    assert r.estado == "target"
    esperado = ((110 - 100) - 100 * MAKER - 110 * MAKER) / 5
    assert r.r == pytest.approx(esperado)


def test_stop_sufre_el_hueco_y_sale_taker():
    r = res([barra(1, 101, 101, 99.5, 100), barra(2, 93, 94, 90, 91)])
    assert r.estado == "stop"
    assert r.r == pytest.approx(((93 - 100) - 100 * MAKER - 93 * TAKER) / 5), "sale a la apertura, 93"


def test_el_stop_gana_los_empates():
    r = res([barra(1, 101, 101, 99.5, 100), barra(2, 100, 111, 94, 100)])
    assert r.estado == "stop"


def test_nunca_se_llena_en_la_vela_que_lo_crea():
    # La vela 0 (la de la decision) toca la entrada y el objetivo: no cuenta.
    r = res([barra(0, 100, 111, 99, 110), barra(1, 105, 106, 104, 105),
             barra(2, 105, 106, 104, 105), barra(3, 105, 106, 104, 105)])
    assert (r.estado, r.r) == ("caducada", 0.0)


def test_caducada_vale_cero():
    r = res([barra(i, 105, 106, 104, 105) for i in range(1, 5)])
    assert (r.estado, r.r) == ("caducada", 0.0)


def test_abierta_en_el_horizonte_se_valora_al_cierre_saliendo_taker():
    bars = [barra(1, 101, 101, 99.5, 100)] + [barra(i, 101, 102, 99, 102) for i in range(2, 4)]
    r = res(bars, horizonte=3)
    assert r.estado == "horizonte"
    assert r.r == pytest.approx(((102 - 100) - 100 * MAKER - 102 * TAKER) / 5)


def test_sin_llegar_al_horizonte_no_se_juzga():
    bars = [barra(1, 101, 101, 99.5, 100), barra(2, 101, 102, 99, 102)]
    assert res(bars, horizonte=42).estado == "pendiente"
    assert res([barra(1, 105, 106, 104, 105)]).estado == "pendiente", "ni siquiera ha caducado"


# --------------------------------------------------------------------------
# Quien habria abierto que
# --------------------------------------------------------------------------


def cand_real(symbol, rr, i):
    ts = T0
    entry, stop = 100.0, 95.0
    did = f"d-{i}"
    return Candidate(
        cid=did, decision_id=did, symbol=symbol, setup="pullback_trend", timeframe="4h",
        entry=entry, stop=stop, target=entry + rr * 5, reward_risk=rr, cost_rt_pct=0.3,
        spread_pct=0.02, regime=Regime.TREND_UP, bar_ts_ms=ts,
        created_at=datetime.fromtimestamp(ts / 1000, tz=UTC),
    )


def test_la_seleccion_del_baseline_es_la_de_strategy_baseline():
    """Si alguien cambia el baseline, el juez tiene que cambiar con el (o fallar aqui)."""
    rng = random.Random(1)
    for _ in range(200):
        n = rng.randint(1, 6)
        # R:R repetidos a proposito: el desempate tambien tiene que coincidir.
        reales = [cand_real(f"S{i}/USDC", rng.choice([2.0, 2.5, 3.1, 3.1, 4.0]), rng.randint(0, 99))
                  for i in range(n)]
        reales = list({c.cid: c for c in reales}.values())
        gen = Generation(candidates=tuple(reales), rejections=())
        cupo = rng.randint(0, 3)
        esperado = [ch.decision_id for ch in rank(gen)][:cupo]
        mios = tuple(Cand(c.cid, c.symbol, c.entry, c.stop, c.target) for c in reales)
        assert seleccion_baseline(mios, cupo) == esperado


def test_la_ia_abre_en_su_orden_hasta_el_cupo_y_nada_inventado():
    a, b, c = (Cand(f"d-{k}", "X", 100, 95, 110) for k in "abc")
    d = Decision(T0, (a, b, c), abiertos=(("d-c", 0.5), ("d-inventado", 1.0), ("d-a", 1.0)), cupo=1)
    assert seleccion_ia(d) == [("d-c", 0.5)]


# --------------------------------------------------------------------------
# M1, M2, M3
# --------------------------------------------------------------------------


def dec(ts, rs, abiertos, cupo=1):
    """Una vela con candidatos de R conocida (R:R = indice, para fijar el baseline)."""
    cands = tuple(Cand(f"d-{i}", f"S{i}", 100, 95, 100 + 5 * (i + 2), "trend_up")
                  for i in range(len(rs)))
    resultados = {(ts, c.cid): Resultado("x", r) for c, r in zip(cands, rs)}
    return Decision(ts, cands, tuple(abiertos), cupo), resultados


def test_m1_es_lo_de_la_ia_menos_lo_del_baseline_y_saltar_todo_vale_cero():
    # Baseline: el de mayor R:R = el ultimo (d-2), que acaba en -1 R.
    d1, r1 = dec(T0, [2.0, 0.5, -1.0], [("d-0", 1.0)])
    d2, r2 = dec(T0 + TF, [2.0, 0.5, -1.0], [])
    d3, r3 = dec(T0 + 2 * TF, [2.0, 0.5, -1.0], [("d-2", 1.0)])
    velas, pend = evaluar([d1, d2, d3], {**r1, **r2, **r3})
    assert pend == 0
    assert [v.m1 for v in velas] == pytest.approx([3.0, 1.0, 0.0])
    assert [v.discrepa for v in velas] == [True, True, False]


def test_el_multiplicador_cuenta_en_m1_y_se_separa_en_m3():
    d, r = dec(T0, [2.0, -1.0], [("d-1", 0.5)])
    [v], _ = evaluar([d], r)
    assert v.m1 == pytest.approx(-0.5 - (-1.0)), "reducir un perdedor ayuda"
    assert v.discrepa, "mismo candidato que el baseline, pero con otro tamanyo"
    assert m3([v]) == pytest.approx((-0.5, -1.0))


def test_m2_separa_abiertos_y_saltados():
    d, r = dec(T0, [2.0, 0.5, -1.0], [("d-0", 1.0)], cupo=1)
    velas, _ = evaluar([d], r)
    assert m2(velas) == pytest.approx((2.0, 1, -0.25, 2))


def test_una_vela_con_un_candidato_sin_resolver_espera_entera():
    d, r = dec(T0, [2.0, 0.5], [("d-0", 1.0)])
    r[(T0, "d-1")] = Resultado("pendiente")
    velas, pend = evaluar([d], r)
    assert (velas, pend) == ([], 1)


# --------------------------------------------------------------------------
# Las IAs de mentira: el juez tiene que acertar con ellas
# --------------------------------------------------------------------------


def simular(elige, *, dias=40, velas_dia=3, semilla=11, remuestreos=2000):
    """Mercado inventado: cada vela 3 candidatos con R al azar e independiente del R:R.

    `elige(candidatos, rs)` devuelve el cid que abre la IA (o None).
    """
    rng = random.Random(semilla)
    decisiones, resultados = [], {}
    for k in range(dias * velas_dia):
        ts = T0 + k * (DIA_MS // velas_dia)
        rs = [rng.choice([-1.0, -1.0, 2.0]) for _ in range(3)]
        d, r = dec(ts, rs, [])
        cid = elige(d.candidatos, rs, rng)
        decisiones.append(Decision(ts, d.candidatos, ((cid, 1.0),) if cid else (), 1))
        resultados.update(r)
    velas, _ = evaluar(decisiones, resultados)
    intervalo = bootstrap_por_dias([(v.ts_ms, v.m1) for v in velas], remuestreos=remuestreos)
    return veredicto(intervalo, sum(v.discrepa for v in velas)), intervalo


def test_una_ia_que_elige_al_azar_casi_siempre_sale_no_concluyente():
    """Casi: con un intervalo del 90 %, una IA inutil sale APORTA ~1 de cada 20-30 veces
    por pura suerte (medido el 24/09: 6 de 200, y 7 de 200 PERJUDICA). No es un fallo del
    juez, es lo que significa el 90 %. Lo que se comprueba es que no pase MAS que eso."""
    veredictos = [simular(lambda cands, rs, rng: rng.choice(cands).cid, semilla=s,
                          remuestreos=1000)[0] for s in range(100)]
    assert veredictos.count(APORTA) <= 10
    assert veredictos.count(PERJUDICA) <= 10
    assert veredictos.count(NO_CONCLUYENTE) >= 80


@pytest.mark.parametrize("semilla", range(5))
def test_una_ia_que_conoce_el_futuro_sale_aporta(semilla):
    v, i = simular(lambda cands, rs, rng: max(zip(cands, rs), key=lambda x: x[1])[0].cid,
                   semilla=semilla)
    assert v == APORTA and i.lo > 0


@pytest.mark.parametrize("semilla", range(5))
def test_una_ia_que_elige_siempre_lo_peor_sale_perjudica(semilla):
    v, i = simular(lambda cands, rs, rng: min(zip(cands, rs), key=lambda x: x[1])[0].cid,
                   semilla=semilla)
    assert v == PERJUDICA and i.hi < 0


def test_aporta_exige_la_muestra_minima():
    from portfolio.comparacion import Intervalo

    bueno = Intervalo(0.5, 0.1, 0.9, 40, 10)
    assert veredicto(bueno, 29) == NO_CONCLUYENTE
    assert veredicto(bueno, 30) == APORTA
    assert veredicto(Intervalo(-0.5, -0.9, -0.1, 5, 2), 3) == PERJUDICA, "perjudica, con cualquier muestra"


def test_el_bootstrap_es_reproducible_y_remuestrea_dias():
    vals = [(T0 + k * TF, float(k % 5) - 2) for k in range(60)]
    assert bootstrap_por_dias(vals) == bootstrap_por_dias(vals)
    assert bootstrap_por_dias(vals).dias == 10
    assert bootstrap_por_dias([]) is None


# --------------------------------------------------------------------------
# Sin mirar a mitad de camino
# --------------------------------------------------------------------------


def test_el_veredicto_no_se_ensenya_antes_de_tiempo():
    cal = Calendario(T0)
    assert not cal.abierto(T0 + (MIN_DIAS - 1) * DIA_MS, discrepancias=500)
    assert not cal.abierto(T0 + MIN_DIAS * DIA_MS, discrepancias=29)
    assert cal.abierto(T0 + MIN_DIAS * DIA_MS, discrepancias=30)
    assert cal.abierto(T0 + MAX_DIAS * DIA_MS, discrepancias=0), "con 8 semanas, pase lo que pase"
