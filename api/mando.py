"""Los controles del panel (fase 5): pausar, quitar la pausa, parar, levantar la parada y cerrar todo.

Decisiones del propietario (25-26/09): sin PIN (Tailscale es la unica barrera); "cerrar todo" con doble
confirmacion y deja el bot EN PAUSA; levantar la parada, desde el VPS o el panel, con motivo. Los
comandos entran en la MISMA tabla que los de Telegram (`control_comandos`, origen `panel`): las
carteras siguen teniendo una sola fuente, y los jueces (`check_paper`, `check_control`) los cubren.

**Que otra pagina no pueda pulsar los botones (CSRF).** Sin PIN, una web cualquiera abierta en el mismo
navegador podria mandar un POST al panel. Dos cierres: la peticion tiene que llevar la cabecera
`X-Ploutos-Panel: 1` (una pagina de otro origen no puede ponerla sin que el navegador pregunte antes al
servidor, y este no lo permite) y, si trae `Origin`, tiene que ser el del propio panel.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from urllib.parse import urlparse

from notify import control
from notify.comandos import Comando, Orden, aplicar, reconstruir

CABECERA = "x-ploutos-panel"


class Rechazado(Exception):
    """El comando no tiene sentido ahora (quitar una pausa que no hay...): no se guarda nada."""


def permitido(cabeceras: Mapping[str, str]) -> bool:
    """Que la peticion sale del propio panel (ver la cabecera del modulo). Cabeceras en minusculas."""
    if cabeceras.get(CABECERA) != "1":
        return False
    origen = cabeceras.get("origin")
    return origen is None or urlparse(origen).netloc == cabeceras.get("host")


def _texto_plano(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html)


def ejecutar(conn: sqlite3.Connection, orden: str, motivo: str, ahora_ms: int) -> str:
    """Aplica un control del panel y lo guarda. Devuelve la respuesta (texto). `Rechazado` si no toca."""
    estado = reconstruir(control.comandos(conn))
    motivo = (motivo or "").strip()
    if orden == "pause":
        cmds = [Orden.PAUSE]
    elif orden == "kill":
        cmds = [Orden.KILL]
    elif orden == "resume":
        if estado.pausa_ms is None:
            raise Rechazado("no hay ninguna pausa que quitar")
        # La confirmacion la ha pedido el panel: se guarda como en Telegram, /resume y su /si.
        cmds = [Orden.RESUME, Orden.SI]
    elif orden == "levantar_kill":
        if estado.kill_ms is None:
            raise Rechazado("no hay ninguna parada que levantar")
        if not motivo:
            raise Rechazado("hace falta un motivo: queda apuntado por que se levanto")
        cmds = [Orden.LEVANTAR_KILL]
    elif orden == "cerrar_todo":
        cmds = [Orden.CERRAR_TODO]
    else:
        raise Rechazado(f"orden desconocida: {orden!r}")

    respuesta = ""
    for i, o in enumerate(cmds):
        c = Comando(-1, ahora_ms, o, motivo or f"panel: {orden}")
        estado, texto = aplicar(estado, c)
        ultimo = i == len(cmds) - 1
        # Solo la ultima respuesta sale por Telegram (la del /resume intermedio no tendria sentido).
        control.guardar_comando(conn, c, recibido_ms=ahora_ms, origen="panel",
                                respuesta=texto if ultimo else None)
        respuesta = texto or ""
    return _texto_plano(respuesta)
