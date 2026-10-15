"""El journal del analista (pieza 8 de la fase 3): `ai/journal.py` y `portfolio/store.py`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ai.invoke import AnalystCall
from ai.journal import SKIPPED_BUDGET, SKIPPED_QUOTA, call_row, decision_rows, skipped_row
from ai.parser import parse
from ai.quota import CallOutcome
from portfolio import store

T0 = 1_790_035_200_000
CANDS = {"d-a", "d-b"}
POS = {"d-p"}


def llamada(structured, outcome=CallOutcome.OK, detail="ok"):
    parsed = parse(structured, CANDS, POS) if outcome is CallOutcome.OK \
        else parse(None, CANDS, POS)
    return AnalystCall(outcome=outcome, parsed=parsed, latency_s=12.3456, detail=detail,
                       input_tokens=2, output_tokens=600, cache_created=17000,
                       cost_usd_equiv=0.0745, num_turns=2, structured=structured,
                       result_text="{...}")


BUENA = {"decisions": [
    {"type": "open", "ref": "d-a", "confidence": 0.6, "size_multiplier": 0.8,
     "reasons": ["ADX alto"], "risks": ["correlacion"]},
    {"type": "skip", "ref": "d-b", "confidence": 0.5, "reasons": ["R:R flojo"]},
    {"type": "hold", "ref": "d-p", "confidence": 0.7, "reasons": ["sigue en tendencia"]},
], "market_read": "alcista"}


@pytest.fixture
def conn(tmp_path: Path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    yield c
    c.close()


def test_una_llamada_valida_deja_la_llamada_y_sus_decisiones(conn):
    call = llamada(BUENA)
    fila = call_row(call, ts_ms=T0, called_ms=T0 + 5, kind="decision",
                    prompt='{"candidates": []}', n_candidates=2)
    call_id = store.record_ai_call(conn, fila, decision_rows(call))
    c = conn.execute("SELECT * FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    assert (c["outcome"], c["valid"], c["cost_usd_equiv"]) == ("ok", 1, 0.0745)
    assert json.loads(c["structured"])["market_read"] == "alcista"
    ds = {d["ref"]: d for d in conn.execute("SELECT * FROM ai_decisions WHERE call_id = ?", (call_id,))}
    assert ds["d-a"]["size_multiplier"] == 0.8 and ds["d-a"]["executed"] == 1
    assert ds["d-p"]["executed"] == 0, "decision D: hold se registra pero no se ejecuta"
    assert json.loads(ds["d-b"]["reasons"]) == ["R:R flojo"]


def test_una_salida_invalida_guarda_lo_crudo_y_el_motivo_del_parser(conn):
    mala = {"decisions": [{"type": "open", "ref": "d-inventado", "confidence": 0.9,
                           "reasons": ["x"]}], "market_read": "."}
    call = llamada(mala)
    fila = call_row(call, ts_ms=T0, called_ms=T0, kind="decision", prompt="p", n_candidates=2)
    assert decision_rows(call) == []
    call_id = store.record_ai_call(conn, fila)
    c = conn.execute("SELECT * FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    assert c["valid"] == 0 and "inventado" in c["reason"]
    assert "d-inventado" in c["structured"], "lo crudo, para poder explicarlo despues"


def test_un_fallo_de_llamada_guarda_el_detalle_de_la_llamada(conn):
    call = llamada(None, CallOutcome.QUOTA, "You've hit your session limit")
    fila = call_row(call, ts_ms=T0, called_ms=T0, kind="decision", prompt="p", n_candidates=1)
    assert fila["outcome"] == "quota" and "session limit" in fila["reason"]


@pytest.mark.parametrize("motivo", [SKIPPED_BUDGET, SKIPPED_QUOTA])
def test_cuando_no_se_llama_tambien_queda_fila(conn, motivo):
    """Sin esta fila, 'por que no se hizo nada' no tendria respuesta."""
    store.record_ai_call(conn, skipped_row(ts_ms=T0, called_ms=T0, outcome=motivo,
                                           reason="regla 18: 8 en 5 h", n_candidates=3))
    c = conn.execute("SELECT * FROM ai_calls").fetchone()
    assert (c["outcome"], c["valid"], c["n_candidates"]) == (motivo, 0, 3)


def test_un_motivo_de_no_llamar_inventado_no_vale():
    with pytest.raises(ValueError):
        skipped_row(ts_ms=T0, called_ms=T0, outcome="porque si", reason="", n_candidates=0)


def test_una_columna_desconocida_es_un_error_no_un_silencio(conn):
    with pytest.raises(ValueError, match="columnas desconocidas"):
        store.record_ai_call(conn, {"ts_ms": T0, "clave_inventada": 1})


def test_va_en_la_misma_transaccion_que_la_vela(conn):
    """El journal del analista viaja con `save_step`: o se guarda la vela entera
    o nada (la leccion de las dos transacciones del 22/09)."""
    from portfolio.paper import PaperBroker, PaperLedger
    from tests.risk_fixtures import INSTRUMENTS

    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    ledger.record(T0, {})
    call = llamada(BUENA)
    fila = call_row(call, ts_ms=T0, called_ms=T0, kind="decision", prompt="p", n_candidates=2)
    store.save_step(conn, broker, ledger, "4h", T0, [], ai_calls=[(fila, decision_rows(call))])
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ai_decisions").fetchone()[0] == 3


def test_el_multiplicador_del_journal_es_el_que_se_usa(conn):
    """Revision del 23/09/2026: un open sin size_multiplier se ejecuta a 1,0; el
    journal decia NULL."""
    sin = {"decisions": [{"type": "open", "ref": "d-a", "confidence": 0.6, "reasons": ["x"]}],
           "market_read": "."}
    filas = {f["ref"]: f for f in decision_rows(llamada(sin))}
    assert filas["d-a"]["size_multiplier"] == 1.0


def test_los_candidatos_no_mencionados_tambien_tienen_fila(conn):
    """Sin ella, 'que decidio la IA sobre d-b' no tendria respuesta."""
    solo_a = {"decisions": [{"type": "open", "ref": "d-a", "confidence": 0.6, "reasons": ["x"]}],
              "market_read": "."}
    call = llamada(solo_a)
    fila = call_row(call, ts_ms=T0, called_ms=T0, kind="decision", prompt="p", n_candidates=2)
    call_id = store.record_ai_call(conn, fila, decision_rows(call))
    b = conn.execute("SELECT * FROM ai_decisions WHERE call_id = ? AND ref = 'd-b'",
                     (call_id,)).fetchone()
    assert b["type"] == "skip" and b["confidence"] is None
    assert "no mencionado" in json.loads(b["reasons"])[0]


def test_una_columna_obligatoria_que_falta_se_dice_antes_de_tocar_la_base(conn):
    with pytest.raises(ValueError, match="obligatorias.*reason"):
        store.record_ai_call(conn, {"ts_ms": T0, "called_ms": T0, "kind": "decision",
                                    "outcome": "ok", "valid": 1, "n_candidates": 1})


def test_si_falla_el_journal_no_se_guarda_nada_de_la_vela(conn):
    """El journal va en la transaccion de la vela: si revienta, ni estado, ni
    cursor, ni llamada."""
    from portfolio.paper import PaperBroker, PaperLedger
    from tests.risk_fixtures import INSTRUMENTS

    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    ledger.record(T0, {})
    call = llamada(BUENA)
    fila = call_row(call, ts_ms=T0, called_ms=T0, kind="decision", prompt="p", n_candidates=2)
    repetidas = decision_rows(call) + decision_rows(call)[:1]    # clave (llamada, ref) repetida
    with pytest.raises(sqlite3.IntegrityError):
        store.save_step(conn, broker, ledger, "4h", T0, [], ai_calls=[(fila, repetidas)])
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM paper_equity").fetchone()[0] == 0
    assert store.cursor(conn, "4h") is None


def test_se_guarda_con_que_camino_y_que_modelo_se_decidio(conn):
    """Protocolo de la fase 6: sin esto, un cambio a mitad mezclaria dos IAs."""
    from dataclasses import replace

    call = replace(llamada(BUENA), modelo="claude-sonnet-x")
    fila = call_row(call, ts_ms=T0, called_ms=T0 + 5, kind="decision",
                    prompt="{}", n_candidates=2, camino="abc123def456")
    call_id = store.record_ai_call(conn, fila, decision_rows(call))
    c = conn.execute("SELECT camino, modelo FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    assert (c["camino"], c["modelo"]) == ("abc123def456", "claude-sonnet-x")
    s = skipped_row(ts_ms=T0, called_ms=T0, outcome=SKIPPED_BUDGET, reason="x",
                    n_candidates=1, camino="abc123def456")
    otra = store.record_ai_call(conn, s)
    assert conn.execute("SELECT camino FROM ai_calls WHERE id = ?", (otra,)).fetchone()[0] == "abc123def456"
