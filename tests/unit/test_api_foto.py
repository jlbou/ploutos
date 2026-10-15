"""La foto del panel (api/foto.py) y su servidor (api/app.py), con bases de verdad.

Sin red: el servidor no se levanta; se prueba la funcion que hace la foto y el detector de cambios
del WebSocket.
"""

from __future__ import annotations

import json
from datetime import date

from api.app import crear_app, huella
from api.foto import H4, MIN, RETIRADOS, estado_del_papel, foto
from core.config import load_settings
from data.news import store as noticias_db
from data.store.db import open_database
from features.news import Anuncio
from notify import control
from notify.comandos import Comando, Orden
from portfolio import store

SETTINGS = load_settings()
T0 = 1_790_092_800_000          # 22/09/2026 16:00 UTC (apertura de una vela de 4 h)
AHORA = T0 + 2 * H4 + 30 * MIN  # la vela de T0+H4 ya cerro y hubo tiempo de procesarla


def base_papel(tmp_path, nombre, *, equity=50.42, vela=T0 + H4):
    c = store.connect(tmp_path / f"{nombre}.db")
    store.migrate(c)
    with c:
        c.execute("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                  (vela, equity, 1, 1))
        c.execute("INSERT INTO paper_positions (symbol, decision_id, qty, entry_price, stop_price, target_price,"
                  " setup, opened_ts_ms, entry_fee_usd, worst_price, best_price) VALUES"
                  " ('ETH/USDC','d-eth',0.1,100,95,115,'pullback_trend',?,0.01,99,101)", (T0,))
        c.execute("INSERT INTO paper_orders (decision_id, symbol, qty, limit_price, stop_price, target_price,"
                  " setup, created_ts_ms, state) VALUES ('d-sol','SOL/USDC',0.3,50,48,56,'pullback_trend',?,"
                  "'pending')", (T0 + H4,))
    return c


def base_principal(tmp_path, precio=102.0, ultima_1m=AHORA - 2 * MIN):
    db = open_database(tmp_path / "main.db")
    db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume, closed, source,"
        " ingested_ms) VALUES (?,?,?,?,?,?,?,?,1,'ws',?)",
        [("ETH/USDC", "1m", ultima_1m, precio, precio, precio, precio, 1.0, ultima_1m)])
    db.close()
    import sqlite3
    return sqlite3.connect(tmp_path / "main.db")


def test_sin_ninguna_base_todo_sin_datos_y_sin_romperse():
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"baseline": None, "ai": None},
             noticias=None, mando=None)
    assert f["carteras"] == {"baseline": {"disponible": False}, "ai": {"disponible": False}}
    assert {s["estado"] for k, s in f["servicios"].items() if k not in RETIRADOS} == {"sin_datos"}
    # 15/10: las dos carteras de la fase 6 y el demo, retiradas: "Retirado", nunca "Caido".
    assert {f["servicios"][k]["estado"] for k in RETIRADOS & f["servicios"].keys()} <= {"retirado"}
    assert {"papel_baseline", "papel_ai"} <= f["servicios"].keys()
    assert f["manual"]["disponible"] is False and f["noticias"]["disponible"] is False
    assert (f["slider"]["nivel"], f["slider"]["bloqueado"]) == (3, True)
    assert [n["nivel"] for n in f["slider"]["niveles"]] == [1, 2, 3, 4, 5]
    assert f["slider"]["niveles"][2]["max_operaciones"] == 6


def test_la_cartera_con_sus_posiciones_valoradas(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path),
             carteras={"baseline": base_papel(tmp_path, "base")}, noticias=None, mando=None)
    c = f["carteras"]["baseline"]
    assert c["equity_usd"] == 50.42 and round(c["distancia_suelo_usd"], 2) == 25.42
    [p] = c["posiciones"]
    assert p["precio"] == 102.0 and p["pnl_usd"] == 0.2 and p["pnl_r"] == 0.4    # 0,2 $ sobre 0,5 $ de riesgo
    assert [o["decision_id"] for o in c["pendientes"]] == ["d-sol"]
    assert c["modo"] == "NORMAL" and c["estado"] == "ok"
    assert f["servicios"]["ingesta"]["estado"] == "ok"


def test_sin_precio_la_posicion_sale_sin_pnl_no_con_cero(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None,
             carteras={"ai": base_papel(tmp_path, "ai")}, noticias=None, mando=None)
    [p] = f["carteras"]["ai"]["posiciones"]
    assert p["precio"] is None and p["pnl_usd"] is None and p["pnl_r"] is None


def test_la_ingesta_parada_se_ve(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path, ultima_1m=AHORA - 30 * MIN),
             carteras={}, noticias=None, mando=None)
    assert f["servicios"]["ingesta"]["estado"] == "caido"


def test_estado_del_papel():
    ultima_cerrada = (AHORA - 10 * MIN) // H4 * H4 - H4
    assert estado_del_papel(ultima_cerrada, AHORA) == "ok"
    assert estado_del_papel(ultima_cerrada - H4, AHORA) == "tarde"
    assert estado_del_papel(ultima_cerrada - 2 * H4, AHORA) == "caido"
    assert estado_del_papel(None, AHORA) == "sin_datos"
    # Justo al cerrar una vela, el papel tiene 10 min para procesarla sin salir "tarde".
    cierre = 3 * H4 + 1_790_000_000_000 // H4 * H4
    assert estado_del_papel(cierre - 2 * H4, cierre + 5 * MIN) == "ok"


def test_pausa_parada_y_noticias(tmp_path):
    mando = control.conectar(tmp_path / "control.db")
    control.migrar(mando)
    control.guardar_comando(mando, Comando(1, AHORA - MIN, Orden.PAUSE, "/pause"),
                            recibido_ms=AHORA - MIN, origen="telegram", respuesta="ok")
    news = noticias_db.conectar(tmp_path / "news.db")
    noticias_db.migrar(news)
    noticias_db.guardar(news, [Anuncio("u", AHORA - H4, "OKX to delist NEAR")], AHORA)
    noticias_db.registrar_lectura(news, AHORA - MIN, True, 1, 1, [])
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={}, noticias=news, mando=mando)
    assert f["manual"]["pausa_ms"] == AHORA - MIN and f["manual"]["parada_ms"] is None
    assert f["noticias"]["flags"] == {"NEAR/USDC": ["delisting (critica)"]}
    assert f["servicios"]["noticias"]["estado"] == "ok"
    assert f["servicios"]["telegram"]["estado"] == "sin_datos"


def test_el_token_de_la_ia():
    s = SETTINGS.model_copy(update={"claude": SETTINGS.claude.model_copy(
        update={"token_expires_on": date(2026, 10, 1)})})
    f = foto(settings=s, ahora_ms=AHORA, principal=None, carteras={}, noticias=None, mando=None,
             hoy=date(2026, 9, 22))
    assert f["token_ia"] == {"caduca": "2026-10-01", "dias": 9}


def test_la_foto_no_nombra_a_claude(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path),
             carteras={"baseline": base_papel(tmp_path, "b"), "ai": base_papel(tmp_path, "a")},
             noticias=None, mando=None)
    assert "claude" not in json.dumps(f, default=str).lower()


def test_la_huella_solo_cambia_si_cambia_algo():
    a = {"generado_ms": 1, "x": [1, 2]}
    assert huella(a) == huella({"generado_ms": 2, "x": [1, 2]})
    assert huella(a) != huella({"generado_ms": 1, "x": [1, 3]})


def test_el_servidor_hace_la_foto_con_las_bases_que_haya(tmp_path):
    base_papel(tmp_path, "base").close()
    rutas = {"principal": tmp_path / "no-esta.db", "baseline": tmp_path / "base.db",
             "ai": tmp_path / "tampoco.db", "noticias": tmp_path / "n.db", "control": tmp_path / "c.db"}
    app = crear_app(SETTINGS, rutas, reloj=lambda: AHORA)
    f = app.state.hacer_foto()
    assert f["carteras"]["baseline"]["disponible"] and not f["carteras"]["ai"]["disponible"]
    assert {r.path for r in app.routes} >= {"/api/foto", "/ws"}
    assert not (tmp_path / "no-esta.db").exists()          # solo lectura: no crea bases


# --- la pagina (ui/) ------------------------------------------------------------------------------

from pathlib import Path  # noqa: E402
import re  # noqa: E402

UI = Path(__file__).resolve().parents[2] / "ui"


def test_la_pagina_no_depende_de_internet_ni_nombra_a_claude():
    """Decision del propietario del 25/09: sin fuentes ni scripts de fuera; y el panel dice "IA"."""
    for nombre in ("index.html", "panel.js"):
        texto = (UI / nombre).read_text(encoding="utf-8")
        assert not re.search(r"https?://", texto), f"{nombre} carga algo de fuera"
        assert "claude" not in texto.lower(), nombre


def test_la_pagina_nunca_mete_datos_como_html():
    """Lo que viene de las bases (titulos de noticias, motivos) no se interpreta como HTML."""
    js = (UI / "panel.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js


def test_el_servidor_sirve_la_pagina():
    app = crear_app(SETTINGS, {k: Path("no-esta.db") for k in ("principal", "baseline", "ai", "noticias", "control")})
    assert any(getattr(r, "name", "") == "ui" for r in app.routes)
    assert (UI / "index.html").exists() and (UI / "panel.js").exists() and (UI / "favicon.svg").exists()
    # La icona de la pantalla de inicio del movil (el propietario, 26/09): iOS no usa el SVG.
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="apple-touch-icon.png"' in html and (UI / "apple-touch-icon.png").exists()
    assert 'rel="manifest"' in html and (UI / "manifest.webmanifest").exists()


def test_donde_se_quedo_cada_moneda(tmp_path):
    c = base_papel(tmp_path, "b")                    # ETH con posicion, SOL con entrada pendiente
    vela = T0 + H4
    with c:
        c.executemany("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail) VALUES (?,?,?,?,?,?)", [
            (vela, None, "BTC/USDC", None, "filtered", "hueco libre: 3/3 huecos ocupados"),
            (vela, "d-x", "XRP/USDC", "pullback_trend", "candidate", "..."),
            (vela, "d-x", "XRP/USDC", "pullback_trend", "vetoed", "regla 15: correlacion"),
            (vela, "d-n", "NEAR/USDC", "pullback_trend", "candidate", "..."),
            (vela, "d-e", "ETH/USDC", "pullback_trend", "candidate", "..."),
        ])
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"baseline": c}, noticias=None, mando=None)
    m = f["carteras"]["baseline"]["por_moneda"]
    assert m["vela_ms"] == vela
    e = {s: v["estado"] for s, v in m["monedas"].items()}
    assert e["ETH/USDC"] == "posicion" and e["SOL/USDC"] == "pendiente"
    assert e["BTC/USDC"] == "descartada" and "3/3" in m["monedas"]["BTC/USDC"]["detalle"]
    assert e["XRP/USDC"] == "vetada" and "regla 15" in m["monedas"]["XRP/USDC"]["detalle"]
    assert e["NEAR/USDC"] == "no_abierta" and e["DOGE/USDC"] == "sin_senyal"
    assert set(m["monedas"]) == set(SETTINGS.whitelist)


def test_la_libreria_de_graficos_es_la_verificada():
    """Lightweight Charts 5.2.1, bajada con permiso del propietario (26/09): si cambia, que se note."""
    import base64
    import hashlib
    datos = (UI / "vendor" / "lightweight-charts.standalone.production.js").read_bytes()
    assert base64.b64encode(hashlib.sha256(datos).digest()).decode() == "4hzFyqAibvML2FScULnvkmYV8qTua05IY1NHelX1mM8="
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'src="vendor/lightweight-charts.standalone.production.js"' in html


def test_la_equity_de_ahora_es_la_formula_del_papel_con_el_precio_del_minuto(tmp_path):
    """el propietario, 26/09: una estimacion en directo, con la misma formula que PaperLedger.equity_usd."""
    from portfolio.paper import PaperBroker, PaperLedger, PaperPosition
    from tests.risk_fixtures import INSTRUMENTS
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path, precio=102.0),
             carteras={"baseline": base_papel(tmp_path, "b")}, noticias=None, mando=None)
    c = f["carteras"]["baseline"]
    # La misma cuenta con el simulador: una posicion de 0,1 ETH a 100, comision de entrada 0,01, precio 102.
    import dataclasses
    # Con la comision de settings.yaml, la que usa el bucle (no la de ccxt que trae el fixture).
    ins = {"ETH/USDC": dataclasses.replace(INSTRUMENTS["ETH/USDC"], taker_fee=SETTINGS.exchange.fees.taker_pct / 100)}
    broker = PaperBroker(ins)
    broker.positions["ETH/USDC"] = PaperPosition(decision_id="d-eth", symbol="ETH/USDC", qty=0.1, entry_price=100,
                                                 stop_price=95, target_price=115, setup="pullback_trend",
                                                 opened_ts_ms=T0, entry_fee_usd=0.01)
    esperada = PaperLedger(starting_usd=SETTINGS.capital.initial_capital_usd, broker=broker).equity_usd({"ETH/USDC": 102.0})
    assert abs(c["equity_ahora_usd"] - esperada) < 1e-9
    assert c["equity_ahora_ms"] == AHORA - 2 * MIN


def test_sin_precio_no_se_estima(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"ai": base_papel(tmp_path, "a")},
             noticias=None, mando=None)
    assert f["carteras"]["ai"]["equity_ahora_usd"] is None


def _pedir(app, ruta):
    """Un GET a la aplicacion ASGI, sin servidor ni httpx (no esta instalado): devuelve (estado, cabeceras)."""
    import asyncio
    mensajes = []

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def mandar(m):
        mensajes.append(m)

    alcance = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
               "path": ruta, "raw_path": ruta.encode(), "root_path": "", "query_string": b"", "headers": [],
               "server": ("localhost", 8765), "client": ("127.0.0.1", 1)}
    asyncio.run(app(alcance, recibir, mandar))
    inicio = next(m for m in mensajes if m["type"] == "http.response.start")
    return inicio["status"], {k.decode(): v.decode() for k, v in inicio["headers"]}


def test_la_pagina_se_sirve_sin_cache_y_las_letras_con_su_tipo():
    """27/09: tras un despliegue el navegador seguia con el panel viejo. Con no-cache pregunta siempre."""
    app = crear_app(SETTINGS, {k: Path("no-esta.db") for k in ("principal", "baseline", "ai", "noticias", "control")})
    for ruta in ("/", "/panel.js"):
        estado, cab = _pedir(app, ruta)
        assert estado == 200 and cab["cache-control"] == "no-cache", ruta
    estado, cab = _pedir(app, "/vendor/fonts/ibm-plex-mono-latin-400-normal.woff2")
    assert estado == 200 and cab["content-type"] == "font/woff2"


LETRAS = {
    "barlow-semi-condensed-latin-600-normal.woff2": "V62jRdxnewthTZ8553X+3eLS7EnylmBlTLulKxtaIiA=",
    "barlow-semi-condensed-latin-700-normal.woff2": "KrcdErJOWt4CgAcddJ/ewWhMJW05eiWPeBdvLU9bUk8=",
    "ibm-plex-mono-latin-400-normal.woff2": "PFpFH57CejVLDCvMpjbG7BemUSgaq/KfhCfiEKHTHoU=",
    "ibm-plex-mono-latin-500-normal.woff2": "dWAm/3Lrdv2XGsS3UEzsVe72IQnSaEwsrY2jIXC4Czc=",
    "ibm-plex-sans-latin-400-normal.woff2": "O2RpkdMAVak6TsxJlxPUNHlTp0qUfsq0NatyBwy9qw4=",
    "ibm-plex-sans-latin-500-normal.woff2": "Bxczb7Mfzc3kuN6zZ1u0oPf21ISGSvzWdRrCmXWWIgM=",
    "ibm-plex-sans-latin-600-normal.woff2": "iWCFHWkcBU7TjiWb3PGmGQ0Ve0ID7VuzLGMqhj+47C8=",
}


def test_las_letras_son_las_bajadas_y_la_pagina_las_usa():
    """Barlow e IBM Plex, bajadas con permiso del propietario (27/09): si cambian, que se note; y ninguna sobra."""
    import base64
    import hashlib
    carpeta = UI / "vendor" / "fonts"
    assert sorted(p.name for p in carpeta.glob("*.woff2")) == sorted(LETRAS)
    html = (UI / "index.html").read_text(encoding="utf-8")
    for nombre, esperada in LETRAS.items():
        assert base64.b64encode(hashlib.sha256((carpeta / nombre).read_bytes()).digest()).decode() == esperada, nombre
        assert f"url(vendor/fonts/{nombre})" in html, nombre


def test_la_pagina_no_usa_el_script_viejo_guardado_en_el_navegador():
    """27/09: el navegador del propietario mezclo la pagina nueva con el panel.js viejo (guardado antes del no-cache) y el
    panel no cargaba. La direccion del script lleva version, para que ninguna copia vieja valga."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script src="panel\.js\?v=\d+"></script>', html)
    assert '<script src="panel.js"></script>' not in html


def test_el_flujo_de_la_ultima_vela(tmp_path):
    """PRD 10, vista de sistema: cuantas monedas llegan a cada paso en la ULTIMA vela, y la llamada a la IA."""
    from api.foto import flujo
    c = base_papel(tmp_path, "ai")                    # ETH con posicion, SOL con entrada pendiente
    vieja, vela = T0, T0 + H4
    wl = tuple(SETTINGS.whitelist)
    with c:
        c.executemany("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail) VALUES (?,?,?,?,?,?)", [
            (vieja, "d-v", "BTC/USDC", "pullback_trend", "candidate", ""),          # de otra vela: no cuenta
            (vela, None, "ETH/USDC", None, "filtered", "hueco libre"),
            (vela, None, "DOGE/USDC", None, "filtered", "spread"),
            (vela, None, "ADA/USDC", None, "filtered", "fuera de la whitelist"),     # no es de las 8: no cuenta
            (vela, "d-sol", "SOL/USDC", "pullback_trend", "candidate", ""),
            (vela, "d-xrp", "XRP/USDC", "pullback_trend", "candidate", ""),
            (vela, "d-sol", "SOL/USDC", "pullback_trend", "submitted", ""),
            (vela, "d-xrp", "XRP/USDC", "pullback_trend", "vetoed", "regla 15"),
        ])
        c.execute("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates, latency_s)"
                  " VALUES (?,?,?,?,?,?,?,?)", (vela, vela + H4 + 30_000, "decision", "ok", 1, "1 open", 2, 14.2))
    x = flujo(c, vela, wl, posiciones=1, pendientes=1, max_posiciones=3)
    assert (x["pasan"], x["descartadas"], x["candidatos"], x["enviadas"], x["vetadas"]) == (6, 2, 2, 1, 1)
    assert x["llamada_ia"] == {"resultado": "ok", "candidatos": 2, "latencia_s": 14.2}
    assert (x["posiciones"], x["pendientes"], x["max_posiciones"]) == (1, 1, 3)
    assert flujo(c, None, wl, 0, 0, 3) == {"vela_ms": None}


def test_el_flujo_del_baseline_no_tiene_llamada(tmp_path):
    from api.foto import flujo
    c = base_papel(tmp_path, "b")
    c.execute("DROP TABLE ai_calls")                  # como una base sin las tablas de la IA
    assert flujo(c, T0, tuple(SETTINGS.whitelist), 0, 0, 3)["llamada_ia"] is None


def test_la_foto_lleva_el_flujo_de_cada_cartera(tmp_path):
    rutas = {"principal": tmp_path / "no.db", "baseline": tmp_path / "base.db", "ai": tmp_path / "no.db",
             "noticias": tmp_path / "n.db", "control": tmp_path / "c.db"}
    base_papel(tmp_path, "base").close()
    f = crear_app(SETTINGS, rutas, reloj=lambda: AHORA).state.hacer_foto()
    assert "flujo" in f["carteras"]["baseline"]
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'id="p-flujo"' in html and 'id="flujo"' in html


def test_el_panel_tiene_cuatro_paginas_y_los_avisos_en_todas():
    """el propietario, 29/09: Resumen, IA, Operaciones y Sistema, cada una con su direccion; la pausa y la parada, fuera de ellas."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    paginas = {"resumen": ("p-curva", "p-posiciones", "p-controles"), "ia": ("p-ia", "p-flujo", "p-monedas"),
               "operaciones": ("p-operaciones",), "sistema": ("p-sistema", "p-noticias", "p-agresividad", "p-fase8")}
    trozos = re.split(r'<section class="pagina[^"]*" id="pag-', html)
    assert len(trozos) == 5 and "p-bandas" in trozos[0]          # los avisos, antes de cualquier pagina
    for trozo in trozos[1:]:
        nombre = trozo.split('"', 1)[0]
        assert f'href="#{nombre}" data-pag="{nombre}"' in html
        for seccion in paginas.pop(nombre):
            assert f'id="{seccion}"' in trozo, (nombre, seccion)
    assert not paginas
    js = (UI / "panel.js").read_text(encoding="utf-8")
    assert 'const PAGINAS = ["resumen", "ia", "operaciones", "sistema"]' in js


# --- el demo de OKX (fase 4): la base del ejecutor, en solo lectura ----------------------------------------


def base_ejecutor(tmp_path):
    import sqlite3

    from execution import store as exec_store
    from execution.equity import Foto
    c = exec_store.conectar(tmp_path / "exec.db")
    exec_store.migrar(c)
    exec_store.guardar_foto(c, T0, 50.0, Foto(5000.0, {"BTC": 1.0}))
    exec_store.guardar_equity(c, AHORA - 40_000, 50.12, True, 34.9, 15.2)
    exec_store.guardar_posicion(c, "d-20260922T1600-eth-pb", "ETH/USDC", 0.0057, 2640.0, 2554.0, 2861.0, T0, 0.015)
    exec_store.guardar_posicion(c, "d-20260922T1600-sol-pb", "SOL/USDC", 0.12, 117.8, 114.0, 125.0, T0, 0.014)
    exec_store.guardar_pasada(c, AHORA - 60_000, True, [], [], ["d-20260922T1600-sol-pb"])
    exec_store.tratar(c, "d-20260922T1600-near-pb", AHORA - 90_000, "omitida", "NEAR/USDC no se opera en el demo")
    exec_store.guardar_modo(c, AHORA - 100_000, "CLOSE_ONLY_MANUAL", True, "/pause")
    exec_store.guardar_modo(c, AHORA - 90_000, "CLOSE_ONLY_CAPITAL", True, "equity <= suelo")
    c.close()
    return sqlite3.connect(f"file:{tmp_path / 'exec.db'}?mode=ro", uri=True)


def test_el_demo_se_ve_con_la_oco_de_cada_posicion(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={}, noticias=None, mando=None,
             exec_conn=base_ejecutor(tmp_path))
    d = f["demo"]
    assert d["disponible"] and d["equity_usd"] == 50.12 and d["capital_usd"] == 50.0
    assert d["modo"] == "CLOSE_ONLY_CAPITAL", "el mas restrictivo de los activos, no el primero"
    ocos = {p["symbol"]: p["oco"] for p in d["posiciones"]}
    assert ocos == {"ETH/USDC": "viva", "SOL/USDC": "sin_oco"}
    assert d["conciliacion"]["cuadra"] and d["tratadas"][0]["que"] == "omitida"
    assert f["servicios"]["ejecutor"]["estado"] == "retirado"     # 15/10: el demo, retirado


def test_sin_el_ejecutor_el_demo_no_esta_y_no_sale_como_servicio():
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={}, noticias=None, mando=None)
    assert f["demo"] == {"disponible": False} and "ejecutor" not in f["servicios"]


def test_el_panel_lee_la_base_del_ejecutor_sin_crearla(tmp_path):
    rutas = {"principal": tmp_path / "a.db", "baseline": tmp_path / "b.db", "ai": tmp_path / "c.db",
             "noticias": tmp_path / "d.db", "control": tmp_path / "e.db", "ejecutor": tmp_path / "exec.db"}
    assert crear_app(SETTINGS, rutas, reloj=lambda: AHORA).state.hacer_foto()["demo"] == {"disponible": False}
    assert not (tmp_path / "exec.db").exists()
    base_ejecutor(tmp_path).close()
    assert crear_app(SETTINGS, rutas, reloj=lambda: AHORA).state.hacer_foto()["demo"]["disponible"]



def test_las_posiciones_del_demo_llevan_lo_mismo_que_las_de_papel(tmp_path):
    """Para las mismas tarjetas: precio de ahora (de la ingesta, aproximado), PnL en $ y en R, setup."""
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path, precio=2700.0), carteras={},
             noticias=None, mando=None, exec_conn=base_ejecutor(tmp_path))
    eth = next(p for p in f["demo"]["posiciones"] if p["symbol"] == "ETH/USDC")
    assert eth["precio"] == 2700.0 and eth["precio_aprox"] and eth["setup"] == "pullback_trend"
    assert eth["pnl_usd"] == round((2700.0 - 2640.0) * 0.0057, 4)
    assert eth["pnl_r"] == round(eth["pnl_usd"] / ((2640.0 - 2554.0) * 0.0057), 3)
    sol = next(p for p in f["demo"]["posiciones"] if p["symbol"] == "SOL/USDC")
    assert sol["precio"] is None and sol["pnl_usd"] is None, "sin precio, sin PnL (no un cero)"


def test_la_pantalla_de_carga_sale_con_la_pagina_y_se_va_con_la_primera_foto():
    """el propietario, 03/10: en el movil la pagina se quedaba en blanco sin saber si cargaba. La pantalla de carga va en el HTML
    (sale sin esperar al JavaScript) y el panel la quita al recibir la primera foto."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    js = (UI / "panel.js").read_text(encoding="utf-8")
    assert html.index('id="carga"') < html.index('<header'), "lo primero del body"
    assert "Tailscale" in html, "si no conecta, dice donde mirar"
    cuerpo = js[js.index("function recibir"):]
    assert '$("carga")' in cuerpo[:cuerpo.index("\n}")]


# --- El papel de L (10/10): de sus ficheros, solo lectura ---

def _ficheros_l(tmp_path, pasada):
    d = tmp_path / "papel-l"
    d.mkdir()
    (d / "ultimo.json").write_text(json.dumps({
        "metricas": {"final": 51.2, "rendimiento": 0.024, "caida_max": 0.05},
        "btc": {"rendimiento": -0.03, "caida_max": 0.12},
        "ops": [{"simbolo": "SOL/USDC", "entrada_ms": T0, "salida_ms": T0 + H4, "entrada": 100.0, "salida": 95.0,
                 "neto": -0.8, "motivo": "stop"}],
        "abiertas": {"ETH/USDC": {"t": T0, "entrada": 100.0, "qty": 0.15, "coste": 15.03, "stop": 90.0,
                                  "objetivo": 200.0}}}), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"pasada_ms": pasada, "huecos": {}}), encoding="utf-8")
    return d


def test_papel_l_antes_de_empezar_no_esta_y_no_es_un_servicio(tmp_path):
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"baseline": None, "ai": None},
             noticias=None, mando=None, papel_l_dir=tmp_path / "no-existe")
    assert f["papel_l"]["disponible"] is False and f["papel_l"]["inicio"] == "2026-10-12"
    assert "papel_l" not in f["servicios"]


def test_papel_l_con_sus_ficheros(tmp_path):
    d = _ficheros_l(tmp_path, pasada=AHORA - 3600_000)
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=base_principal(tmp_path, precio=102.0),
             carteras={"baseline": None, "ai": None}, noticias=None, mando=None, papel_l_dir=d)
    l = f["papel_l"]
    assert l["disponible"] is True and l["operaciones"] == 1
    assert round(l["rendimiento_pct"], 1) == 2.4 and round(l["btc_caida_max_pct"], 1) == 12.0
    (p,) = l["posiciones"]
    assert p["symbol"] == "ETH/USDC" and p["precio"] == 102.0 and p["pnl_usd"] == round(0.15 * 102 - 15.03, 4)
    assert l["ultimas"][0]["motivo"] == "stop"
    assert f["servicios"]["papel_l"]["estado"] == "ok"
    assert l["caida_velas_pct"] is None, "una pasada de antes del 15/10 no la trae: no se inventa"


def test_papel_l_con_la_caida_vela_a_vela(tmp_path):
    """Revision 6 (15/10): la caida con el cierre de cada vela de 4 h, solo informacion, junto a la diaria."""
    d = _ficheros_l(tmp_path, pasada=AHORA - 3600_000)
    r = json.loads((d / "ultimo.json").read_text(encoding="utf-8"))
    r["metricas"]["caida_max_velas"], r["btc"]["caida_max_velas"] = 0.07, 0.15
    (d / "ultimo.json").write_text(json.dumps(r), encoding="utf-8")
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"baseline": None, "ai": None},
             noticias=None, mando=None, papel_l_dir=d)
    l = f["papel_l"]
    assert round(l["caida_velas_pct"], 1) == 7.0 and round(l["btc_caida_velas_pct"], 1) == 15.0
    assert round(l["caida_max_pct"], 1) == 5.0, "la del criterio no cambia"


def test_papel_l_sin_pasada_en_dos_dias_esta_caido(tmp_path):
    d = _ficheros_l(tmp_path, pasada=AHORA - 51 * 3600_000)
    f = foto(settings=SETTINGS, ahora_ms=AHORA, principal=None, carteras={"baseline": None, "ai": None},
             noticias=None, mando=None, papel_l_dir=d)
    assert f["servicios"]["papel_l"]["estado"] == "caido"


def test_las_fechas_del_papel_l_son_las_del_script():
    import importlib.util
    from pathlib import Path

    from api.foto import PAPEL_L
    ruta = Path(__file__).resolve().parents[2] / "scripts" / "papel_l.py"
    spec = importlib.util.spec_from_file_location("papel_l_fechas", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (PAPEL_L["inicio"], PAPEL_L["fin"]) == (mod.INICIO, mod.FIN)
    assert PAPEL_L["corte_pct"] == 25


def test_los_medios_en_sombra_salen_en_sistema_solo_si_hay_base(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "medios.db")
    c.execute("CREATE TABLE medios_lecturas (ms INTEGER, fuente TEXT, ok INTEGER, titulares INTEGER, nuevos INTEGER,"
              " error TEXT)")
    c.executemany("INSERT INTO medios_lecturas VALUES (?,?,?,0,0,'')",
                  [(AHORA - 5 * MIN, "a", 1), (AHORA - MIN, "b", 0)])
    vacio = dict(principal=None, carteras={"baseline": None, "ai": None}, noticias=None, mando=None)
    assert "medios" not in foto(settings=SETTINGS, ahora_ms=AHORA, **vacio)["servicios"]
    s = foto(settings=SETTINGS, ahora_ms=AHORA, medios=c, **vacio)["servicios"]["medios"]
    assert s == {"ultimo_ms": AHORA - 5 * MIN, "estado": "ok"}         # la ultima BUENA, no la fallida
    assert foto(settings=SETTINGS, ahora_ms=AHORA + 70 * MIN, medios=c, **vacio)["servicios"]["medios"]["estado"] == "caido"
