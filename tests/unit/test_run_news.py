"""El servicio de noticias (`scripts/run_news.py`) con su base de verdad y la red falsa."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data.news import store as db
from data.news.okx import Lectura
from features.news import Anuncio

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_news.py"
_spec = importlib.util.spec_from_file_location("run_news", SCRIPT)
run_news = importlib.util.module_from_spec(_spec)
sys.modules["run_news"] = run_news
_spec.loader.exec_module(run_news)

T0 = int(datetime(2026, 10, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
HORA = 3600_000
URL = "https://my.okx.com/en-eu/help/okx-to-delist-near"


class Leer:
    def __init__(self):
        self.anuncios, self.errores, self.lanza = [], [], None

    def __call__(self, ya_vistos=frozenset()):
        if self.lanza:
            raise self.lanza
        return Lectura([a for a in self.anuncios if a.id not in ya_vistos], list(self.errores))


class Enviar:
    def __init__(self):
        self.textos = []

    def __call__(self, conn, token, chat, ahora_ms):
        filas = conn.execute("SELECT id, texto FROM paper_avisos WHERE enviado_ms IS NULL").fetchall()
        for f in filas:
            self.textos.append(f["texto"])
            conn.execute("UPDATE paper_avisos SET enviado_ms = ? WHERE id = ?", (ahora_ms, f["id"]))
        conn.commit()
        return len(filas), None


class Latido:
    def __init__(self):
        self.veces = 0

    def enviar(self):
        self.veces += 1


@pytest.fixture
def servicio(tmp_path):
    leer, enviar, latido = Leer(), Enviar(), Latido()
    r = run_news.NewsRunner(tmp_path / "news.db", _leer=leer, _enviar=enviar, _latido=latido)
    yield r, leer, enviar, latido
    r.conn.close()


def test_una_pasada_normal_guarda_late_y_no_avisa_de_lo_que_no_nos_toca(servicio):
    r, leer, enviar, latido = servicio
    leer.anuncios = [Anuncio("u1", T0 - HORA, "OKX to delist DORA, ICX spot trading pairs")]
    info = r.pasada(T0)
    assert info["ok"] and info["nuevos"] == 1 and latido.veces == 1
    assert enviar.textos == []
    assert db.ultima_lectura_buena(r.conn) == T0


def test_un_deslistado_nuestro_avisa_una_sola_vez(servicio):
    r, leer, enviar, _ = servicio
    leer.anuncios = [Anuncio(URL, T0 - HORA, "OKX to delist NEAR")]
    r.pasada(T0)
    r.pasada(T0 + 5 * 60_000)
    assert len(enviar.textos) == 1
    assert "NEAR/USDC" in enviar.textos[0] and "No caduca sola" in enviar.textos[0]
    assert URL in enviar.textos[0], "con el enlace al anuncio de OKX"


def test_levantada_por_el_propietario_ya_no_esta(servicio):
    r, leer, enviar, _ = servicio
    leer.anuncios = [Anuncio(URL, T0 - HORA, "OKX to delist NEAR")]
    r.pasada(T0)
    [f] = r.flags()
    db.levantar(r.conn, f.clave, "falsa alarma", T0 + HORA)
    assert r.flags() == []
    with pytest.raises(ValueError):
        db.levantar(r.conn, f.clave, "  ", T0)


def test_un_aviso_ya_caducado_no_se_manda(servicio):
    r, leer, enviar, _ = servicio
    leer.anuncios = [Anuncio("v", T0 - 48 * HORA, "Announcement on the Price Volatility of Dogecoin (DOGE)")]
    r.pasada(T0)
    assert enviar.textos == []


def test_las_flags_se_derivan_de_lo_guardado_y_sobreviven_a_un_reinicio(servicio, tmp_path):
    r, leer, _, _ = servicio
    leer.anuncios = [Anuncio(URL, T0 - HORA, "OKX to delist NEAR")]
    r.pasada(T0)
    otro = run_news.NewsRunner(tmp_path / "news.db", _leer=Leer(), _enviar=Enviar(), _latido=Latido())
    assert [f.moneda for f in otro.flags()] == ["NEAR"]
    otro.conn.close()


def test_si_la_fuente_cae_no_late_y_avisa_tras_una_hora_una_vez(servicio):
    r, leer, enviar, latido = servicio
    r.pasada(T0)                                   # una buena
    leer.errores = ["x: URLError"] * 4             # y despues nada
    for minutos in (5, 30, 59):
        r.pasada(T0 + minutos * 60_000)
    assert enviar.textos == [] and latido.veces == 1
    r.pasada(T0 + 61 * 60_000)
    r.pasada(T0 + 90 * 60_000)
    avisos = [t for t in enviar.textos if "Sin anuncios de OKX" in t]
    assert len(avisos) == 1 and "No se bloquea nada" in avisos[0]


def test_un_fallo_dentro_no_tumba_el_servicio(servicio):
    r, leer, _, latido = servicio
    leer.lanza = RuntimeError("se rompio algo")
    info = r.pasada(T0)
    assert info["ok"] is False and "RuntimeError" in info["errores"][0] and latido.veces == 0


def test_el_recordatorio_de_pendientes_sale_una_vez_al_dia_desde_las_0010(servicio):
    r, leer, enviar, _ = servicio
    leer.anuncios = [Anuncio(URL, T0 - HORA, "OKX to delist NEAR")]
    r.pasada(T0)                                              # el aviso del deslistado
    manyana = int(datetime(2026, 10, 2, 0, 5, tzinfo=UTC).timestamp() * 1000)
    r.pasada(manyana)
    assert not any("Pendiente de decidir" in t for t in enviar.textos), "antes de las 00:10, no"
    r.pasada(manyana + 10 * 60_000)
    r.pasada(manyana + 20 * 60_000)
    assert sum("Pendiente de decidir" in t for t in enviar.textos) == 1


def test_el_estado_ensenya_la_clave_para_levantarla(servicio):
    r, leer, _, _ = servicio
    leer.anuncios = [Anuncio(URL, T0 - HORA, "OKX to delist NEAR")]
    r.pasada(T0)
    texto = r.estado(T0)
    assert "flags activas: 1" in texto and "no caduca" in texto and r.flags()[0].clave in texto
