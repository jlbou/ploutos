"""El latido del vigilante externo (`notify/latido.py`) y cuando late la ingesta.

Lo que se protege: que nunca lanza ni frena lo que vigila, que la URL (secreta)
no sale en un log, que no pasa del limite de Healthchecks.io, y que la ingesta
solo late con TODOS los datos frescos (una ingesta viva sin datos no es sana).
"""

from __future__ import annotations

import io
import logging
import urllib.error

from core.config import load_settings
from data.ingest.staleness import StalenessMonitor
from notify.latido import Latido

URL = "https://hc-ping.com/0f9a8b7c-0000-4000-8000-123456789abc"


class Red:
    def __init__(self, error=None):
        self.error, self.pedidas = error, []

    def __call__(self, peticion, timeout):
        assert timeout <= 5, "timeout corto: no puede frenar lo que vigila"
        self.pedidas.append(peticion.full_url)
        if self.error:
            raise self.error
        return io.BytesIO(b"OK")


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_sin_url_no_hace_nada():
    red = Red()
    latido = Latido(None, "prueba", _open=red)
    assert latido.enviar() is None and latido.fallo() is None
    assert red.pedidas == []


def test_late_como_mucho_una_vez_por_intervalo():
    """Healthchecks.io limita a 5 por minuto; el periodo configurado es de 5 min."""
    red, reloj = Red(), Reloj()
    latido = Latido(URL, "prueba", intervalo_s=120, _open=red, _reloj=reloj)
    assert latido.enviar() is True
    reloj.t += 60
    assert latido.enviar() is None, "aun no toca"
    reloj.t += 61
    assert latido.enviar() is True
    assert red.pedidas == [URL, URL]


def test_un_fallo_de_red_no_lanza_ni_ensenya_la_url(caplog):
    """La URL es secreta: quien la tenga puede mandar latidos falsos."""
    red = Red(error=urllib.error.URLError(f"timeout conectando a {URL}"))
    latido = Latido(URL, "prueba", _open=red)
    with caplog.at_level(logging.WARNING, logger="ploutos.latido"):
        assert latido.enviar() is False
    assert "no llego" in caplog.text
    assert URL not in caplog.text


def test_un_fallo_no_se_reintenta_en_cada_vuelta():
    red, reloj = Red(error=OSError("red caida")), Reloj()
    latido = Latido(URL, "prueba", intervalo_s=120, _open=red, _reloj=reloj)
    latido.enviar()
    reloj.t += 10
    latido.enviar()
    assert len(red.pedidas) == 1


def test_el_fallo_avisa_ya():
    red = Red()
    Latido(URL, "prueba", _open=red).fallo()
    assert red.pedidas == [URL + "/fail"]


# --------------------------------------------------------------------------
# La ingesta solo late con todo fresco
# --------------------------------------------------------------------------

AHORA = 1_790_035_200_000


def monitor_con(simbolos, ahora=AHORA):
    m = StalenessMonitor(settings=load_settings())
    for s in simbolos:
        m.touch("candles:1m", s, ahora)
    return m


def test_todas_las_velas_de_1m_frescas_late():
    whitelist = load_settings().whitelist
    assert monitor_con(whitelist).todo_fresco(whitelist)


def test_si_falta_una_moneda_no_late():
    whitelist = load_settings().whitelist
    assert not monitor_con(whitelist[:-1]).todo_fresco(whitelist)


def test_si_algo_se_queda_viejo_no_late():
    whitelist = load_settings().whitelist
    m = monitor_con(whitelist)
    m.check(AHORA + 10 * 60 * 1000)          # diez minutos sin nada: todo STALE
    assert not m.todo_fresco(whitelist)


def test_sin_ningun_dato_no_late():
    assert not StalenessMonitor(settings=load_settings()).todo_fresco(load_settings().whitelist)


# --------------------------------------------------------------------------
# Revision del 24/09: la ingesta late solo si ha GUARDADO lo que recibe
# --------------------------------------------------------------------------

import importlib.util  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_ingest.py"
_spec = importlib.util.spec_from_file_location("run_ingest", _SCRIPT)
run_ingest = importlib.util.module_from_spec(_spec)
sys.modules["run_ingest"] = run_ingest
_spec.loader.exec_module(run_ingest)

MINUTO = 60_000


def ingesta(tmp_path):
    return run_ingest.IngestService(load_settings(), db_path=str(tmp_path / "ploutos.db"))


def guardar(servicio, simbolos, ts_ms):
    servicio.db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume,"
        " closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(s, "1m", ts_ms, 1.0, 1.0, 1.0, 1.0, 1.0, 1, "ws", ts_ms) for s in simbolos],
    )


def test_con_todo_guardado_al_dia_late(tmp_path):
    s = ingesta(tmp_path)
    guardar(s, load_settings().whitelist, AHORA - 2 * MINUTO)      # cerro hace 1 min
    assert s._guardado_al_dia(AHORA)


def test_si_no_guarda_no_late_aunque_reciba(tmp_path):
    """Disco lleno: el detector de datos viejos seguiria fresco (se actualiza al
    recibir) pero lo guardado se queda viejo."""
    s = ingesta(tmp_path)
    guardar(s, load_settings().whitelist, AHORA - 10 * MINUTO)
    assert not s._guardado_al_dia(AHORA)


def test_si_una_moneda_no_se_guarda_no_late(tmp_path):
    s = ingesta(tmp_path)
    guardar(s, load_settings().whitelist[:-1], AHORA - 2 * MINUTO)
    assert not s._guardado_al_dia(AHORA)
