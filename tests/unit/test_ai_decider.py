"""El analista como "el que decide" del bucle (`ai/decider.py`, pieza 9).

Sin red: la llamada a Claude se sustituye por una funcion que devuelve lo que
toque, pasado por el parser DE VERDAD. Lo que se protege: cuando se llama y
cuando no (decision B, velas atrasadas, modos, regla 18), que lo que se apunta
en el journal sea lo que paso, y que la IA solo abra lo que se le ofrecio.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from ai.budget import CallBudget
from ai.decider import AnalystDecider
from ai.invoke import AnalystCall
from ai.parser import parse
from ai.prompt import candidate_ids, position_ids
from ai.quota import CallOutcome, Classification, QuotaTracker
from core.config import load_settings
from core.modes import Mode
from features.regime import Regime
from portfolio.loop import DecisionContext
from risk.limits import Limits
from risk.state import RiskState
from strategy.candidates import Candidate, make_decision_id

TF = 4 * 3600 * 1000
VELA = datetime(2026, 9, 22, 16, tzinfo=UTC)
TS = int(VELA.timestamp() * 1000)
# La vela de las 16:00 se decide al cerrar, a las 20:00 (mas un minuto).
AHORA = (TS + TF + 60_000) / 1000


def candidato(symbol, entry, stop, target):
    did = make_decision_id(symbol, "pullback_trend", TS)
    return Candidate(
        cid=did, decision_id=did, symbol=symbol, setup="pullback_trend", timeframe="4h",
        entry=entry, stop=stop, target=target, reward_risk=2.0, cost_rt_pct=0.27,
        spread_pct=0.02, regime=Regime.TREND_UP, bar_ts_ms=TS, created_at=VELA,
        reasons=("retroceso a la EMA",), features={"rsi14": 48.1},
    )


TRX = candidato("TRX/USDC", 0.3416, 0.33765, 0.36148)
ETH = candidato("ETH/USDC", 2751.0, 2670.0, 2950.0)


def contexto(*candidatos, modo=Mode.NORMAL, ts=TS):
    settings = load_settings()
    estado = RiskState(now=VELA, equity_usd=50.0, free_quote_usd=50.0, mode=modo,
                       usdc_deviation_pct=0.0)
    return DecisionContext(
        ts_ms=ts, now=VELA, candidates=tuple(candidatos), state=estado,
        limits=Limits.for_state(settings, 50.0, 3), mode=modo, marks={},
    )


class Claude:
    """Hace de `call_analyst`: pasa `structured` por el parser real y apunta la entrada."""

    def __init__(self, structured=None, outcome=CallOutcome.OK, detalle="ok"):
        self.structured, self.outcome, self.detalle = structured, outcome, detalle
        self.entradas = []

    def __call__(self, entrada, **kw):
        self.entradas.append(entrada)
        cids, pids = candidate_ids(entrada), position_ids(entrada)
        if self.outcome is CallOutcome.OK:
            parsed = parse(self.structured, cids, pids)
        else:
            from ai.parser import ParseResult
            parsed = ParseResult.invalid(f"llamada fallida: {self.outcome.value}", cids)
        return AnalystCall(self.outcome, parsed, 12.0, self.detalle, structured=self.structured)


def decision(ref, tipo="open", m=None, conf=0.7):
    d = {"type": tipo, "ref": ref, "confidence": conf, "reasons": ["porque si"], "risks": []}
    if m is not None:
        d["size_multiplier"] = m
    return d


@pytest.fixture
def budget():
    conn = sqlite3.connect(":memory:")
    yield CallBudget.from_settings(conn, load_settings())
    conn.close()


def analista(budget, claude, *, activo=False, ahora=AHORA, sonda=None):
    return AnalystDecider(
        settings=load_settings(), budget=budget,
        tracker=QuotaTracker.from_active(activo, int(ahora * 1000)),
        token="token-falso", config_dir=None, timeframe_ms=TF, clock=lambda: ahora,
        _call=claude, _probe=sonda or (lambda **kw: Classification(CallOutcome.OK, "ok")),
    )


def usadas(budget):
    return budget.conn.execute("SELECT COUNT(*) FROM ai_budget_calls").fetchone()[0]


# --------------------------------------------------------------------------
# Cuando NO se llama
# --------------------------------------------------------------------------


def test_sin_candidatos_no_se_llama_ni_se_apunta(budget):
    claude = Claude()
    a = analista(budget, claude)
    assert a(contexto()) == []
    assert claude.entradas == [] and a.journal == [] and usadas(budget) == 0


def test_una_vela_atrasada_no_gasta_presupuesto(budget):
    """Decision 3 del propietario: tras una parada, solo la ultima vela."""
    claude = Claude()
    a = analista(budget, claude, ahora=AHORA + 2 * TF / 1000)
    assert a(contexto(TRX)) == []
    assert claude.entradas == [] and usadas(budget) == 0
    [(fila, decisiones)] = a.journal
    assert fila["outcome"] == "skipped_stale" and decisiones == []


def test_en_quota_no_se_llama_y_queda_apuntado(budget):
    claude = Claude()
    a = analista(budget, claude)
    assert a(contexto(TRX, modo=Mode.CLOSE_ONLY_QUOTA)) == []
    assert claude.entradas == []
    assert a.journal[0][0]["outcome"] == "skipped_quota"


@pytest.mark.parametrize("modo", [Mode.CLOSE_ONLY_DAILY, Mode.CLOSE_ONLY_CAPITAL])
def test_en_los_otros_solo_cierre_no_se_llama(budget, modo):
    claude = Claude()
    a = analista(budget, claude)
    assert a(contexto(TRX, modo=modo)) == []
    assert claude.entradas == [] and usadas(budget) == 0


def test_sin_presupuesto_no_se_llama_y_entra_en_quota(budget):
    """Regla 18 + decision del propietario del 23/09: presupuesto agotado = CLOSE_ONLY_QUOTA."""
    for k in range(8):
        assert budget.try_acquire(int(AHORA * 1000) - 60_000 * (k + 1)).allowed
    claude = Claude()
    a = analista(budget, claude)
    assert a(contexto(TRX)) == []
    assert claude.entradas == []
    assert a.journal[0][0]["outcome"] == "skipped_budget"
    assert a.quota_change is not None and a.quota_change.active


# --------------------------------------------------------------------------
# Cuando SI se llama
# --------------------------------------------------------------------------


def test_abre_lo_que_eligio_con_su_multiplicador(budget):
    claude = Claude({"decisions": [decision(ETH.cid, m=0.5), decision(TRX.cid, "skip")],
                     "market_read": "."})
    a = analista(budget, claude)
    [eleccion] = a(contexto(TRX, ETH))
    assert eleccion.candidate is ETH
    assert (eleccion.size_multiplier, eleccion.decider) == (0.5, "ai")
    assert usadas(budget) == 1


def test_el_journal_lleva_la_llamada_y_una_fila_por_candidato(budget):
    claude = Claude({"decisions": [decision(ETH.cid)], "market_read": "."})
    a = analista(budget, claude)
    a(contexto(TRX, ETH))
    [(fila, decisiones)] = a.journal
    assert fila["kind"] == "decision" and fila["valid"] == 1 and fila["n_candidates"] == 2
    assert fila["ts_ms"] == TS
    # El mismo instante que el presupuesto (el juez cuenta la regla 18 con esto).
    [apuntada] = budget.conn.execute("SELECT ts_ms FROM ai_budget_calls").fetchone()
    assert fila["called_ms"] == apuntada
    assert fila["prompt"].startswith("{")
    assert {d["ref"] for d in decisiones} == {TRX.cid, ETH.cid}, "TRX, no mencionado, tambien"


def test_el_orden_es_el_del_modelo_no_el_de_la_confianza(budget):
    """`ai/parser.py`: la confianza se registra, NO se usa."""
    claude = Claude({"decisions": [decision(TRX.cid, conf=0.3), decision(ETH.cid, conf=0.9)],
                     "market_read": "."})
    elecciones = analista(budget, claude)(contexto(TRX, ETH))
    assert [e.candidate.symbol for e in elecciones] == ["TRX/USDC", "ETH/USDC"]


def test_una_salida_invalida_no_abre_nada_y_se_apunta(budget):
    claude = Claude({"decisions": [decision("d-inventado")], "market_read": "."})
    a = analista(budget, claude)
    assert a(contexto(TRX)) == []
    [(fila, decisiones)] = a.journal
    assert fila["valid"] == 0 and decisiones == []
    assert a.quota_change is None


def test_cuota_agotada_entra_en_quota(budget):
    claude = Claude(outcome=CallOutcome.QUOTA, detalle="You've hit your session limit")
    a = analista(budget, claude)
    assert a(contexto(TRX)) == []
    assert a.quota_change is not None and a.quota_change.active
    assert a.journal[0][0]["outcome"] == "quota"


def test_un_timeout_no_cambia_de_modo(budget):
    a = analista(budget, Claude(outcome=CallOutcome.TIMEOUT, detalle="timeout"))
    assert a(contexto(TRX)) == []
    assert a.quota_change is None


# --------------------------------------------------------------------------
# Sondas
# --------------------------------------------------------------------------


def test_sin_quota_no_hay_sonda(budget):
    assert analista(budget, Claude()).sondear() == (None, None)


def test_la_sonda_que_responde_saca_de_quota(budget):
    llamadas = []

    def sonda(**kw):
        llamadas.append(kw)
        return Classification(CallOutcome.OK, "ok")

    a = analista(budget, Claude(), activo=True, sonda=sonda)
    ahora = int(AHORA * 1000) + 46 * 60 * 1000       # pasado el intervalo de 45 min
    fila, cambio = a.sondear(ahora)
    assert llamadas and fila["kind"] == "probe" and fila["called_ms"] == ahora
    assert cambio is not None and not cambio.active
    assert usadas(budget) == 1, "la sonda tambien cuenta para la regla 18"
    assert a.sondear(ahora + 1000) == (None, None), "y no se repite enseguida"


# --------------------------------------------------------------------------
# Revision del 24/09/2026
# --------------------------------------------------------------------------


def test_si_preparar_la_entrada_falla_no_se_gasta_presupuesto(budget, monkeypatch):
    """Antes se apuntaba la llamada y DESPUES se preparaba la entrada: un fallo ahi,
    reintentado cada minuto, se comia las 8 llamadas de la ventana sin hacer ninguna."""
    import ai.decider as modulo

    def rompe(ctx):
        raise ValueError("candidato raro")

    monkeypatch.setattr(modulo, "entrada_de", rompe)
    claude = Claude()
    a = analista(budget, claude)
    assert a(contexto(TRX)) == [], "falla = no hacer nada, sin lanzar"
    assert usadas(budget) == 0 and claude.entradas == []


def test_un_fallo_dentro_no_lanza(budget):
    def revienta(entrada, **kw):
        raise RuntimeError("inesperado")

    a = analista(budget, revienta)
    assert a(contexto(TRX)) == []
    assert usadas(budget) == 1, "la llamada se intento: gasto su hueco (cuenta intentos)"


def test_reintentar_la_misma_vela_no_vuelve_a_llamar(budget):
    """Si la vela no se pudo guardar, el runner recarga y la reintenta. El analista
    devuelve lo mismo y repone el journal (que se perdio), sin otra llamada."""
    claude = Claude({"decisions": [decision(ETH.cid, m=0.5)], "market_read": "."})
    a = analista(budget, claude)
    primera = a(contexto(TRX, ETH))
    journal_1 = list(a.journal)
    a.journal = []                       # lo que hace el runner al recoger el journal
    segunda = a(contexto(TRX, ETH))
    assert len(claude.entradas) == 1 and usadas(budget) == 1
    assert [e.decision_id for e in segunda] == [e.decision_id for e in primera]
    assert segunda[0].size_multiplier == 0.5
    assert a.journal == journal_1


def test_otra_vela_si_vuelve_a_llamar(budget):
    claude = Claude({"decisions": [decision(TRX.cid)], "market_read": "."})
    a = analista(budget, claude)
    a(contexto(TRX))
    a.clock = lambda: AHORA + TF / 1000          # cuatro horas despues, la vela siguiente
    a(contexto(TRX, ts=TS + TF))
    assert len(claude.entradas) == 2


# --------------------------------------------------------------------------
# Con que se decide (protocolo de la fase 6: la muestra se parte si cambia)
# --------------------------------------------------------------------------


def test_cada_fila_lleva_la_huella_del_camino_de_decision(budget):
    from ai.journal import camino

    claude = Claude({"decisions": [decision(ETH.cid)], "market_read": "."})
    a = analista(budget, claude)
    a(contexto(TRX, ETH))
    [(fila, _)] = a.journal
    assert fila["camino"] == camino(load_settings())
    assert len(fila["camino"]) == 12


def test_tambien_las_velas_no_decididas_llevan_la_huella(budget):
    a = analista(budget, Claude(), ahora=AHORA + 3 * TF / 1000)
    a(contexto(ETH))
    [(fila, _)] = a.journal
    assert fila["outcome"] == "skipped_stale" and fila["camino"]


def test_la_huella_cambia_con_lo_que_cambia_la_decision_y_no_con_lo_demas():
    from ai.journal import camino

    s = load_settings()
    base = camino(s)
    assert camino(load_settings()) == base, "reproducible"

    def con(seccion, **cambios):
        return s.model_copy(update={seccion: getattr(s, seccion).model_copy(update=cambios)})

    assert camino(con("claude", model="opus")) != base
    assert camino(con("strategy", min_reward_risk=2.5)) != base
    assert camino(con("risk", target_notional_usd=12.0)) != base
    fees = s.exchange.fees.model_copy(update={"taker_pct": 0.35})
    assert camino(s.model_copy(update={"exchange": s.exchange.model_copy(update={"fees": fees})})) != base
    # Lo que no cambia ninguna decision no parte la muestra.
    assert camino(con("claude", timeout_seconds=120, max_calls_per_day=30)) == base
