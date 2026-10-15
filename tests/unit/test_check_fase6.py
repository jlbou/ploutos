"""El juez de la fase 6 de punta a punta (`scripts/check_fase6.py`), con bases de verdad.

Las bases se llenan por el MISMO camino que el bot (`build_input`/`render`, `call_row`,
`store.record_ai_call`, `store.record_decisions`): si el journal cambia de forma, este
test se entera. Lo que se comprueba es lo que no esta en `portfolio/comparacion.py`:
que lee bien lo guardado, que no ensenya el veredicto antes de tiempo y que para en
seco si los datos no cuadran.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai.invoke import AnalystCall
from ai.journal import call_row, decision_rows
from ai.parser import parse
from ai.prompt import LimitsView, build_input, candidate_ids, position_ids, render
from ai.quota import CallOutcome
from data.store.db import open_database
from features.regime import Regime
from portfolio import store
from strategy.candidates import Candidate, make_decision_id
from tests.risk_fixtures import INSTRUMENTS, MAKER, TAKER

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_fase6.py"
_spec = importlib.util.spec_from_file_location("check_fase6", SCRIPT)
check_fase6 = importlib.util.module_from_spec(_spec)
sys.modules["check_fase6"] = check_fase6
_spec.loader.exec_module(check_fase6)

TF = 4 * 3600 * 1000
T0 = 1_790_092_800_000          # 22/09/2026 16:00 UTC
DIA = 86_400_000
BTC, ETH = "BTC/USDC", "ETH/USDC"


def candidato(symbol, target):
    did = make_decision_id(symbol, "pullback_trend", T0)
    return Candidate(
        cid=did, decision_id=did, symbol=symbol, setup="pullback_trend", timeframe="4h",
        entry=100.0, stop=95.0, target=target, reward_risk=(target - 100) / 5, cost_rt_pct=0.3,
        spread_pct=0.02, regime=Regime.TREND_UP, bar_ts_ms=T0,
        created_at=datetime.fromtimestamp(T0 / 1000, tz=UTC),
    )


# El baseline elige ETH (R:R 3); la IA abre BTC (R:R 2). BTC toca el objetivo, ETH el stop.
C_BTC, C_ETH = candidato(BTC, 110.0), candidato(ETH, 115.0)


def velas(symbol):
    filas = [(symbol, "4h", T0, 100, 100, 100, 100)]
    filas.append((symbol, "4h", T0 + TF, 100, 100.5, 99.5, 100))            # se llena
    if symbol == BTC:
        filas.append((symbol, "4h", T0 + 2 * TF, 100, 111, 100, 110))       # objetivo
    else:
        filas.append((symbol, "4h", T0 + 2 * TF, 100, 100, 94, 95))         # stop
    filas += [(symbol, "4h", T0 + k * TF, 100, 100, 100, 100) for k in range(3, 46)]
    return filas


@pytest.fixture
def bases(tmp_path):
    main = tmp_path / "main.db"
    db = open_database(main)
    db.executemany_sync(
        "INSERT INTO instruments (symbol, base, quote, active, tick_size,"
        " lot_size, min_amount, min_cost, maker_fee, taker_fee, raw, fetched_ms)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(s, s.split("/")[0], "USDC", 1, i.tick_size, i.lot_size, i.min_amount, None,
          MAKER, TAKER, "{}", T0) for s, i in INSTRUMENTS.items()],
    )
    db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low,"
        " close, volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,100,1,'rest',?)",
        [(*f, T0) for s in (BTC, ETH) for f in velas(s)],
    )
    db.close()

    filas_cand = [(c.decision_id, c.symbol, c.setup, "candidate", str(c)) for c in (C_BTC, C_ETH)]
    ai = store.connect(tmp_path / "ai.db")
    store.migrate(ai)
    entrada = build_input(
        now=datetime.fromtimestamp(T0 / 1000, tz=UTC), mode="NORMAL", equity_usd=50,
        free_quote_usd=50, positions=[], limits=LimitsView(3, 1, 0.5, 3.0, 6),
        candidates=[C_BTC, C_ETH],
    )
    salida = {"decisions": [
        {"type": "open", "ref": C_BTC.cid, "confidence": 0.7, "reasons": ["a"], "risks": []},
        {"type": "skip", "ref": C_ETH.cid, "confidence": 0.6, "reasons": ["b"], "risks": []},
    ], "market_read": "."}
    llamada = AnalystCall(CallOutcome.OK, parse(salida, candidate_ids(entrada), position_ids(entrada)),
                          10.0, "ok", structured=salida)
    store.record_ai_call(ai, call_row(llamada, ts_ms=T0, called_ms=T0 + TF + 60_000,
                                      kind="decision", prompt=render(entrada), n_candidates=2,
                                      camino="huella000001"), decision_rows(llamada))
    store.record_decisions(ai, T0, filas_cand)
    ai.close()

    base = store.connect(tmp_path / "paper.db")
    store.migrate(base)
    store.record_decisions(base, T0, filas_cand)
    base.close()
    return tmp_path


def juez(bases, capsys, monkeypatch, ahora):
    monkeypatch.setattr(sys, "argv", [
        "check_fase6.py", "--main-db", str(bases / "main.db"), "--paper-db",
        str(bases / "paper.db"), "--ai-db", str(bases / "ai.db"), "--ahora-ms", str(ahora)])
    codigo = check_fase6.main()
    return codigo, capsys.readouterr().out


def test_antes_de_tiempo_solo_dice_si_los_datos_estan_bien(bases, capsys, monkeypatch):
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 10 * DIA)
    assert codigo == 2
    assert "todavia no" in out and "M1" not in out, "el resultado no se ensenya a mitad"
    assert "discrepan: 1 de 30" in out
    assert "juzgables: 1 velas" in out
    assert "OK    mismos candidatos en las dos carteras (2 comparados)" in out


def test_al_llegar_el_tope_da_el_veredicto(bases, capsys, monkeypatch):
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 60 * DIA)
    assert codigo == 0
    # La IA abrio el ganador y el baseline el perdedor: M1 claramente positivo...
    assert "M1, seleccion" in out and "media +" in out
    # ...pero una sola discrepancia no demuestra nada.
    assert out.rstrip().endswith("VEREDICTO: NO CONCLUYENTE")


def test_si_las_carteras_no_ven_los_mismos_numeros_para_en_seco(bases, capsys, monkeypatch):
    base = store.connect(bases / "paper.db")
    with base:
        base.execute("UPDATE paper_decisions SET detail = replace(detail, 'stop 95', 'stop 96')"
                     " WHERE symbol = ?", (ETH,))
    base.close()
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 60 * DIA)
    assert codigo == 1 and "NO cuadran" in out and "VEREDICTO" not in out


def test_si_el_journal_no_cuadra_con_la_salida_guardada_para_en_seco(bases, capsys, monkeypatch):
    ai = store.connect(bases / "ai.db")
    with ai:
        ai.execute("UPDATE ai_decisions SET type = 'skip' WHERE ref = ?", (C_BTC.cid,))
    ai.close()
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 60 * DIA)
    assert codigo == 1 and "no son los de la salida guardada" in out


def test_si_no_entiende_los_numeros_del_baseline_para_en_seco(bases, capsys, monkeypatch):
    """Si cambia el formato del texto guardado, el juez no puede comparar: no puede salir en verde."""
    base = store.connect(bases / "paper.db")
    with base:
        base.execute("UPDATE paper_decisions SET detail = 'otro formato' WHERE kind = 'candidate'")
    base.close()
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 60 * DIA)
    assert codigo == 1 and "no se entienden los numeros del baseline" in out


def test_si_no_hay_ningun_candidato_comun_para_en_seco(bases, capsys, monkeypatch):
    base = store.connect(bases / "paper.db")
    with base:
        base.execute("UPDATE paper_decisions SET decision_id = 'otro-' || decision_id WHERE kind = 'candidate'")
    base.close()
    codigo, out = juez(bases, capsys, monkeypatch, T0 + 60 * DIA)
    assert codigo == 1 and "0 comparados" in out and "no se ha podido comprobar" in out
