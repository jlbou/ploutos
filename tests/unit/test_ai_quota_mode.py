"""CLOSE_ONLY_QUOTA (pieza 7 de la fase 3): el seguidor, la sonda y el bucle."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai.invoke import PROBE_PROMPT, probe_claude
from ai.quota import (
    CAUSA_PRESUPUESTO,
    PROBE_INTERVAL_MS,
    CallOutcome,
    QuotaTracker,
)
from core.config import load_settings
from core.modes import Mode
from features.context import CorrelationMatrix
from portfolio import store
from portfolio.loop import TradingLoop
from portfolio.paper import OrderState, PaperBroker, PaperLedger
from tests.risk_fixtures import INSTRUMENTS

T0 = 1_790_035_200_000
MIN = 60_000


# --------------------------------------------------------------------------
# El seguidor
# --------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", [CallOutcome.QUOTA, CallOutcome.AUTH])
def test_cuota_o_login_entran(outcome):
    t = QuotaTracker()
    cambio = t.on_outcome(outcome, "You've hit your session limit", T0)
    assert cambio is not None and cambio.active and t.active


@pytest.mark.parametrize("outcome", [CallOutcome.TIMEOUT, CallOutcome.ERROR, CallOutcome.OK])
def test_timeout_error_o_ok_no_entran(outcome):
    t = QuotaTracker()
    assert t.on_outcome(outcome, "x", T0) is None and not t.active


def test_el_presupuesto_agotado_tambien_entra():
    t = QuotaTracker()
    cambio = t.on_budget_denied("regla 18: 8 llamadas en 5 h", T0)
    assert cambio.active and t.cause == CAUSA_PRESUPUESTO


def test_entrar_dos_veces_no_es_un_cambio():
    t = QuotaTracker()
    t.on_outcome(CallOutcome.QUOTA, "x", T0)
    assert t.on_outcome(CallOutcome.AUTH, "y", T0 + MIN) is None


def test_se_sale_cuando_una_llamada_responde_bien():
    t = QuotaTracker()
    t.on_outcome(CallOutcome.QUOTA, "x", T0)
    cambio = t.on_outcome(CallOutcome.OK, "ok", T0 + 50 * MIN)
    assert cambio is not None and not cambio.active and not t.active


def test_un_timeout_durante_el_modo_no_saca():
    t = QuotaTracker()
    t.on_outcome(CallOutcome.QUOTA, "x", T0)
    assert t.on_outcome(CallOutcome.TIMEOUT, "", T0 + MIN) is None and t.active


def test_la_sonda_espera_su_intervalo():
    """Informe 3.1: una sonda cada 30-60 min, no en cada vuelta."""
    t = QuotaTracker()
    assert not t.should_probe(T0), "sin modo activo no hay sonda"
    t.on_outcome(CallOutcome.QUOTA, "x", T0)
    assert not t.should_probe(T0 + PROBE_INTERVAL_MS - 1)
    assert t.should_probe(T0 + PROBE_INTERVAL_MS)
    t.mark_probe(T0 + PROBE_INTERVAL_MS)
    assert not t.should_probe(T0 + PROBE_INTERVAL_MS + MIN)
    assert t.should_probe(T0 + 2 * PROBE_INTERVAL_MS)


def test_tras_un_reinicio_se_sigue_en_el_modo_y_se_sondea():
    t = QuotaTracker.from_active(True, T0)
    assert t.active and not t.should_probe(T0)
    assert t.should_probe(T0 + PROBE_INTERVAL_MS)
    assert t.on_outcome(CallOutcome.OK, "ok", T0 + PROBE_INTERVAL_MS).active is False


# --------------------------------------------------------------------------
# La sonda
# --------------------------------------------------------------------------


class FakeRun:
    def __init__(self, stdout="", returncode=0, timeout=False):
        self.stdout, self.returncode, self.timeout = stdout, returncode, timeout
        self.args = self.kwargs = None

    def __call__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        if self.timeout:
            raise subprocess.TimeoutExpired(args, 1)
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


def test_la_sonda_es_minima_y_sin_herramientas(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "clave-okx-falsa")
    fake = FakeRun('{"is_error": false, "result": "ok"}')
    c = probe_claude(token="tok", config_dir=tmp_path, claude_bin="claude", _run=fake)
    assert c.outcome is CallOutcome.OK
    assert fake.args[:3] == ["claude", "-p", PROBE_PROMPT]
    assert "--restricted" in fake.args and "--json-schema" not in fake.args
    assert "OKX_API_KEY" not in fake.kwargs["env"], "regla 19 tambien en la sonda"


def test_la_sonda_detecta_el_login_caducado(tmp_path):
    fake = FakeRun('{"is_error": true, "result": "Not logged in · Please run /login"}', 1)
    assert probe_claude(token="t", config_dir=tmp_path, claude_bin="c", _run=fake).outcome is CallOutcome.AUTH


def test_la_sonda_no_revienta_con_timeout(tmp_path):
    fake = FakeRun(timeout=True)
    assert probe_claude(token="t", config_dir=tmp_path, claude_bin="c", _run=fake).outcome is CallOutcome.TIMEOUT


# --------------------------------------------------------------------------
# El bucle
# --------------------------------------------------------------------------


def bucle():
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    return broker, TradingLoop(instruments=INSTRUMENTS, cost=None, settings=load_settings(),
                               broker=broker, ledger=ledger)


def test_entrar_en_quota_cancela_las_pendientes_y_el_motor_lo_ve():
    broker, loop = bucle()
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    cambio, canceladas = loop.set_quota_mode(True, "cuota: session limit")
    assert cambio is not None and canceladas == 1
    assert broker.orders[0].state is OrderState.CANCELLED
    st = loop._state(datetime.fromtimestamp(T0 / 1000, tz=UTC), {}, CorrelationMatrix())
    assert st.mode is Mode.CLOSE_ONLY_QUOTA, "la regla 18 del motor mira el modo"


def test_salir_de_quota_no_levanta_otros_modos():
    _b, loop = bucle()
    loop.modes.activate(Mode.CLOSE_ONLY_CAPITAL, "regla 7")
    loop.set_quota_mode(True, "cuota")
    loop.set_quota_mode(False, "responde")
    assert loop.modes.effective is Mode.CLOSE_ONLY_CAPITAL


def test_si_ya_estaba_en_solo_cierre_no_se_cancela_nada_de_nuevo():
    broker, loop = bucle()
    loop.modes.activate(Mode.CLOSE_ONLY_DAILY, "regla 10")
    _c, canceladas = loop.set_quota_mode(True, "cuota")
    assert canceladas == 0


def test_la_salida_por_sonda_se_guarda_al_momento(tmp_path: Path):
    """Pasa FUERA de una vela: si no se guardara ya, un reinicio antes de la
    vela siguiente dejaria el modo puesto."""
    conn = store.connect(tmp_path / "p.db")
    store.migrate(conn)
    _b, loop = bucle()
    entra, _ = loop.set_quota_mode(True, "cuota")
    sale, _ = loop.set_quota_mode(False, "Claude vuelve a responder")
    for i, c in enumerate((entra, sale)):
        store.record_mode_changes(
            conn, T0 + i, [(c.mode.name, c.activated, c.reason, c.effective_after.name)]
        )
    assert store.load_modes(conn).effective is Mode.NORMAL


def test_una_pendiente_que_sobrevive_a_un_reinicio_en_solo_cierre_se_cancela():
    """Revision del 23/09/2026: el cambio de modo se guardo sin el estado, el
    proceso se reinicio, y volvio QUOTA con una pendiente viva. La primera vela
    tiene que cancelarla: el invariante es 'en solo cierre no hay pendientes',
    no 'cancelar al pasar de NORMAL a solo cierre'."""
    broker, loop = bucle()
    loop.modes.activate(Mode.CLOSE_ONLY_QUOTA, "cuota (reconstruido de la base)")
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    r = loop.step(T0 + 4 * 3600 * 1000, {}, {}, {}, usdc_deviation_pct=0.0)
    assert r.cancelled == 1
    assert broker.orders[0].state is OrderState.CANCELLED
