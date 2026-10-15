"""La ingesta sale de DEGRADED tras 10 min SEGUIDOS sana (`scripts/run_ingest.py`, fase 4 pieza d), sin red."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from core.modes import Mode, ModeMachine
from core.salud import Salud

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("run_ingest", RAIZ / "scripts" / "run_ingest.py")
ri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ri)


class Vigia:
    def __init__(self):
        self.mal = False

    def exchange_is_degraded(self):
        return self.mal

    def stale_symbols(self):
        return {"BTC/USDC"} if self.mal else set()


class Repo:
    def __init__(self):
        self.cambios = []

    async def record(self, cambio):
        self.cambios.append(cambio)


class Bus:
    def emit(self, *a, **k):
        pass


def runner(monkeypatch, reloj):
    r = ri.IngestService.__new__(ri.IngestService)
    r.modes, r.salud, r.staleness, r.mode_repo, r.bus = ModeMachine(), Salud(), Vigia(), Repo(), Bus()
    monkeypatch.setattr(ri, "utcnow_ms", lambda: reloj[0])
    return r


async def test_entra_al_momento_y_sale_solo_tras_10_min_sana(monkeypatch):
    reloj = [1_790_352_000_000]
    r = runner(monkeypatch, reloj)
    r.staleness.mal = True
    await r._update_degraded_mode()
    assert Mode.CLOSE_ONLY_DEGRADED in r.modes.active
    r.staleness.mal = False
    for minuto in range(1, 10):
        reloj[0] += 60_000
        await r._update_degraded_mode()
        assert Mode.CLOSE_ONLY_DEGRADED in r.modes.active, f"a los {minuto} min aun no sale"
    reloj[0] += 60_000
    await r._update_degraded_mode()
    reloj[0] += 60_000
    await r._update_degraded_mode()
    assert Mode.CLOSE_ONLY_DEGRADED not in r.modes.active
    assert [c.activated for c in r.mode_repo.cambios] == [True, False]


async def test_una_recaida_vuelve_a_empezar_la_cuenta(monkeypatch):
    reloj = [1_790_352_000_000]
    r = runner(monkeypatch, reloj)
    r.staleness.mal = True
    await r._update_degraded_mode()
    r.staleness.mal = False
    for _ in range(8):
        reloj[0] += 60_000
        await r._update_degraded_mode()
    r.staleness.mal = True
    reloj[0] += 60_000
    await r._update_degraded_mode()
    r.staleness.mal = False
    for _ in range(8):
        reloj[0] += 60_000
        await r._update_degraded_mode()
    assert Mode.CLOSE_ONLY_DEGRADED in r.modes.active, "8 min sana tras la recaida: aun no"
