"""El juez de la fase 1: 72 h sin huecos (`scripts/check_gaps.py`).

BUG REAL (22/09/2026): solo buscaba huecos ENTRE dos velas presentes. Si la
ingesta moria a la hora 60 y se miraba a la 72, las ultimas 12 h sin datos no
contaban como hueco, y decia "CRITERIO CUMPLIDO". Es justo el fallo que el
criterio de 72 h existe para detectar: que el proceso se muera.

Cada test monta una base con velas de 1 h de las 8 monedas y lanza el script
de verdad, mirando su codigo de salida.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from core.clock import utcnow_ms
from core.config import load_settings
from data.coverage import GRACE_MS, Hole, coverage, expected_slots
from data.store.db import open_database

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_gaps.py"
_spec = importlib.util.spec_from_file_location("check_gaps", SCRIPT)
check_gaps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_gaps)

H = 3600 * 1000
SETTINGS = load_settings()


def _ultima_cerrada(now: int) -> int:
    return (now - H - GRACE_MS) // H * H


def lanzar(tmp_path: Path, monkeypatch, quitar=lambda ts: False, desde_h=80,
           extra: list[str] | None = None) -> int:
    """Base con velas de 1 h de las 8 monedas; `quitar(ts)` decide cuales faltan."""
    db_path = tmp_path / "ploutos.db"
    db = open_database(db_path)
    now = utcnow_ms()
    ultima = _ultima_cerrada(now)
    filas = [
        (s, "1h", ts, 1.0, 1.1, 0.9, 1.0, 10.0, 1, "rest", now)
        for s in SETTINGS.whitelist
        for ts in range(ultima - (desde_h - 1) * H, ultima + H, H)
        if not quitar(ts)
    ]
    db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close,"
        " volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        filas,
    )
    db.close()

    ajustes = SETTINGS.model_copy(
        update={"storage": SETTINGS.storage.model_copy(update={"db_path": str(db_path)})}
    )
    monkeypatch.setattr(check_gaps, "load_settings", lambda *_a, **_k: ajustes)
    monkeypatch.setattr(
        sys, "argv", ["check_gaps.py", "--timeframe", "1h", "--hours", "72", *(extra or [])]
    )
    return check_gaps.main()


def test_sin_huecos_se_cumple(tmp_path, monkeypatch):
    assert lanzar(tmp_path, monkeypatch) == 0


def test_hueco_en_medio_no_se_cumple(tmp_path, monkeypatch):
    medio = _ultima_cerrada(utcnow_ms()) - 30 * H
    assert lanzar(tmp_path, monkeypatch, quitar=lambda ts: ts == medio) == 1


def test_la_ingesta_muerta_al_final_NO_se_cumple(tmp_path, monkeypatch):
    """EL CASO DEL BUG: la ingesta se murio hace 12 h y nadie la levanto."""
    corte = _ultima_cerrada(utcnow_ms()) - 12 * H
    assert lanzar(tmp_path, monkeypatch, quitar=lambda ts: ts > corte) == 1


def test_una_sola_vela_final_perdida_tambien_cuenta(tmp_path, monkeypatch):
    ultima = _ultima_cerrada(utcnow_ms())
    assert lanzar(tmp_path, monkeypatch, quitar=lambda ts: ts == ultima) == 1


def test_si_la_ingesta_arranco_hace_menos_de_72_h_aun_no_hay_historia(tmp_path, monkeypatch):
    assert lanzar(tmp_path, monkeypatch, desde_h=40) == 2


def test_una_copia_se_juzga_en_el_instante_en_que_se_hizo(tmp_path, monkeypatch):
    """Simulacro de restauracion (22/09/2026): una copia de hace 12 h, juzgada
    AHORA, tiene 12 h de "hueco" al final que no son un fallo de la ingesta sino
    la edad de la copia. Con --until se juzga en su momento."""
    from datetime import UTC, datetime

    corte = _ultima_cerrada(utcnow_ms()) - 12 * H
    quitar = lambda ts: ts > corte  # noqa: E731
    # 100 h de historia: juzgando 12 h antes, la ventana de 72 h empieza antes.
    assert lanzar(tmp_path, monkeypatch, quitar=quitar, desde_h=100) == 1
    momento = datetime.fromtimestamp((corte + H) / 1000 + 180, tz=UTC)
    (tmp_path / "b").mkdir()
    assert lanzar(tmp_path / "b", monkeypatch, quitar=quitar, desde_h=100,
                  extra=["--until", momento.strftime("%Y-%m-%dT%H:%M")]) == 0


# --------------------------------------------------------------------------
# La cobertura, en pequenyo
# --------------------------------------------------------------------------

S = 60_000        # velas de 1 minuto


def test_las_esperadas_salen_del_reloj():
    slots = expected_slots(since_ms=10 * S + 1, now_ms=20 * S + GRACE_MS, step_ms=S)
    assert slots[0] == 11 * S, "la primera apertura dentro de la ventana"
    assert slots[-1] == 19 * S, "la ultima que ya cerro, con margen"


@pytest.mark.parametrize(
    "faltan, huecos",
    [
        ([], []),
        ([0], [Hole(0, 0, 1)]),                         # al principio
        ([4, 5], [Hole(4 * S, 5 * S, 2)]),              # en medio
        ([8, 9], [Hole(8 * S, 9 * S, 2)]),              # al final: la ingesta muerta
        ([0, 5, 9], [Hole(0, 0, 1), Hole(5 * S, 5 * S, 1), Hole(9 * S, 9 * S, 1)]),
    ],
)
def test_los_huecos_se_ven_esten_donde_esten(faltan, huecos):
    presentes = [i * S for i in range(10) if i not in faltan]
    c = coverage(presentes, since_ms=0, now_ms=10 * S + GRACE_MS, step_ms=S)
    assert c.expected == 10
    assert list(c.holes) == huecos
    assert c.missing == len(faltan)


def test_sin_ninguna_vela_todo_es_hueco():
    c = coverage([], since_ms=0, now_ms=10 * S + GRACE_MS, step_ms=S)
    assert c.missing == c.expected == 10
