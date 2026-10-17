"""El cierre del panel por nombre (hueco S5, DNS rebinding) y sus cabeceras de seguridad (api/guardia.py).

Una web de fuera puede apuntar su propio dominio a la IP de Tailscale del panel: el navegador la trata como "mismo
origen" y podria leer el panel o pulsar sus botones. La cabecera Host, en cambio, lleva SU dominio: el panel solo
contesta si el Host es el suyo. Sin httpx: se llama al ASGI a pelo.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from api.guardia import Guardia, politica

HOSTS = frozenset({"100.70.1.2:8765", "ploutos.ejemplo.ts.net:8765", "ploutos:8765"})
UI = Path(__file__).resolve().parents[2] / "ui"


def _scope(tipo: str, host: str | None, ruta: str = "/") -> dict:
    cabeceras = [] if host is None else [(b"host", host.encode())]
    return {"type": tipo, "path": ruta, "headers": cabeceras, "method": "GET"}


def _llamar(guardia, scope):
    """Devuelve (lo que se envio, si la app de dentro llego a ejecutarse)."""
    enviados, dentro = [], []

    async def app(scope, receive, send):
        dentro.append(scope["path"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/html")]})
            await send({"type": "http.response.body", "body": b"ok"})
        else:
            await send({"type": "websocket.accept"})

    async def receive():
        return {"type": "websocket.connect"} if scope["type"] == "websocket" else {"type": "http.request", "body": b""}

    async def send(m):
        enviados.append(m)

    asyncio.run(Guardia(app, hosts=guardia)(scope, receive, send))
    return enviados, dentro


def _cabeceras(enviados) -> dict[str, str]:
    inicio = next(m for m in enviados if m["type"] == "http.response.start")
    return {k.decode().lower(): v.decode() for k, v in inicio["headers"]}


def test_con_su_nombre_o_su_ip_contesta():
    for host in HOSTS:
        enviados, dentro = _llamar(HOSTS, _scope("http", host))
        assert dentro == ["/"] and enviados[0]["status"] == 200, host
    # El Host no distingue mayusculas.
    assert _llamar(HOSTS, _scope("http", "PLOUTOS.Ejemplo.ts.net:8765"))[1] == ["/"]


def test_con_otro_nombre_no_llega_ni_a_la_pagina():
    for host in ["malo.example:8765", "100.70.1.2", "ploutos.ejemplo.ts.net", "100.70.1.2:8765.malo.example", None]:
        enviados, dentro = _llamar(HOSTS, _scope("http", host, "/api/comandos"))
        assert dentro == [], host
        assert enviados[0]["status"] == 421, host


def test_el_websocket_tambien_se_cierra():
    """El WebSocket lleva la foto entera: una web de fuera tampoco puede leerla."""
    enviados, dentro = _llamar(HOSTS, _scope("websocket", "malo.example:8765", "/ws"))
    assert dentro == [] and enviados == [{"type": "websocket.close", "code": 1008}]
    enviados, dentro = _llamar(HOSTS, _scope("websocket", "ploutos:8765", "/ws"))
    assert dentro == ["/ws"] and enviados == [{"type": "websocket.accept"}]


def test_las_respuestas_llevan_las_cabeceras_de_seguridad():
    c = _cabeceras(_llamar(HOSTS, _scope("http", "ploutos:8765"))[0])
    assert c["x-content-type-options"] == "nosniff"
    assert c["referrer-policy"] == "no-referrer"
    assert c["x-frame-options"] == "DENY"
    assert c["content-security-policy"] == politica(HOSTS)


def test_la_politica_solo_deja_lo_propio():
    p = dict(d.strip().split(" ", 1) for d in politica(HOSTS).split(";"))
    assert p["default-src"] == "'self'" and p["script-src"] == "'self'"      # sin scripts en linea ni de fuera
    assert p["frame-ancestors"] == "'none'" and p["object-src"] == "'none'" and p["base-uri"] == "'none'"
    assert p["form-action"] == "'none'"
    # El WebSocket, a su propio nombre (Safari antiguo no cuenta ws:// dentro de 'self').
    assert set(p["connect-src"].split()) == {"'self'"} | {f"ws://{h}" for h in HOSTS}
    assert "http" not in politica(HOSTS).replace("ws://", "")


def test_la_pagina_no_tiene_scripts_en_linea():
    """script-src 'self': un <script> sin src no se ejecutaria."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts and all("src=" in s for s in scripts), scripts
    assert not re.search(r"\son[a-z]+=", html), "manejadores en linea (onclick=...)"


def test_sin_hosts_solo_para_probar_en_local():
    """hosts=None: sin cierre por nombre (solo los tests); las cabeceras van igual."""
    enviados, dentro = _llamar(None, _scope("http", "cualquiera:1"))
    assert dentro == ["/"] and "content-security-policy" in _cabeceras(enviados)


def test_el_panel_lleva_la_guardia_puesta():
    from api.app import crear_app
    from core.config import load_settings
    rutas = {k: Path("no-esta.db") for k in ("principal", "baseline", "ai", "noticias", "control")}
    app = crear_app(load_settings(), rutas, hosts=HOSTS)
    guardias = [m for m in app.user_middleware if m.cls is Guardia]
    assert len(guardias) == 1 and guardias[0].kwargs == {"hosts": HOSTS}
