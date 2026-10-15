"""El que decide, pasado desde fuera al bucle (pieza 9 de la fase 3).

El bucle es la ULTIMA puerta: lo que devuelva el que decide (la IA) lo sigue
aprobando o vetando el motor de riesgo real, y ademas el bucle no se fia de que
el parser haya hecho su trabajo: un candidato que no es de esta vela no entra,
y el multiplicador solo puede REDUCIR.

El pipeline se sustituye por uno que devuelve dos candidatos fijos: lo que se
prueba aqui es lo que pasa DESPUES de generar candidatos.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from core.config import load_settings
from features.regime import Regime
from portfolio import loop as loop_mod
from portfolio.loop import DecisionContext, TradingLoop
from portfolio.paper import Bar, PaperBroker, PaperLedger
from strategy.baseline import Choice
from strategy.candidates import Candidate, make_decision_id
from strategy.pipeline import PipelineResult
from tests.risk_fixtures import INSTRUMENTS

VELA = datetime(2026, 9, 22, 16, tzinfo=UTC)
TS = int(VELA.timestamp() * 1000)


def candidato(symbol, entry, stop, target, ts=TS):
    did = make_decision_id(symbol, "pullback_trend", ts)
    return Candidate(
        cid=did, decision_id=did, symbol=symbol, setup="pullback_trend", timeframe="4h",
        entry=entry, stop=stop, target=target, reward_risk=(target - entry) / (entry - stop),
        cost_rt_pct=0.27, spread_pct=0.02, regime=Regime.TREND_UP, bar_ts_ms=ts,
        created_at=VELA, reasons=("prueba",), features={},
    )


ETH = candidato("ETH/USDC", 2700.0, 2610.0, 2980.0)
TRX = candidato("TRX/USDC", 0.34, 0.329, 0.372)
DE_OTRA_VELA = candidato("SOL/USDC", 200.0, 193.0, 222.0, ts=TS - 4 * 3600 * 1000)


@pytest.fixture
def pipeline_fijo(monkeypatch):
    monkeypatch.setattr(loop_mod, "run_pipeline",
                        lambda *a, **kw: PipelineResult(candidates=(ETH, TRX)))


def bucle(decide=None):
    broker = PaperBroker(INSTRUMENTS)
    return TradingLoop(
        instruments=INSTRUMENTS, cost=None, settings=load_settings(), broker=broker,
        ledger=PaperLedger(starting_usd=50.0, broker=broker), decide=decide,
    )


def paso(b: TradingLoop):
    velas = {s: Bar(ts_open_ms=TS, open=c.entry * 1.01, high=c.entry * 1.02,
                    low=c.entry * 1.005, close=c.entry * 1.01)
             for s, c in (("ETH/USDC", ETH), ("TRX/USDC", TRX))}
    return b.step(TS, {}, velas, {s: pd.Series(dtype=float) for s in velas},
                  usdc_deviation_pct=0.0)


def cantidades(b: TradingLoop) -> dict[str, float]:
    return {o.symbol: o.qty for o in b.broker.pending}


def test_sin_decide_es_el_baseline(pipeline_fijo):
    """El camino de la fase 2 no cambia: `rank` por R:R."""
    r = paso(bucle())
    assert ETH.reward_risk > TRX.reward_risk
    assert [c.candidate.symbol for c in r.submitted] == ["ETH/USDC", "TRX/USDC"]


def test_el_que_decide_ve_el_momento_de_decidir_y_elige(pipeline_fijo):
    vistos: list[DecisionContext] = []

    def decide(ctx):
        vistos.append(ctx)
        return [Choice(ETH, decider="ai")]

    r = paso(bucle(decide))
    [ctx] = vistos
    assert {c.symbol for c in ctx.candidates} == {"ETH/USDC", "TRX/USDC"}
    assert ctx.ts_ms == TS and ctx.state.equity_usd == pytest.approx(50.0)
    assert [c.candidate.symbol for c in r.submitted] == ["ETH/USDC"]


def test_el_multiplicador_reduce_la_cantidad_aprobada(pipeline_fijo):
    entero_b = bucle(lambda ctx: [Choice(ETH)])
    paso(entero_b)
    entera = cantidades(entero_b)["ETH/USDC"]
    mitad_b = bucle(lambda ctx: [Choice(ETH, size_multiplier=0.5)])
    paso(mitad_b)
    mitad = cantidades(mitad_b)["ETH/USDC"]
    assert mitad <= entera * 0.5 + 1e-12
    assert mitad == pytest.approx(entera * 0.5, abs=INSTRUMENTS["ETH/USDC"].lot_size)


@pytest.mark.parametrize("m", [1.5, 0.3])
def test_un_multiplicador_fuera_de_rango_no_abre(pipeline_fijo, m):
    """Solo reducir, y no por debajo de 0,5 (PRD seccion 6). El parser ya lo
    impide; el bucle no se fia."""
    r = paso(bucle(lambda ctx: [Choice(ETH, size_multiplier=m)]))
    assert r.submitted == ()
    [(cand, _n, motivo)] = r.vetoed
    assert cand is ETH and "fuera de" in motivo


def test_un_candidato_que_no_es_de_esta_vela_no_entra(pipeline_fijo):
    r = paso(bucle(lambda ctx: [Choice(DE_OTRA_VELA), Choice(TRX)]))
    assert [c.candidate.symbol for c in r.submitted] == ["TRX/USDC"]
    assert any(c is DE_OTRA_VELA and "no es un candidato" in m for c, _n, m in r.vetoed)


def test_lo_que_elige_la_ia_lo_sigue_juzgando_el_motor(pipeline_fijo):
    """Con la paridad de USDC desconocida (regla 17) no se abre nada, lo pida quien lo pida."""
    b = bucle(lambda ctx: [Choice(ETH)])
    velas = {"ETH/USDC": Bar(ts_open_ms=TS, open=2727.0, high=2754.0, low=2713.5, close=2727.0)}
    r = b.step(TS, {}, velas, {}, usdc_deviation_pct=None)
    assert r.submitted == () and r.vetoed


def test_se_usa_el_candidato_de_la_vela_no_el_que_devuelve_el_que_decide(pipeline_fijo):
    """Revision del 24/09: un Choice con el MISMO id y otro stop no puede colarse."""
    from dataclasses import replace
    falso = replace(ETH, stop=ETH.entry * 0.999)       # stop pegado: mas tamanyo
    b = bucle(lambda ctx: [Choice(falso)])
    paso(b)
    [orden] = b.broker.pending
    assert orden.stop_price == ETH.stop


def test_si_el_que_decide_revienta_la_vela_sigue_sin_entradas(pipeline_fijo):
    """Falla = no hacer nada (PRD seccion 6). Antes la vela quedaba atascada."""
    def revienta(ctx):
        raise RuntimeError("inesperado")

    r = paso(bucle(revienta))
    assert r.submitted == ()
    assert "RuntimeError" in r.decide_error
    assert r.equity_usd == pytest.approx(50.0), "la vela se proceso entera"
