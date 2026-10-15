"""El juez de los comandos (`scripts/check_control.py`) sobre bases escritas por el servicio de VERDAD
(`run_telegram.TelegramRunner`, con Telegram falso). Despues se estropea una cosa cada vez."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from notify import comandos as cmds
from portfolio import store

RAIZ = Path(__file__).resolve().parents[2] / "scripts"


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


check_control = _cargar("check_control")
from tests.unit.test_run_telegram import (  # noqa: E402
    T0, Enviar, Latido, Reloj, Secretos, Telegram, mensaje, run_telegram,
)

H4 = 4 * 3600_000


class Servicio:
    """El servicio de verdad, con una vuelta cada 30 s."""

    def __init__(self, tmp_path, enviar=None):
        self.tg, self.reloj = Telegram(), Reloj()
        self.r = run_telegram.TelegramRunner(
            tmp_path / "control.db", carteras={}, news_db=tmp_path / "news.db", secretos=Secretos(),
            _call=self.tg, _enviar=enviar or Enviar(), _latido=Latido(), _reloj=self.reloj)
        self.uid = 0

    def hasta(self, ms, paso=30_000):
        while self.reloj.ms < ms:
            self.r.vuelta()
            self.reloj.ms += paso

    def manda(self, texto):
        self.uid += 1
        self.tg.cola.append(mensaje(self.uid, texto, segundos=(self.reloj.ms - T0) // 1000))


def cartera(tmp_path, nombre, cambios, velas=6):
    """Una base de cartera con `velas` velas desde T0 y los cambios de modo (ts, modo, activado)."""
    c = store.connect(tmp_path / f"{nombre}.db")
    store.migrate(c)
    with c:
        for i in range(velas):
            c.execute("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                      (T0 + i * H4, 50.0, 0, 0))
        for ts, modo, activado in cambios:
            c.execute("INSERT INTO paper_mode_changes (ts_ms, mode, activated, reason, effective_after)"
                      " VALUES (?,?,?,?,?)", (ts, modo, int(activado), "x", modo if activado else "NORMAL"))
    return c


def fallos(checks):
    return {c.nombre: c.fallos for c in checks if not c.ok}


@pytest.fixture
def escenario(tmp_path):
    """/pause a mitad de la vela 1 -> las carteras entran en pausa al procesar la vela 1."""
    s = Servicio(tmp_path)
    s.hasta(T0 + H4 + H4 // 2)
    s.manda("/pause")
    s.hasta(T0 + H4 + H4 // 2 + 120_000)
    carteras = {n: cartera(tmp_path, n, [(T0 + H4, "CLOSE_ONLY_MANUAL", True)]) for n in ("paper", "paper-ai")}
    return s, carteras


def test_todo_en_orden(escenario):
    s, carteras = escenario
    checks, servicio = check_control.juzgar(s.r.conn, carteras, H4)
    assert fallos(checks) == {}
    assert servicio > H4
    assert all(c.comprobados for c in checks)


def test_un_hueco_del_servicio_se_ve(tmp_path):
    s = Servicio(tmp_path)
    s.hasta(T0 + 60_000)
    s.reloj.ms += 20 * 60_000
    s.hasta(s.reloj.ms + 60_000)
    assert "el servicio no se ha parado (una vuelta cada <= 10 min)" in fallos(check_control.juzgar(s.r.conn, {}, H4)[0])


def test_una_respuesta_que_no_salio_se_ve(tmp_path):
    s = Servicio(tmp_path, enviar=lambda *a: (0, "Telegram caido"))
    s.manda("/pause")
    s.hasta(T0 + 60_000)
    assert "cada comando de Telegram recibio su respuesta" in fallos(check_control.juzgar(s.r.conn, {}, H4)[0])


def test_un_kill_levantado_desde_telegram_se_ve(tmp_path):
    s = Servicio(tmp_path)
    s.manda("/kill")
    s.hasta(T0 + 60_000)
    with s.r.conn:
        s.r.conn.execute("INSERT INTO control_comandos (update_id, ts_ms, recibido_ms, orden, texto, origen)"
                         " VALUES (99, ?, ?, 'levantar_kill', 'x', 'telegram')", (T0 + 60_000, T0 + 60_000))
    f = fallos(check_control.juzgar(s.r.conn, {}, H4)[0])
    assert "comandos a tiempo, y el /kill solo se levanta en el VPS o el panel con motivo" in f
    assert "la pausa solo cae con /si a tiempo; la parada, solo desde el VPS o el panel" in f


def test_un_comando_ejecutado_tarde_se_ve(tmp_path):
    s = Servicio(tmp_path)
    s.hasta(T0 + 60_000)
    with s.r.conn:
        s.r.conn.execute("INSERT INTO control_comandos (update_id, ts_ms, recibido_ms, orden, texto, origen)"
                         " VALUES (99, ?, ?, 'pause', '/pause', 'telegram')", (T0, T0 + 3600_000))
    assert "comandos a tiempo, y el /kill solo se levanta en el VPS o el panel con motivo" in \
        fallos(check_control.juzgar(s.r.conn, {}, H4)[0])


def test_si_la_funcion_quitara_la_pausa_con_un_si_tardio_el_juez_lo_ve(tmp_path, monkeypatch):
    """El juez no se fia de `reconstruir`: con una version rota (sin ventana de 60 s) suspende."""
    s = Servicio(tmp_path)
    s.manda("/pause")
    s.hasta(T0 + 60_000)
    s.manda("/resume")
    s.hasta(T0 + 180_000)
    s.manda("/si")                                   # 2 min despues del /resume: no vale
    s.hasta(T0 + 240_000)
    assert fallos(check_control.juzgar(s.r.conn, {}, H4)[0]) == {}
    monkeypatch.setattr(cmds, "CONFIRMAR_MS", 10**12)
    assert "la pausa solo cae con /si a tiempo; la parada, solo desde el VPS o el panel" in \
        fallos(check_control.juzgar(s.r.conn, {}, H4)[0])


def test_una_cartera_que_no_aplico_la_pausa_se_ve(escenario, tmp_path):
    s, carteras = escenario
    carteras["paper-ai"] = cartera(tmp_path, "sin-pausa", [])
    [texto] = fallos(check_control.juzgar(s.r.conn, carteras, H4)[0])[
        "cada cartera tuvo la pausa y la parada que tocaban en cada vela"][:1]
    assert "paper-ai" in texto and "CLOSE_ONLY_MANUAL" in texto


def test_una_cartera_que_la_aplico_una_vela_antes_se_ve(escenario, tmp_path):
    s, carteras = escenario
    carteras["paper"] = cartera(tmp_path, "antes", [(T0, "CLOSE_ONLY_MANUAL", True)])
    assert "cada cartera tuvo la pausa y la parada que tocaban en cada vela" in \
        fallos(check_control.juzgar(s.r.conn, carteras, H4)[0])


def test_sin_base_de_control_sale_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["check_control.py", "--control-db", str(tmp_path / "no.db")])
    assert check_control.main() == 2
