"""El juez de noticias (`scripts/check_news.py`): cada comprobacion, sana y rota a proposito.

La base de noticias la escribe el SERVICIO de verdad (`run_news.NewsRunner`) con la red falsa;
luego se rompe una cosa cada vez y la comprobacion que la vigila tiene que ponerse en rojo.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core import paradas
from core.config import load_settings
from data.news import store as db
from data.news.okx import Lectura
from features.news import Anuncio
from portfolio import store as papel

RAIZ = Path(__file__).resolve().parents[2]


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


check_news = _cargar("check_news")
run_news = _cargar("run_news")

T0 = int(datetime(2026, 10, 1, 12, tzinfo=UTC).timestamp() * 1000)
MIN = 60_000
TF = 4 * 3600_000
WL = load_settings().whitelist
URL = "https://my.okx.com/en-eu/help/okx-to-delist-near"


class Red:
    def __init__(self):
        self.anuncios, self.errores = [], []

    def __call__(self, ya_vistos=frozenset()):
        return Lectura([a for a in self.anuncios if a.id not in ya_vistos], list(self.errores))


class NadaQueMandar:
    def __call__(self, conn, token, chat, ahora):
        return 0, None


class SinLatido:
    def enviar(self):
        pass


@pytest.fixture
def base(tmp_path):
    """Una hora de servicio sano, con un deslistado de NEAR a los 30 min."""
    red = Red()
    r = run_news.NewsRunner(tmp_path / "news.db", _leer=red, _enviar=NadaQueMandar(), _latido=SinLatido())
    for m in range(0, 65, 5):
        if m == 30:
            red.anuncios = [Anuncio(URL, T0 + 29 * MIN, "OKX to delist NEAR")]
        r.pasada(T0 + m * MIN)
    yield r.conn
    r.conn.close()


def cartera(tmp_path, filas):
    c = papel.connect(tmp_path / "paper.db")
    papel.migrate(c)
    for ts, sym in filas:
        papel.record_decisions(c, ts, [(f"d-{sym}-{ts}", sym, "pullback_trend", "candidate", "...")])
    return c


def fallos(news, carteras=None):
    checks, _ = check_news.juzgar(news, carteras or {}, WL, TF)
    return {c.nombre: c.fallos for c in checks if not c.ok}


def test_un_servicio_sano_no_tiene_fallos(base):
    assert fallos(base) == {}


def test_un_hueco_de_mas_de_15_min_se_detecta(base):
    with base:
        base.execute("DELETE FROM news_lecturas WHERE ms BETWEEN ? AND ?", (T0 + 10 * MIN, T0 + 25 * MIN))
    assert any("sin lecturas" in f for f in fallos(base)["el servicio no se ha parado (lecturas cada <= 15 min)"])


def _quitar_lecturas(base, desde_min, hasta_min):
    with base:
        base.execute("DELETE FROM news_lecturas WHERE ms BETWEEN ? AND ?",
                     (T0 + desde_min * MIN, T0 + hasta_min * MIN))


def test_un_hueco_dentro_de_una_parada_conocida_se_justifica_y_se_ve(base, monkeypatch):
    _quitar_lecturas(base, 10, 25)
    monkeypatch.setattr(paradas, "PARADAS_CONOCIDAS",
                        (paradas.Parada(T0, T0 + 40 * MIN, "reinicio de prueba"),))
    checks, _ = check_news.juzgar(base, {}, WL, TF)
    hueco = next(c for c in checks if c.nombre.startswith("el servicio no se ha parado"))
    assert hueco.ok
    assert len(hueco.justificados) == 1 and "reinicio de prueba" in hueco.justificados[0]


def test_un_hueco_mayor_que_la_parada_conocida_sigue_siendo_fallo(base, monkeypatch):
    _quitar_lecturas(base, 10, 25)
    monkeypatch.setattr(paradas, "PARADAS_CONOCIDAS",
                        (paradas.Parada(T0, T0 + 20 * MIN, "reinicio de prueba"),))
    checks, _ = check_news.juzgar(base, {}, WL, TF)
    hueco = next(c for c in checks if c.nombre.startswith("el servicio no se ha parado"))
    assert not hueco.ok and not hueco.justificados


def test_una_flag_activa_sin_aviso_se_detecta(base):
    with base:
        base.execute("DELETE FROM paper_avisos WHERE clave LIKE 'noticia:%'")
    assert "cada flag que llego a estar activa se aviso" in fallos(base)


def test_una_caida_de_mas_de_una_hora_sin_aviso_se_detecta(base):
    with base:
        for m in range(70, 140, 5):
            db.registrar_lectura(base, T0 + m * MIN, False, 0, 0, ["sin red"])
    assert "si la fuente cayo mas de 1 h, se aviso" in fallos(base)


def test_la_caida_avisada_por_el_servicio_de_verdad_pasa(tmp_path):
    red = Red()
    r = run_news.NewsRunner(tmp_path / "n.db", _leer=red, _enviar=NadaQueMandar(), _latido=SinLatido())
    r.pasada(T0)
    red.errores = ["sin red"] * 4
    for m in range(5, 125, 5):
        r.pasada(T0 + m * MIN)
    assert fallos(r.conn) == {}
    r.conn.close()


def test_una_levantada_que_no_es_de_ninguna_flag_se_detecta(base):
    with base:
        base.execute("INSERT INTO news_levantadas VALUES ('inventada:NEAR:delisting', ?, 'x')", (T0,))
    assert "cada flag levantada a mano existe" in fallos(base)


def test_un_candidato_de_una_moneda_con_flag_se_detecta(base, tmp_path):
    # La vela de las 12:00 decide a las 16:00, con el deslistado (12:29) ya activo.
    c = cartera(tmp_path, [(T0, "NEAR/USDC"), (T0, "BTC/USDC")])
    f = fallos(base, {"baseline": c})["ninguna cartera genero candidatos de una moneda con flag"]
    assert len(f) == 1 and "NEAR/USDC" in f[0]
    c.close()


def test_un_candidato_de_antes_del_aviso_es_legitimo(base, tmp_path):
    c = cartera(tmp_path, [(T0 - 2 * TF, "NEAR/USDC")])    # decidida a las 08:00, antes de las 12:29
    assert fallos(base, {"baseline": c}) == {}
    c.close()


def test_el_criterio_pide_siete_dias(base, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_news.py", "--news-db", str(tmp_path / "news.db"),
                                      "--paper-db", str(tmp_path / "no-existe.db")])
    assert check_news.main() == 2
    assert "Aun no" in capsys.readouterr().out
