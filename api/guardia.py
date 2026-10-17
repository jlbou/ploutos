"""La guardia del panel: solo contesta a su propio nombre (hueco S5, DNS rebinding) y pone las cabeceras de seguridad.

**El hueco.** Una web de fuera puede hacer que SU dominio resuelva a la IP de Tailscale del panel (DNS rebinding):
para el navegador es "el mismo origen" y podria leer la foto o pulsar los botones (ni la cabecera `X-Ploutos-Panel`
ni el `Origin` lo paran: el origen es el suyo). Lo que no puede cambiar es la cabecera `Host`, que lleva su dominio.
Por eso, ANTES de cualquier ruta (la pagina, la API, los controles y el WebSocket): si el `Host` no es uno de los
del panel (su IP y sus nombres de Tailscale, con el puerto), 421 y nada mas. Como en Ebisu.

**Las cabeceras.** CSP solo propia (sin scripts en linea ni de fuera; el WebSocket, solo al propio panel), sin
marcos, sin adivinar tipos y sin Referer. Los estilos en linea se permiten: la pagina y la libreria de graficos los usan.

ASGI a pelo (sin dependencias): asi se prueba sin cliente HTTP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

Mensaje = MutableMapping[str, Any]
ASGI = Callable[[Mensaje, Callable[[], Awaitable[Mensaje]], Callable[[Mensaje], Awaitable[None]]], Awaitable[None]]


def politica(hosts: Iterable[str] | None) -> str:
    """La Content-Security-Policy. `connect-src` nombra el WebSocket de cada host (Safari antiguo no lo
    cuenta dentro de 'self')."""
    ws = " ".join(f"ws://{h}" for h in sorted(hosts or ()))
    return "; ".join([
        "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data:",
        "font-src 'self'", f"connect-src 'self'{' ' + ws if ws else ''}", "manifest-src 'self'", "object-src 'none'",
        "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'",
    ])


class Guardia:
    """`hosts`: los valores de `Host` que se aceptan, en minusculas y con puerto. None = sin cierre por nombre
    (solo los tests que no lo miran); las cabeceras de seguridad van siempre."""

    def __init__(self, app: ASGI, hosts: Iterable[str] | None) -> None:
        self.app = app
        self.hosts = None if hosts is None else frozenset(h.lower() for h in hosts)
        self.cabeceras = [(k.encode(), v.encode()) for k, v in {
            "Content-Security-Policy": politica(self.hosts),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        }.items()]

    def _host_valido(self, scope: Mensaje) -> bool:
        if self.hosts is None:
            return True
        host = next((v for k, v in scope.get("headers", []) if k.lower() == b"host"), b"")
        return host.decode("latin-1").lower() in self.hosts

    async def __call__(self, scope: Mensaje, receive, send) -> None:
        tipo = scope["type"]
        if tipo not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not self._host_valido(scope):
            if tipo == "http":
                await send({"type": "http.response.start", "status": 421,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *self.cabeceras]})
                await send({"type": "http.response.body", "body": b"host no permitido"})
            else:
                await receive()                                   # el websocket.connect
                await send({"type": "websocket.close", "code": 1008})
            return
        if tipo == "websocket":
            await self.app(scope, receive, send)
            return

        async def con_cabeceras(m: Mensaje) -> None:
            if m["type"] == "http.response.start":
                m = {**m, "headers": [*m.get("headers", []), *self.cabeceras]}
            await send(m)

        await self.app(scope, receive, con_cabeceras)
