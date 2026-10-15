"""El lector de anuncios de OKX (`data/news/okx.py`), sin red.

`tests/fixtures/okx_respuesta_anuncios.json` es una respuesta REAL de la API (25/09/2026):
si OKX cambia el formato, este test lo dice antes que el servicio.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import URLError

from core.config import load_settings
from data.news.okx import TIPOS, USER_AGENT, interpretar, leer
from features.news import bases_de, flags

REAL = (Path(__file__).resolve().parents[1] / "fixtures" / "okx_respuesta_anuncios.json").read_bytes()
BASES = bases_de(load_settings().whitelist)


class Abrir:
    """Hace de urlopen: devuelve lo que se le diga por tipo y apunta las peticiones."""

    def __init__(self, respuestas):
        self.respuestas, self.peticiones = respuestas, []

    def __call__(self, peticion, timeout):
        self.peticiones.append((peticion, timeout))
        tipo = peticion.full_url.split("annType=")[1].split("&")[0]
        r = self.respuestas.get(tipo, b'{"code":"0","msg":"","data":[{"details":[],"totalPage":"0"}]}')
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(r)


def test_la_respuesta_real_se_entiende():
    anuncios, error = interpretar(REAL, "announcements-delistings")
    assert error is None and len(anuncios) == 20
    a = anuncios[0]
    assert a.id.startswith("https://") and a.titulo and a.publicado_ms > 1_700_000_000_000


def test_con_la_respuesta_real_ninguna_de_nuestras_monedas_se_bloquea():
    anuncios, _ = interpretar(REAL, "announcements-delistings")
    assert flags(anuncios, BASES) == []


def test_un_error_de_okx_no_lanza_y_se_dice():
    anuncios, error = interpretar(b'{"code":"51000","msg":"Parameter annType error","data":[]}', "x")
    assert anuncios == [] and "51000" in error
    assert interpretar(b"<html>403</html>", "x")[1].endswith("no es JSON")


def test_un_anuncio_mal_formado_no_tumba_los_demas():
    d = json.loads(REAL)
    d["data"][0]["details"][0]["pTime"] = "ayer"
    anuncios, error = interpretar(json.dumps(d), "announcements-delistings")
    assert error is None and len(anuncios) == 19


def test_pide_los_cuatro_tipos_con_user_agent_y_timeout():
    abrir = Abrir({"announcements-delistings": REAL})
    r = leer(_abrir=abrir)
    assert [p.full_url.split("annType=")[1].split("&")[0] for p, _ in abrir.peticiones] == list(TIPOS)
    assert all(p.get_header("User-agent") == USER_AGENT and t == 10.0 for p, t in abrir.peticiones)
    assert all("eea.okx.com" in p.full_url for p, _ in abrir.peticiones)
    assert len(r.anuncios) == 20 and r.errores == []
    assert "announcements-new-listings" not in TIPOS, "un listado nunca abre nada (PRD 6)"


def test_no_devuelve_los_ya_vistos_ni_duplicados_y_van_por_orden():
    abrir = Abrir({"announcements-delistings": REAL, "announcements-others": REAL})
    todos = leer(_abrir=abrir).anuncios
    assert len(todos) == 20, "el mismo anuncio en dos tipos cuenta una vez"
    assert [a.publicado_ms for a in todos] == sorted(a.publicado_ms for a in todos)
    vistos = frozenset(a.id for a in todos[:15])
    assert len(leer(ya_vistos=vistos, _abrir=Abrir({"announcements-delistings": REAL})).anuncios) == 5


def test_si_la_red_cae_no_lanza_avisa_y_sigue_con_los_demas_tipos():
    abrir = Abrir({"announcements-delistings": URLError("sin red"),
                   "announcements-others": TimeoutError("lento"),
                   "announcements-trading-updates": REAL})
    r = leer(_abrir=abrir)
    assert len(r.anuncios) == 20 and len(r.errores) == 2 and not r.fuente_caida


def test_si_caen_todos_es_fuente_caida_no_sin_noticias():
    r = leer(_abrir=Abrir({t: URLError("sin red") for t in TIPOS}))
    assert r.anuncios == [] and r.fuente_caida
