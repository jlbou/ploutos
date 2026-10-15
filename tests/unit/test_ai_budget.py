"""El presupuesto de la regla 18 (`ai/budget.py`)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai.budget import CallBudget
from core.config import load_settings

H = 3600 * 1000
T0 = 1_790_035_200_000        # 22/09/2026 00:00 UTC


def abrir(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "paper.db"


def test_lo_de_la_configuracion_es_40_y_8(db):
    b = CallBudget.from_settings(abrir(db), load_settings())
    assert (b.per_day, b.per_window) == (40, 8)


def test_la_novena_llamada_en_5_horas_no_sale(db):
    b = CallBudget(abrir(db), 40, 8)
    for i in range(8):
        assert b.try_acquire(T0 + i * 60_000).allowed
    no = b.try_acquire(T0 + 9 * 60_000)
    assert not no.allowed and "5 h" in no.reason


def test_la_ventana_es_movil(db):
    """5 h despues de la primera, esa ya no cuenta y hay sitio para una."""
    b = CallBudget(abrir(db), 40, 8)
    for i in range(8):
        b.try_acquire(T0 + i * 60_000)
    assert not b.try_acquire(T0 + 5 * H - 1).allowed
    assert b.try_acquire(T0 + 5 * H + 1).allowed


def test_el_tope_diario_y_el_reinicio_a_las_00_utc(db):
    b = CallBudget(abrir(db), 3, 3)
    for i in range(3):
        assert b.try_acquire(T0 + i * H).allowed
    assert "hoy" in b.try_acquire(T0 + 20 * H).reason
    assert b.try_acquire(T0 + 24 * H + 60_000).allowed, "dia nuevo"


def test_una_llamada_denegada_no_se_apunta(db):
    b = CallBudget(abrir(db), 40, 1)
    b.try_acquire(T0)
    for i in range(5):
        b.try_acquire(T0 + i)
    assert b.check(T0 + 10).used_window == 1


def test_sobrevive_al_reinicio(db):
    """La leccion de las reglas 10, 11 y 14: lo que vive en memoria se pierde."""
    b = CallBudget(abrir(db), 40, 8)
    for i in range(8):
        b.try_acquire(T0 + i)
    b.conn.close()
    otro = CallBudget(abrir(db), 40, 8)
    assert not otro.check(T0 + 100).allowed


def test_dos_procesos_no_se_quedan_el_mismo_hueco(db):
    uno = CallBudget(abrir(db), 40, 1)
    dos = CallBudget(abrir(db), 40, 1)
    resultados = [uno.try_acquire(T0).allowed, dos.try_acquire(T0 + 1).allowed]
    assert resultados == [True, False]


def test_las_sondas_tambien_cuentan(db):
    """Una sonda de CLOSE_ONLY_QUOTA es una llamada: gasta cuota igual."""
    b = CallBudget(abrir(db), 40, 2)
    b.try_acquire(T0, kind="probe")
    b.try_acquire(T0 + 1, kind="decision")
    assert not b.try_acquire(T0 + 2).allowed


def test_una_ventana_mayor_que_el_dia_no_tiene_sentido(db):
    with pytest.raises(ValueError, match="regla 18"):
        CallBudget(abrir(db), 5, 8)
