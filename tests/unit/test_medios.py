"""Los medios en sombra (docs/diseno-medios-sombra.md): leer RSS sin fiarse, guardar sin duplicar, nunca lanzar."""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from data.medios import rss
from data.medios import store as db
from features.news import Tipo, flags

REPO = Path(__file__).resolve().parents[2]

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Medio</title>
<item><title><![CDATA[Solana network <b>halts</b> trading after exploit &amp; outage]]></title>
<link>https://medio.example/a</link><guid>a-1</guid><pubDate>Tue, 06 Oct 2026 21:00:44 +0000</pubDate></item>
<item><title>Bitcoin price prediction: 200% rally?</title><link>https://medio.example/b</link>
<dc:date>2026-10-06T20:00:00Z</dc:date></item>
<item><title>Sin fecha</title><link>https://medio.example/c</link></item>
<item><title></title><link>https://medio.example/vacio</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Otro</title>
<entry><title>Hackers drain $40M from Avalanche bridge</title><link href="https://otro.example/x"/>
<id>tag:otro,2026:x</id><published>2026-10-06T10:00:00+02:00</published></entry>
</feed>"""

BOMBA = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
<rss><channel><item><title>&lol2;</title><guid>x</guid></item></channel></rss>"""


def test_rss_y_atom_salen_como_texto_plano_con_su_fecha():
    titulares, error = rss.interpretar(RSS, "medio")
    assert error is None
    assert [t.titulo for t in titulares] == [
        "Solana network halts trading after exploit & outage", "Bitcoin price prediction: 200% rally?", "Sin fecha"]
    assert titulares[0].guid == "a-1" and titulares[0].publicado_ms == 1_791_320_444_000
    assert titulares[1].guid == "https://medio.example/b", "sin guid, el enlace"
    assert titulares[1].publicado_ms == 1_791_316_800_000, "dc:date ISO"
    assert titulares[2].publicado_ms is None
    atom, error = rss.interpretar(ATOM, "otro")
    assert error is None and atom[0].guid == "tag:otro,2026:x" and atom[0].enlace == "https://otro.example/x"
    assert atom[0].publicado_ms == 1_791_273_600_000, "con su zona horaria"


def test_un_documento_con_entidades_se_rechaza_sin_parsearlo():
    titulares, error = rss.interpretar(BOMBA, "malo")
    assert titulares == [] and "DOCTYPE" in error


@pytest.mark.parametrize("cuerpo, trozo", [
    (b"<rss><channel><item>", "mal formado"),
    (b"<rss><channel></channel></rss>", "ningun titular"),
    (b"x" * (rss.MAX_BYTES + 1), "maximo"),
], ids=["mal-formado", "vacio", "demasiado-grande"])
def test_lo_que_no_sirve_es_un_error_no_una_excepcion(cuerpo, trozo):
    titulares, error = rss.interpretar(cuerpo, "f")
    assert titulares == [] and trozo in error


def test_el_titulo_se_recorta():
    largo = b"<rss><channel><item><title>" + b"a" * 1000 + b"</title><guid>g</guid></item></channel></rss>"
    assert len(rss.interpretar(largo, "f")[0][0].titulo) == rss.MAX_TITULO


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_una_fuente_caida_no_para_las_demas():
    fuentes = (rss.Fuente("bien", "https://bien.example/rss", "A"), rss.Fuente("mal", "https://mal.example/rss", "B"))

    def abrir(peticion, timeout):
        if "mal" in peticion.full_url:
            raise TimeoutError("lento")
        assert peticion.get_header("User-agent") == rss.USER_AGENT
        return _Resp(RSS)

    lecturas = rss.leer(fuentes, _abrir=abrir)
    assert lecturas[0].error is None and len(lecturas[0].titulares) == 3
    assert lecturas[1].titulares == [] and "TimeoutError" in lecturas[1].error


def test_las_24_fuentes_tienen_nombre_unico_y_calidad():
    nombres = [f.nombre for f in rss.FUENTES]
    assert len(nombres) == 24 == len(set(nombres))
    assert {f.calidad for f in rss.FUENTES} == {"A", "B"}
    assert all(f.url.startswith("https://") for f in rss.FUENTES)


# --- La base ---


def test_guardar_no_duplica_y_una_fecha_futura_se_queda_en_la_de_visto(tmp_path):
    conn = db.conectar(tmp_path / "m.db")
    db.migrar(conn)
    titulares, _ = rss.interpretar(RSS, "medio")
    visto = 1_791_320_000_000                      # antes del pubDate del primero: "futuro"
    assert db.guardar(conn, titulares, "A", visto) == 3
    assert db.guardar(conn, titulares, "A", visto + 1) == 0
    fechas = {r["titulo"][:5]: r["publicado_ms"] for r in conn.execute("SELECT * FROM medios_titulares")}
    assert fechas["Solan"] == visto and fechas["Sin f"] is None
    anuncios = {a.titulo[:5]: a.publicado_ms for a in db.anuncios(conn)}
    assert anuncios["Sin f"] == visto, "sin fecha del medio, la de cuando se vio"


def test_las_flags_en_sombra_salen_del_clasificador_de_okx_y_el_deslistado_caduca(tmp_path):
    conn = db.conectar(tmp_path / "m.db")
    db.migrar(conn)
    db.guardar(conn, rss.interpretar(RSS, "medio")[0], "A", 1_791_400_000_000)
    db.guardar(conn, [rss.Titular("o", "d", "Exchange to delist Dogecoin", "", 1_791_400_000_000)], "B",
               1_791_400_000_000)
    fs = {(f.moneda, f.tipo): f for f in flags(db.anuncios(conn), ("BTC", "SOL", "DOGE"),
                                                duraciones_h=db.DURACIONES_SOMBRA_H)}
    assert (("SOL", Tipo.DELISTING) not in fs) and ("SOL", Tipo.TRADING_SUSPENSION) in fs
    assert ("BTC", Tipo.TRADING_SUSPENSION) not in fs, "una prediccion de precio no es nada"
    assert fs[("DOGE", Tipo.DELISTING)].hasta_ms == 1_791_400_000_000 + 72 * 3_600_000


# --- El servicio ---


class _Latido:
    def __init__(self):
        self.veces = 0

    def enviar(self):
        self.veces += 1


def _runner(tmp_path, lecturas):
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_medios", REPO / "scripts" / "run_medios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fuentes = tuple(rss.Fuente(n, f"https://{n}.example", "A") for n in ("a", "b", "c"))
    latido = _Latido()
    return mod.MediosRunner(tmp_path / "m.db", fuentes=fuentes, _leer=lambda _f: lecturas, _latido=latido), latido


def test_la_pasada_guarda_registra_y_late_si_la_mitad_va_bien(tmp_path):
    t = rss.interpretar(RSS, "a")[0]
    r, latido = _runner(tmp_path, [rss.LecturaFuente("a", t), rss.LecturaFuente("b", rss.interpretar(RSS, "b")[0][:1]),
                                   rss.LecturaFuente("c", error="c: caida")])
    info = r.pasada(1_791_400_000_000)
    assert info == {"ok": True, "fuentes_bien": 2, "fuentes": 3, "nuevos": 4}
    assert latido.veces == 1
    assert r.conn.execute("SELECT COUNT(*) FROM medios_lecturas WHERE ok = 0").fetchone()[0] == 1
    assert "flags EN SOMBRA activas" in r.estado(1_791_400_000_000, ["SOL/USDC", "BTC/USDC"])


def test_sin_la_mitad_no_late_y_nunca_lanza(tmp_path):
    r, latido = _runner(tmp_path, [rss.LecturaFuente(n, error=f"{n}: caida") for n in ("a", "b", "c")])
    assert r.pasada(1)["ok"] is False and latido.veces == 0
    r._leer = lambda _f: 1 / 0
    assert r.pasada(2)["ok"] is False


# --- Que nadie que decide lo use (docs/diseno-medios-sombra.md 1) ---


PERMITIDOS = {"data/medios/rss.py", "data/medios/store.py", "data/medios/__init__.py", "scripts/run_medios.py",
              # 10/10 (el propietario): el panel ensenya si el servicio lee; nada de lo que decide (y el test de abajo).
              "scripts/run_panel.py",
              # 11/10 (el propietario): el embudo de noticias para L, en sombra; no decide nada de la fase 6.
              "scripts/embudo_noticias.py"}


def test_ningun_modulo_que_decide_importa_los_medios_ni_abre_su_base():
    culpables = []
    for ruta in sorted(REPO.rglob("*.py")):
        rel = ruta.relative_to(REPO).as_posix()
        if rel.startswith((".venv/", "tests/", "docs/", "var/")) or rel in PERMITIDOS:
            continue
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        if "ploutos-medios.db" in texto:
            culpables.append(f"{rel}: abre ploutos-medios.db")
        for nodo in ast.walk(ast.parse(texto)):
            if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.module.startswith("data.medios"):
                culpables.append(f"{rel}: from {nodo.module}")
            elif isinstance(nodo, ast.Import) and any(a.name.startswith("data.medios") for a in nodo.names):
                culpables.append(f"{rel}: import data.medios")
    assert culpables == [], culpables


def test_el_panel_solo_mira_si_los_medios_leen_nunca_los_titulares():
    """El panel abre la base de los medios (10/10) SOLO para la ultima lectura buena: ni titulares ni su modulo."""
    for rel in ("api/foto.py", "api/app.py", "api/historial.py", "scripts/run_panel.py", "ui/panel.js"):
        texto = (REPO / rel).read_text(encoding="utf-8")
        assert "medios_titulares" not in texto, rel
        assert "data.medios" not in texto, rel


def test_un_titulo_con_etiquetas_dentro_se_lee_entero():
    """Revision del 15/10: `findtext` cortaba el titulo en la primera etiqueta hija."""
    rss_doc = (b"<rss><channel><item><title>Solana <b>exploit</b> drains 5M</title><guid>g1</guid>"
               b"</item></channel></rss>")
    (t,), err = rss.interpretar(rss_doc, "x")
    assert err is None and t.titulo == "Solana exploit drains 5M"
    atom_doc = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>XRP <i>delisted</i> by X</title>'
                b"<id>a1</id></entry></feed>")
    (t,), err = rss.interpretar(atom_doc, "y")
    assert err is None and t.titulo == "XRP delisted by X"
