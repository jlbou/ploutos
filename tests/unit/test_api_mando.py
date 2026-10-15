"""Los controles del panel (api/mando.py): quien puede pulsarlos y que guardan."""

from __future__ import annotations

import pytest

from api import mando
from core.modes import Mode
from notify import control
from notify.comandos import Orden, reconstruir

AHORA = 1_790_400_000_000
HOST = "ploutos.example.ts.net:8765"


@pytest.fixture
def conn(tmp_path):
    c = control.conectar(tmp_path / "control.db")
    control.migrar(c)
    yield c
    c.close()


def test_solo_el_propio_panel_puede_mandar():
    assert mando.permitido({"x-ploutos-panel": "1", "host": HOST, "origin": f"http://{HOST}"})
    assert mando.permitido({"x-ploutos-panel": "1", "host": HOST})                 # sin Origin (mismo sitio)
    assert not mando.permitido({"host": HOST, "origin": f"http://{HOST}"})           # sin la cabecera
    assert not mando.permitido({"x-ploutos-panel": "1", "host": HOST, "origin": "https://malo.example"})
    assert not mando.permitido({"x-ploutos-panel": "true", "host": HOST})


def test_pausar_y_quitar_la_pausa(conn):
    assert "Pausa" in mando.ejecutar(conn, "pause", "", AHORA)
    assert Mode.CLOSE_ONLY_MANUAL in reconstruir(control.comandos(conn)).modos
    assert "Pausa quitada" in mando.ejecutar(conn, "resume", "", AHORA + 1000)
    assert reconstruir(control.comandos(conn)).modos == {}
    filas = conn.execute("SELECT orden, origen, update_id FROM control_comandos ORDER BY id").fetchall()
    assert [tuple(f) for f in filas] == [("pause", "panel", None), ("resume", "panel", None), ("si", "panel", None)]
    # El /resume intermedio no manda aviso; los demas si (por Telegram, para que quede constancia).
    assert conn.execute("SELECT COUNT(*) FROM paper_avisos").fetchone()[0] == 2


def test_lo_que_no_toca_se_rechaza_sin_guardar_nada(conn):
    for orden, motivo in [("resume", ""), ("levantar_kill", "todo bien"), ("borrar", "")]:
        with pytest.raises(mando.Rechazado):
            mando.ejecutar(conn, orden, motivo, AHORA)
    mando.ejecutar(conn, "kill", "", AHORA)
    with pytest.raises(mando.Rechazado):
        mando.ejecutar(conn, "levantar_kill", "   ", AHORA + 1)               # sin motivo
    assert [r[0] for r in conn.execute("SELECT orden FROM control_comandos")] == ["kill"]


def test_parar_y_levantar_la_parada_con_motivo(conn):
    mando.ejecutar(conn, "kill", "", AHORA)
    assert Mode.HALTED in reconstruir(control.comandos(conn)).modos
    mando.ejecutar(conn, "levantar_kill", "revisado desde el panel", AHORA + 60_000)
    assert reconstruir(control.comandos(conn)).modos == {}


def test_cerrar_todo_deja_el_bot_en_pausa(conn):
    texto = mando.ejecutar(conn, "cerrar_todo", "", AHORA)
    assert "Se venden TODAS" in texto and "<" not in texto
    e = reconstruir(control.comandos(conn))
    assert e.pausa_ms == AHORA and Mode.CLOSE_ONLY_MANUAL in e.modos
    assert [r[0] for r in conn.execute("SELECT orden FROM control_comandos")] == [Orden.CERRAR_TODO.value]
