"""Los candidatos en sombra (decision 5 del protocolo de la fase 6, opcion B del propietario del 02/10/2026).

Con la cartera llena, "si hubiera hueco, que abririas?": la IA decide sobre lo que saldria con hueco y NO se abre
nada. Lo que se protege (`docs/archivo/propuesta-candidatos-sombra.md`, los cuatro detalles):
1. la IA ve `slots_free: 1` y las posiciones de verdad, sin saber que es sombra;
2. una sombra nunca deja sin llamada a una vela de verdad (margen de 4 en 5 h y 20 al dia);
3. no cambia nada de la decision de verdad (va despues; el baseline no la tiene);
4. nunca abre nada (el bucle no le hace caso y el juez de papel lo comprueba);
y que se juzga APARTE (`check_fase6.py --sombra`), sin mezclarse con la M1 de verdad.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from ai.budget import CallBudget
from ai.decider import MARGEN_SOMBRA_DIA, MARGEN_SOMBRA_VENTANA, AnalystDecider
from ai.invoke import AnalystCall
from ai.journal import SOMBRA, call_row, decision_rows
from ai.parser import parse
from ai.prompt import LimitsView, build_input, candidate_ids, position_ids, render
from ai.quota import CallOutcome, Classification, QuotaTracker
from core.config import load_settings
from core.modes import Mode
from features.regime import Regime
from portfolio import loop as loop_mod
from portfolio import store
from portfolio.loop import DecisionContext, TradingLoop, solo_por_llena
from portfolio.paper import Bar, PaperBroker, PaperLedger
from risk.limits import Limits
from risk.state import RiskState
from strategy.candidates import Candidate, make_decision_id
from strategy.filters import FilterResult, Screening
from strategy.pipeline import PipelineResult
from tests.risk_fixtures import INSTRUMENTS

TF = 4 * 3600 * 1000
VELA = datetime(2026, 9, 22, 16, tzinfo=UTC)
TS = int(VELA.timestamp() * 1000)
AHORA = (TS + TF + 60_000) / 1000
LLENA = "3/3 huecos ocupados (pendientes incluidas)"


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


def criba(symbol, *rechazos):
    return Screening(symbol, tuple(FilterResult(n, False, d) for n, d in rechazos))


# --------------------------------------------------------------------------
# Que moneda cuenta como "solo por la cartera llena"
# --------------------------------------------------------------------------


def test_solo_por_llena():
    assert solo_por_llena(criba("ETH/USDC", ("hueco libre", LLENA)))
    assert not solo_por_llena(criba("ETH/USDC", ("hueco libre", "ya hay posicion o entrada pendiente en el simbolo")))
    assert not solo_por_llena(criba("ETH/USDC", ("hueco libre", LLENA), ("atr", "ATR 6 % demasiado alto")))
    assert not solo_por_llena(Screening("ETH/USDC", (FilterResult("hueco libre", True, "1/3 ocupados"),)))


# --------------------------------------------------------------------------
# El bucle: la sombra va despues, no abre nada y el baseline no la tiene
# --------------------------------------------------------------------------


class Pipeline:
    """Con el tope de siempre, la cartera llena: ETH cae solo por eso y TRX porque ya tiene posicion.
    Con el tope abierto (la segunda criba de la sombra), salen los dos como candidatos."""

    def __init__(self):
        self.topes = []

    def __call__(self, market, state, limits, *a, **kw):
        self.topes.append(limits.max_positions)
        if limits.max_positions == loop_mod.TOPE_SOMBRA:
            return PipelineResult(candidates=(ETH, TRX))
        return PipelineResult(screenings=(
            criba("ETH/USDC", ("hueco libre", LLENA)),
            criba("TRX/USDC", ("hueco libre", "ya hay posicion o entrada pendiente en el simbolo")),
        ))


@pytest.fixture
def pipeline(monkeypatch):
    p = Pipeline()
    monkeypatch.setattr(loop_mod, "run_pipeline", p)
    return p


def bucle(sombra=None, decide=None):
    broker = PaperBroker(INSTRUMENTS)
    return TradingLoop(instruments=INSTRUMENTS, cost=None, settings=load_settings(), broker=broker,
                       ledger=PaperLedger(starting_usd=50.0, broker=broker), decide=decide, sombra=sombra)


def paso(b: TradingLoop):
    velas = {s: Bar(ts_open_ms=TS, open=c.entry, high=c.entry, low=c.entry, close=c.entry)
             for s, c in (("ETH/USDC", ETH), ("TRX/USDC", TRX))}
    return b.step(TS, {}, velas, {s: pd.Series(dtype=float) for s in velas}, usdc_deviation_pct=0.0)


def test_la_sombra_recibe_solo_las_que_caen_por_la_cartera_llena_y_no_abre_nada(pipeline):
    vistos = []
    b = bucle(sombra=vistos.append, decide=lambda ctx: [])
    r = paso(b)
    assert pipeline.topes == [3, loop_mod.TOPE_SOMBRA]
    [ctx] = vistos
    assert [c.symbol for c in ctx.candidates] == ["ETH/USDC"], "TRX ya tiene posicion: otra pregunta"
    assert r.sombra == (ETH,)
    assert b.broker.pending == [] and r.submitted == ()


def test_el_baseline_no_tiene_sombra_ni_segunda_criba(pipeline):
    r = paso(bucle())
    assert pipeline.topes == [3] and r.sombra == ()


def test_fuera_de_normal_no_hay_sombra(pipeline):
    vistos = []
    b = bucle(sombra=vistos.append, decide=lambda ctx: [])
    b.modes.activate(Mode.CLOSE_ONLY_MANUAL, "pausa")
    paso(b)
    assert vistos == [] and pipeline.topes == [3]


def test_una_sombra_que_falla_no_tumba_la_vela(pipeline):
    def revienta(ctx):
        raise RuntimeError("sombra rota")
    r = paso(bucle(sombra=revienta, decide=lambda ctx: []))
    assert r.equity_usd > 0 and r.sombra == ()


def test_lo_que_devuelva_la_sombra_se_ignora(pipeline):
    """Aunque una sombra mal hecha devolviera elecciones, el bucle no las mira."""
    from strategy.baseline import Choice
    b = bucle(sombra=lambda ctx: [Choice(candidate=ETH, size_multiplier=1.0, confidence=1, reason="x",
                                         decider="ai")], decide=lambda ctx: [])
    paso(b)
    assert b.broker.pending == []


# --------------------------------------------------------------------------
# La IA en sombra (`AnalystDecider.sombra`)
# --------------------------------------------------------------------------


class Claude:
    def __init__(self, outcome=CallOutcome.OK, abre=True):
        self.outcome, self.abre, self.entradas = outcome, abre, []

    def __call__(self, entrada, **kw):
        self.entradas.append(entrada)
        cids, pids = candidate_ids(entrada), position_ids(entrada)
        salida = {"decisions": [{"type": "open" if self.abre else "skip", "ref": c, "confidence": 0.6,
                                 "reasons": ["r"], "risks": [], **({"size_multiplier": 1.0} if self.abre else {})}
                                for c in sorted(cids)], "market_read": "."}
        if self.outcome is CallOutcome.OK:
            parsed = parse(salida, cids, pids)
        else:
            from ai.parser import ParseResult
            parsed = ParseResult.invalid("fallo", cids)
        return AnalystCall(self.outcome, parsed, 10.0, "ok", structured=salida)


@pytest.fixture
def budget():
    conn = sqlite3.connect(":memory:")
    yield CallBudget.from_settings(conn, load_settings())
    conn.close()


def analista(budget, claude, ahora=AHORA):
    return AnalystDecider(
        settings=load_settings(), budget=budget, tracker=QuotaTracker.from_active(False, int(ahora * 1000)),
        token="t", config_dir=None, timeframe_ms=TF, clock=lambda: ahora, _call=claude,
        _probe=lambda **kw: Classification(CallOutcome.OK, "ok"),
    )


def contexto(*candidatos, modo=Mode.NORMAL):
    settings = load_settings()
    estado = RiskState(now=VELA, equity_usd=50.0, free_quote_usd=5.0, mode=modo, usdc_deviation_pct=0.0)
    return DecisionContext(ts_ms=TS, now=VELA, candidates=tuple(candidatos), state=estado,
                           limits=Limits.for_state(settings, 50.0, 3), mode=modo, marks={})


def test_la_ia_ve_un_hueco_y_queda_en_el_journal_como_sombra(budget):
    claude = Claude()
    a = analista(budget, claude)
    assert a.sombra(contexto(ETH)) is None, "no devuelve nada: no se abre nada"
    [entrada] = claude.entradas
    assert entrada["limits"]["slots_free"] == 1
    assert "sombra" not in json.dumps(entrada).lower(), "la IA no sabe que es sombra"
    [(fila, decisiones)] = a.journal
    assert fila["kind"] == SOMBRA and fila["valid"] == 1 and fila["n_candidates"] == 1
    assert [d["ref"] for d in decisiones] == [ETH.cid]
    assert budget.conn.execute("SELECT kind FROM ai_budget_calls").fetchall() == [(SOMBRA,)]


def test_la_sombra_deja_margen_a_las_de_verdad(budget):
    """Con 4 usadas en la ventana de 5 h (de 8), despues quedarian 3: no llama y no cambia de modo."""
    for k in range(load_settings().claude.max_calls_per_5h_window - MARGEN_SOMBRA_VENTANA):
        budget.try_acquire(int(AHORA * 1000) - 1000 * (k + 1))
    claude = Claude()
    a = analista(budget, claude)
    a.sombra(contexto(ETH))
    assert claude.entradas == []
    [(fila, decisiones)] = a.journal
    assert (fila["kind"], fila["outcome"], decisiones) == (SOMBRA, "skipped_budget", [])
    assert "sombra sin presupuesto" in fila["reason"]
    assert a.quota_change is None, "sin margen para la sombra no es sin cuota"
    assert MARGEN_SOMBRA_DIA == 20


def test_reintentar_la_misma_vela_no_vuelve_a_llamar(budget):
    claude = Claude()
    a = analista(budget, claude)
    a.sombra(contexto(ETH))
    primera = list(a.journal)
    a.journal = []
    a.sombra(contexto(ETH))
    assert len(claude.entradas) == 1 and a.journal == primera


def test_vela_atrasada_o_fuera_de_normal_no_llama(budget):
    claude = Claude()
    analista(budget, claude, ahora=AHORA + 2 * TF / 1000).sombra(contexto(ETH))
    analista(budget, claude).sombra(contexto(ETH, modo=Mode.CLOSE_ONLY_DAILY))
    assert claude.entradas == []


def test_la_cuota_agotada_vista_en_sombra_cuenta(budget):
    a = analista(budget, Claude(outcome=CallOutcome.QUOTA))
    a.sombra(contexto(ETH))
    assert a.quota_change is not None and a.quota_change.active


# --------------------------------------------------------------------------
# Los jueces
# --------------------------------------------------------------------------


def _fila_sombra(ts, cids):
    entrada = {"ts": ts, "mode": "NORMAL", "limits": {"slots_free": 1, "trades_left_today": 6}, "memory": [],
               "portfolio": {"open_positions": []}, "candidates": [{"cid": c} for c in cids]}
    fila = {"ts_ms": ts, "called_ms": ts + TF, "kind": SOMBRA, "outcome": "ok", "valid": 1, "reason": "ok",
            "n_candidates": len(cids), "prompt": json.dumps(entrada) + "\nDecide."}
    decisiones = [{"ref": c, "type": "skip", "size_multiplier": None, "confidence": 0.5, "reasons": "[]",
                   "risks": "[]", "executed": 0} for c in cids]
    return fila, decisiones


def _audit(tmp_path, *, orden_de_sombra: bool):
    from portfolio.audit import Audit, PaperRecord
    c = store.connect(tmp_path / "ia.db")
    store.migrate(c)
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    ledger.record(TS, {"ETH/USDC": ETH.entry})
    filas = []
    if orden_de_sombra:
        assert broker.submit(ETH.decision_id, "ETH/USDC", 0.005, ETH.entry, ETH.stop, ETH.target, ETH.setup, TS)
        filas = [(ETH.decision_id, "ETH/USDC", ETH.setup, "submitted", "...")]
    store.save_step(c, broker, ledger, "4h", TS, filas, decider="ai", market=[], correlations=[],
                    usdc=(1.0, None, 0.0, "x"), ai_calls=[_fila_sombra(TS, [ETH.cid, TRX.cid])])
    return Audit(record=PaperRecord.from_db(c, "4h"), bars={}, instruments=INSTRUMENTS,
                 settings=load_settings(), timeframe_ms=TF, decider="ai")


def test_el_juez_de_papel_acepta_las_decisiones_en_sombra(tmp_path):
    a = _audit(tmp_path, orden_de_sombra=False)
    assert a.analista_referencias().ok
    assert a.propone_y_dispone().ok


def test_el_juez_de_papel_ve_una_orden_de_un_candidato_en_sombra(tmp_path):
    check = _audit(tmp_path, orden_de_sombra=True).propone_y_dispone()
    assert any("EN SOMBRA" in f for f in check.fallos)


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_fase6.py"


def _check_fase6():
    spec = importlib.util.spec_from_file_location("check_fase6_sombra", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["check_fase6_sombra"] = m
    spec.loader.exec_module(m)
    return m


def test_la_m1_en_sombra_se_juzga_aparte(tmp_path, monkeypatch, capsys):
    """Una llamada en sombra (y ninguna de verdad): la M1 de verdad no la ve; la de sombra si."""
    from data.store.db import open_database
    from tests.risk_fixtures import MAKER, TAKER
    db = open_database(tmp_path / "main.db")
    db.executemany_sync(
        "INSERT INTO instruments (symbol, base, quote, active, tick_size, lot_size, min_amount, min_cost,"
        " maker_fee, taker_fee, raw, fetched_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(s, s.split("/")[0], "USDC", 1, i.tick_size, i.lot_size, i.min_amount, None, MAKER, TAKER, "{}", TS)
         for s, i in INSTRUMENTS.items()])
    db.close()
    ai = store.connect(tmp_path / "ai.db")
    store.migrate(ai)
    entrada = build_input(now=VELA, mode="NORMAL", equity_usd=50, free_quote_usd=5, positions=[],
                          limits=LimitsView(3, 1, 0.5, 3.0, 6), candidates=[ETH, TRX])
    salida = {"decisions": [
        {"type": "open", "ref": ETH.cid, "confidence": 0.7, "reasons": ["a"], "risks": [], "size_multiplier": 1.0},
        {"type": "skip", "ref": TRX.cid, "confidence": 0.6, "reasons": ["b"], "risks": []}], "market_read": "."}
    llamada = AnalystCall(CallOutcome.OK, parse(salida, candidate_ids(entrada), position_ids(entrada)), 9.0, "ok",
                          structured=salida)
    store.record_ai_call(ai, call_row(llamada, ts_ms=TS, called_ms=TS + TF, kind=SOMBRA, prompt=render(entrada),
                                      n_candidates=2, camino="huella000001"), decision_rows(llamada))
    ai.close()
    m = _check_fase6()
    base = ["check_fase6.py", "--main-db", str(tmp_path / "main.db"), "--paper-db", str(tmp_path / "no.db"),
            "--ai-db", str(tmp_path / "ai.db"), "--ahora-ms", str(TS + 2 * TF)]
    monkeypatch.setattr(sys, "argv", base)
    assert m.main() == 2
    assert "no ha decidido ninguna vela todavia" in capsys.readouterr().out, "la de verdad no ve la sombra"
    monkeypatch.setattr(sys, "argv", [*base, "--sombra"])
    assert m.main() == 2
    out = capsys.readouterr().out
    assert "M1 EN SOMBRA" in out and "decididas: 1" in out and "no aplica" in out


def test_la_sombra_deja_margen_en_el_dia(budget):
    """21 llamadas hoy (repartidas, sin llenar ninguna ventana de 5 h): despues quedarian 18 de 40, menos de
    20. La ventana si tendria sitio: lo que para es el margen del dia."""
    inicio = int(datetime(2026, 9, 22, 0, 30, tzinfo=UTC).timestamp() * 1000)
    for k in range(21):
        assert budget.try_acquire(inicio + k * 45 * 60_000).allowed
    claude = Claude()
    a = analista(budget, claude)
    a.sombra(contexto(ETH))
    assert claude.entradas == [] and a.journal[0][0]["outcome"] == "skipped_budget"
    assert "18 hoy" in a.journal[0][0]["reason"]
