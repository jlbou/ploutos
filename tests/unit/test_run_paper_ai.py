"""El servicio de la cartera de la IA (`scripts/run_paper_ai.py`, pieza 9).

Lo que se protege aqui es lo que NO esta en el decisor: que sin token no
arranca, que entrar en CLOSE_ONLY_QUOTA se guarda con la vela, que la sonda
que responde saca del modo y se guarda YA (un reinicio no puede devolverlo a
QUOTA), y que todo sobrevive a un reinicio.
"""

from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from ai.quota import CallOutcome, Classification, QuotaChange
from core.modes import Mode
from data.store.db import open_database
from portfolio import store
from tests.risk_fixtures import INSTRUMENTS, MAKER, TAKER

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_ai.py"
_spec = importlib.util.spec_from_file_location("run_paper_ai", SCRIPT)
run_paper_ai = importlib.util.module_from_spec(_spec)
sys.modules["run_paper_ai"] = run_paper_ai
_spec.loader.exec_module(run_paper_ai)

BAR_MS = 4 * 60 * 60 * 1000
T0 = 1_790_092_800_000   # 22/09/2026 16:00 UTC


def _main_db(tmp_path: Path) -> Path:
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
        " close, volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(s, "4h", T0 + k * BAR_MS, 1.0, 1.1, 0.9, 1.0, 100.0, 1, "rest", T0)
         for s in INSTRUMENTS for k in range(2)],
    )
    db.close()
    return main


class Reloj:
    def __init__(self, ms: int):
        self.ms = ms

    def __call__(self) -> float:
        return self.ms / 1000


@pytest.fixture
def args(tmp_path):
    return Namespace(tf="4h", equity=50.0, slider=3, main_db=str(_main_db(tmp_path)),
                     paper_db=str(tmp_path / "paper-ai.db"), news_db=str(tmp_path / "news.db"),
                     control_db=str(tmp_path / "control.db"))


def arrancar(args, reloj, sonda=None):
    r = run_paper_ai.AIPaperRunner(
        args, token="token-falso", clock=reloj,
        _call=lambda *a, **kw: pytest.fail("sin candidatos no se llama a Claude"),
        _probe=sonda or (lambda **kw: Classification(CallOutcome.OK, "ok")),
    )
    r.usdc_mids = lambda: {"USDC/USDT": 1.0, "USDT/USD": 1.0, "BTC/USD": 60000.0, "BTC/USDC": 60000.0}
    return r


def cerrar(r):
    r.main.close()
    r.paper.close()


def test_sin_token_no_arranca(args, monkeypatch):
    """Sin token no hay IA que medir. Salida 2, que systemd no reintenta."""
    monkeypatch.setattr(run_paper_ai, "Secrets", lambda: type("S", (), {"claude_code_oauth_token": None})())
    with pytest.raises(SystemExit) as salida:
        run_paper_ai.AIPaperRunner(args)
    assert salida.value.code == 2


def test_es_la_cartera_de_la_ia(args):
    r = arrancar(args, Reloj(T0 + 2 * BAR_MS))
    assert (r.DECIDER, r.SERVICIO) == ("ai", "ploutos-paper-ai")
    assert r.loop.decide is not None, "el bucle decide con el analista, no con rank"
    cerrar(r)


def test_entrar_en_quota_se_guarda_con_la_vela(args):
    reloj = Reloj(T0 + 2 * BAR_MS)
    r = arrancar(args, reloj)
    # Como si la llamada de esta vela hubiera chocado con la cuota.
    original = r.analista.__call__

    def choca(ctx):
        eleccion = original(ctx)
        r.analista.quota_change = QuotaChange(True, "cuota: You've hit your session limit")
        return eleccion

    r.analista = type("A", (), {"__call__": staticmethod(choca), "journal": [],
                                "quota_change": None, "sondear": r.analista.sondear})()
    # Una entrada pendiente que QUOTA tiene que cancelar (precio lejos: no se llena).
    assert r.broker.submit("d-pendiente", "BTC/USDC", 1.0, 0.5, 0.45, 0.6, "pullback_trend", T0 - BAR_MS)
    r.catch_up()
    [aviso] = r.paper.execute("SELECT texto FROM paper_avisos WHERE tipo = 'modo'").fetchall()
    assert "canceladas: 1" in aviso["texto"], "el aviso dice las que cancelo QUOTA"
    filas = r.paper.execute("SELECT ts_ms, mode, activated FROM paper_mode_changes").fetchall()
    # La primera vela que se proceso (T0) es donde "choco": se guarda con SU marca, y
    # en la segunda ya estaba en QUOTA y no se apunta otra vez.
    assert [tuple(f) for f in filas] == [(T0, "CLOSE_ONLY_QUOTA", 1)]
    assert Mode.CLOSE_ONLY_QUOTA in r.loop.modes.active
    cerrar(r)


def test_la_sonda_saca_de_quota_y_se_guarda_ya(args):
    reloj = Reloj(T0 + 2 * BAR_MS)
    r = arrancar(args, reloj)
    r.catch_up()
    r.loop.set_quota_mode(True, "cuota")
    store.record_mode_changes(r.paper, reloj.ms, [("CLOSE_ONLY_QUOTA", True, "cuota", "CLOSE_ONLY_QUOTA")])
    cerrar(r)

    # Reinicio: el modo vuelve de la base y el rastreador lo sabe.
    r = arrancar(args, reloj)
    assert Mode.CLOSE_ONLY_QUOTA in r.loop.modes.active
    r._between_candles()
    assert r.paper.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0, "aun no toca sondear"

    reloj.ms += 46 * 60 * 1000
    r._between_candles()
    [sonda] = r.paper.execute("SELECT kind, outcome, called_ms FROM ai_calls").fetchall()
    assert tuple(sonda) == ("probe", "ok", reloj.ms)
    assert Mode.CLOSE_ONLY_QUOTA not in r.loop.modes.active
    cerrar(r)

    # Otro reinicio: sigue fuera de QUOTA, porque la salida se guardo en el momento.
    r = arrancar(args, reloj)
    assert r.loop.modes.effective is Mode.NORMAL
    cerrar(r)


def test_una_sonda_que_falla_no_saca_de_quota(args):
    reloj = Reloj(T0 + 2 * BAR_MS)
    r = arrancar(args, reloj, sonda=lambda **kw: Classification(CallOutcome.QUOTA, "sin cuota"))
    r.loop.set_quota_mode(True, "cuota")
    r.analista.tracker = type(r.analista.tracker).from_active(True, reloj.ms)
    reloj.ms += 46 * 60 * 1000
    r._between_candles()
    assert Mode.CLOSE_ONLY_QUOTA in r.loop.modes.active
    assert r.paper.execute("SELECT outcome FROM ai_calls").fetchone()[0] == "quota"
    cerrar(r)


def test_la_sombra_esta_enchufada_al_analista(args, monkeypatch):
    """02/10, opcion B: el bucle de la IA lleva la sombra y la manda al analista; el del baseline no la tiene."""
    r = arrancar(args, Reloj(T0 + 2 * BAR_MS))
    assert r.loop.sombra is not None
    vistos = []
    monkeypatch.setattr(r.analista, "sombra", vistos.append)
    r.loop.sombra("contexto")
    assert vistos == ["contexto"]
    cerrar(r)
    rp = run_paper_ai.rp
    assert rp.PaperRunner._sombra(None) is None, "el baseline (grupo de control) va sin sombra"
