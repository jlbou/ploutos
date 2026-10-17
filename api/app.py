"""El servidor del panel (fase 5; docs/diseno-api-panel.md). De momento, SOLO la parte de lectura.

- `GET /api/foto`: el estado entero (`api.foto.foto`).
- `WS /ws`: la MISMA foto, cada vez que cambia (se mira cada 2 s). Foto entera y no deltas (decision
  del propietario del 25/09): cada mensaje es el estado completo, asi que el panel no se puede desincronizar.

Abre las bases en `mode=ro` en CADA peticion y las cierra: no guarda nada en memoria que pueda quedar
viejo, y si una base no esta, esa parte de la foto sale "sin datos". No importa `ai/` ni habla con el
exchange (test de arquitectura). UNICA excepcion (el propietario, 28/09): el CSV fiscal pide a OKX el cambio USDC/EUR,
dato PUBLICO y solo al bajarlo (`api/cambio.py`; otro test comprueba que es lo unico del panel que sale a la red).
Delante de todo, `api/guardia.py` (17/10): solo contesta si el Host es el del panel (DNS rebinding) y pone la CSP. Sirve tambien la pagina (`ui/`) y los controles (`POST /api/comandos`, ver api/mando.py): lo UNICO
que escribe, y solo en la base de control.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from api import cambio, historial, mando
from api.foto import foto
from api.guardia import Guardia
from core.config import Settings
from notify import control

CADA_S = 2.0
UI = Path(__file__).resolve().parent.parent / "ui"


def _ro(ruta: Path) -> sqlite3.Connection | None:
    if not ruta.exists():
        return None
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def conexiones(rutas: Mapping[str, Path]) -> Iterator[dict[str, sqlite3.Connection | None]]:
    """Abre en solo lectura las que existan y las cierra SIEMPRE al salir."""
    with ExitStack() as pila:
        abiertas = {}
        for nombre, ruta in rutas.items():
            conn = _ro(Path(ruta))
            if conn is not None:
                pila.callback(conn.close)
            abiertas[nombre] = conn
        yield abiertas


def huella(f: Mapping[str, Any]) -> str:
    """Lo que cambia de verdad: la foto sin la hora en que se hizo."""
    sin_hora = {k: v for k, v in f.items() if k != "generado_ms"}
    return hashlib.sha256(json.dumps(sin_hora, sort_keys=True, default=str).encode()).hexdigest()


# Las letras del panel (ui/vendor/fonts): Windows no conoce el tipo de .woff2 y lo serviria como binario.
mimetypes.add_type("font/woff2", ".woff2")


class _SinCache(StaticFiles):
    """La pagina, con `Cache-Control: no-cache`: el navegador pregunta siempre si ha cambiado (un 304 si no).
    Sin esto, tras un despliegue el movil seguia ensenyando el panel viejo (visto el 27/09)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        respuesta = await super().get_response(path, scope)
        respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


def crear_app(settings: Settings, rutas: Mapping[str, Path],
              reloj: Callable[[], int] = lambda: int(time.time() * 1000), ui: Path = UI,
              pedir_cambio: cambio.Pedir = cambio.pedir_okx, hosts: Iterable[str] | None = None) -> FastAPI:
    """`rutas`: principal, baseline, ai, noticias, control, (desde la fase 4) ejecutor y (10/10) la carpeta del papel de L. `ui`: la pagina (ficheros estaticos).
    `pedir_cambio`: de donde sale el cambio USDC/EUR del CSV (los tests pasan uno falso: ninguno sale a la red).
    `hosts`: los nombres con los que se entra al panel (api/guardia.py: hueco S5); el servicio siempre los pasa."""
    app = FastAPI(title="Ploutos", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(Guardia, hosts=hosts)

    # El papel de L (10/10) es una carpeta con ficheros, no una base: no se abre con las conexiones.
    bases = {k: v for k, v in rutas.items() if k != "papel_l"}

    def hacer_foto() -> dict[str, Any]:
        with conexiones(bases) as c:
            return foto(settings=settings, ahora_ms=reloj(), principal=c["principal"],
                        carteras={"baseline": c["baseline"], "ai": c["ai"]},
                        noticias=c["noticias"], mando=c["control"], exec_conn=c.get("ejecutor"),
                        papel_l_dir=rutas.get("papel_l"), medios=c.get("medios"))

    app.state.hacer_foto = hacer_foto

    @app.get("/api/foto")
    def get_foto() -> dict[str, Any]:
        return hacer_foto()

    def _cartera(cartera: str) -> Path:
        if cartera not in ("baseline", "ai"):
            raise HTTPException(404, "cartera desconocida")
        return rutas[cartera]

    @app.get("/api/operaciones")
    def get_operaciones(cartera: str = "baseline", limite: int = 200) -> list[dict[str, Any]]:
        with conexiones({"c": _cartera(cartera)}) as c:
            return [] if c["c"] is None else historial.operaciones(c["c"], cartera, min(limite, 1000))

    @app.get("/api/operaciones.csv")
    def get_operaciones_csv(cartera: str = "baseline") -> Response:
        with conexiones({"c": _cartera(cartera)}) as c:
            filas = [] if c["c"] is None else historial.operaciones(c["c"], cartera, 100_000)
        instantes = [ms for f in filas for ms in (f["opened_ts_ms"], f["closed_ts_ms"])]
        tabla = cambio.aperturas(instantes, settings.exchange.hostname, pedir_cambio) if instantes else {}
        cabeceras = {"Content-Disposition": f'attachment; filename="ploutos-{cartera}-operaciones.csv"'}
        faltan = sum(1 for ms in instantes if cambio.cambio(ms, tabla) is None)
        if faltan:
            cabeceras["X-Ploutos-Aviso"] = f"sin cambio USDC/EUR para {faltan} instante(s): columnas en euros vacias"
        return Response(historial.csv_operaciones(filas, tabla), media_type="text/csv; charset=utf-8",
                        headers=cabeceras)

    @app.get("/api/decisiones")
    def get_decisiones(limite: int = 30) -> list[dict[str, Any]]:
        with conexiones({"ai": rutas["ai"]}) as c:
            return [] if c["ai"] is None else historial.decisiones(c["ai"], min(limite, 200))

    @app.get("/api/curva")
    def get_curva() -> dict[str, list[list[float]]]:
        with conexiones({k: rutas[k] for k in ("principal", "baseline", "ai")}) as c:
            return historial.curva({"baseline": c["baseline"], "ai": c["ai"]}, c["principal"],
                                   settings.capital.initial_capital_usd)

    @app.get("/api/velas")
    def get_velas(simbolo: str, desde: int) -> list[list[float]]:
        """Las velas de 4 h de una moneda de la whitelist, para el grafico de una posicion (el propietario, 01/10)."""
        if simbolo not in settings.whitelist:
            raise HTTPException(404, "moneda fuera de la whitelist")
        with conexiones({"principal": rutas["principal"]}) as c:
            return [] if c["principal"] is None else historial.velas_posicion(c["principal"], simbolo, desde)

    @app.post("/api/comandos")
    async def post_comando(request: Request) -> dict[str, Any]:
        """Los controles del panel (api/mando.py): solo desde el propio panel (CSRF)."""
        if not mando.permitido({k.lower(): v for k, v in request.headers.items()}):
            raise HTTPException(403, "solo desde el propio panel")
        try:
            cuerpo = await request.json()
        except ValueError:
            raise HTTPException(400, "hace falta JSON") from None
        if not isinstance(cuerpo, dict):
            raise HTTPException(400, "hace falta un objeto JSON")

        def hacer() -> str:
            conn = control.conectar(rutas["control"])
            try:
                control.migrar(conn)
                return mando.ejecutar(conn, str(cuerpo.get("orden", "")), str(cuerpo.get("motivo", "")), reloj())
            finally:
                conn.close()

        try:
            respuesta = await asyncio.to_thread(hacer)
        except mando.Rechazado as exc:
            raise HTTPException(409, str(exc)) from None
        return {"ok": True, "respuesta": respuesta}

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        anterior = None
        try:
            while True:
                f = await asyncio.to_thread(hacer_foto)
                h = huella(f)
                if h != anterior:
                    await socket.send_json(f)
                    anterior = h
                await asyncio.sleep(CADA_S)
        except WebSocketDisconnect:
            return

    # La pagina, lo ultimo: las rutas de arriba tienen preferencia.
    app.mount("/", _SinCache(directory=ui, html=True), name="ui")
    return app
