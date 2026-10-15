"""Los comandos de Telegram (PRD seccion 9). Funciones PURAS: sin red, sin base, sin reloj.

Decididos por el propietario el 25/09/2026 (docs/diseno-comandos-telegram.md):

- `/status`: solo lectura.
- `/pause` (y `/closeonly`, su sinonimo): solo cierre manual, `CLOSE_ONLY_MANUAL`.
- `/kill`: `HALTED`. **No se levanta desde el movil**: solo en el VPS.
- `/resume`: levanta SOLO la pausa, y solo si se confirma con `/si` en 60 s.

Tres piezas:

1. `interpretar`: un mensaje de Telegram -> un `Comando` o un `Ignorado`. Solo vale un chat
   PRIVADO cuyo chat y remitente sean el `chat_id` del `.env`; lo demas no se contesta.
   Un comando con mas de 2 minutos no se ejecuta: un `/resume` que llega tarde no puede
   reanudar nada.
2. `aplicar` / `reconstruir`: el estado manual (pausa, parada, `/resume` esperando su `/si`)
   a partir de la lista de comandos. El servicio y las carteras usan LA MISMA funcion: el
   estado se deriva de lo guardado y sobrevive a reinicios.
3. `texto_estado`: la respuesta a `/status`.

La asimetria es a proposito: lo que hace el bot mas prudente es inmediato; lo que lo hace
menos prudente pide confirmacion; lo grave no se levanta desde el movil.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from core.modes import Mode
from notify.messages import cabecera, esc, usd

EDAD_MAX_MS = 120_000       # un comando con mas de 2 min no se ejecuta
CONFIRMAR_MS = 60_000       # el /si tiene que llegar en 60 s tras el /resume


class Orden(Enum):
    STATUS = "status"
    PAUSE = "pause"
    KILL = "kill"
    RESUME = "resume"
    SI = "si"
    # Solo desde el VPS o el panel, con motivo. `interpretar` nunca la produce.
    LEVANTAR_KILL = "levantar_kill"
    # Solo desde el panel, con doble confirmacion (el propietario, 26/09): vende todo y deja el bot en pausa.
    CERRAR_TODO = "cerrar_todo"


COMANDOS: dict[str, Orden] = {
    "/status": Orden.STATUS,
    "/pause": Orden.PAUSE,
    "/closeonly": Orden.PAUSE,      # el nombre del PRD: hace lo mismo que /pause
    "/kill": Orden.KILL,
    "/resume": Orden.RESUME,
    "/si": Orden.SI,
}

AYUDA = "\n".join([
    cabecera("❔", "Comandos"),
    "",
    "/status · cómo están las dos carteras",
    "/pause · no abrir nada nuevo (las posiciones siguen con su stop y su objetivo)",
    "/kill · parada total; solo se levanta en el VPS",
    "/resume · quitar la pausa (pide confirmación)",
])


@dataclass(frozen=True, slots=True)
class Comando:
    update_id: int
    ts_ms: int          # la hora del mensaje segun Telegram
    orden: Orden
    texto: str          # lo que escribio el propietario (o el motivo, si viene del VPS)


@dataclass(frozen=True, slots=True)
class Ignorado:
    update_id: int
    motivo: str                 # ajeno | no_es_mensaje | no_es_comando | desconocido | tarde
    respuesta: str | None       # None: no se contesta


def _hora(ts_ms: int, segundos: bool = False) -> str:
    formato = "%H:%M:%S UTC" if segundos else "%H:%M UTC"
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime(formato)


# --------------------------------------------------------------------------
# 1. Mensaje de Telegram -> comando
# --------------------------------------------------------------------------


def interpretar(update: Mapping[str, Any], chat_id: int, ahora_ms: int) -> Comando | Ignorado:
    """Un `update` de `getUpdates` -> lo que hay que hacer con el.

    Nunca lanza: un mensaje raro se ignora. A un mensaje ajeno no se le contesta (no
    se le confirma a nadie que el bot existe ni que esta escuchando).
    """
    try:
        return _interpretar(update, chat_id, ahora_ms)
    except (AttributeError, TypeError, ValueError):
        # Telegram manda JSON bien formado; esto es solo para que un update raro no
        # tumbe al que escucha.
        return Ignorado(-1, "no_es_mensaje", None)


def _interpretar(update: Mapping[str, Any], chat_id: int, ahora_ms: int) -> Comando | Ignorado:
    update_id = int(update.get("update_id", -1))
    mensaje = update.get("message")
    if not isinstance(mensaje, Mapping):
        return Ignorado(update_id, "no_es_mensaje", None)
    chat = mensaje.get("chat") or {}
    remitente = mensaje.get("from") or {}
    if not (chat.get("type") == "private" and chat.get("id") == chat_id
            and remitente.get("id") == chat_id):
        return Ignorado(update_id, "ajeno", None)

    texto = mensaje.get("text")
    es_comando = isinstance(texto, str) and texto.startswith("/")
    # "/pause@PloutosBot motivo" -> "/pause"
    palabra = texto.split(maxsplit=1)[0].split("@", 1)[0].lower() if es_comando else ""
    orden = COMANDOS.get(palabra)
    ts_ms = int(mensaje.get("date", 0)) * 1000
    tarde = ahora_ms - ts_ms > EDAD_MAX_MS

    if orden is None:
        # La ayuda solo a lo reciente: al arrancar por primera vez llegan los mensajes de las
        # ultimas 24 h (los de la fase 0, por ejemplo), y contestarlos ahora seria ruido.
        motivo = "desconocido" if es_comando else "no_es_comando"
        return Ignorado(update_id, motivo, None if tarde else AYUDA)
    if tarde:
        return Ignorado(update_id, "tarde", "\n".join([
            cabecera("⌛", f"{esc(palabra)} ha llegado tarde"),
            "",
            f"Enviado a las {_hora(ts_ms)}, recibido a las {_hora(ahora_ms)}: "
            "no se ejecuta. Si sigue haciendo falta, vuelve a enviarlo.",
        ]))
    return Comando(update_id, ts_ms, orden, texto)


# --------------------------------------------------------------------------
# 2. El estado manual, derivado de los comandos
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Estado:
    pausa_ms: int | None = None     # desde cuando hay pausa
    kill_ms: int | None = None      # desde cuando hay parada
    resume_ms: int | None = None    # un /resume esperando su /si

    @property
    def modos(self) -> dict[Mode, str]:
        """Los modos que tienen que estar activos en las DOS carteras, con su motivo."""
        out: dict[Mode, str] = {}
        if self.pausa_ms is not None:
            out[Mode.CLOSE_ONLY_MANUAL] = f"/pause desde Telegram ({_hora(self.pausa_ms)})"
        if self.kill_ms is not None:
            out[Mode.HALTED] = f"/kill desde Telegram ({_hora(self.kill_ms)})"
        return out


def aplicar(estado: Estado, c: Comando) -> tuple[Estado, str | None]:
    """El estado tras un comando y la respuesta. `None` = responder con `texto_estado`."""
    sigue_kill = ("\n\n🛑 La parada (/kill) sigue activa: solo se levanta en el VPS."
                  if estado.kill_ms is not None else "")

    if c.orden is Orden.STATUS:
        return estado, None

    if c.orden is Orden.PAUSE:
        if estado.pausa_ms is not None:
            return replace(estado, resume_ms=None), \
                f"⏸ Ya estaba en pausa desde las {_hora(estado.pausa_ms)}."
        return replace(estado, pausa_ms=c.ts_ms, resume_ms=None), "\n".join([
            cabecera("⏸", "Pausa", "las dos carteras"),
            "",
            "• No se abre nada nuevo y se cancelan las entradas pendientes.",
            "• Las posiciones siguen con su stop y su objetivo.",
            "• Cuenta desde la próxima decisión de cada cartera (al cierre de la vela).",
            "",
            "Para quitarla: /resume",
        ])

    if c.orden is Orden.KILL:
        if estado.kill_ms is not None:
            return replace(estado, resume_ms=None), \
                f"🛑 Ya estaba parado desde las {_hora(estado.kill_ms)}."
        return replace(estado, kill_ms=c.ts_ms, resume_ms=None), "\n".join([
            cabecera("🛑", "Parada (HALTED)", "las dos carteras"),
            "",
            "• No se abre nada y se cancelan las entradas pendientes.",
            "• Las posiciones siguen con su stop y su objetivo en el exchange; el bot no las toca.",
            "• Cuenta desde la próxima decisión de cada cartera (al cierre de la vela).",
            "• <b>Solo se levanta en el VPS</b>, no desde el móvil.",
        ])

    if c.orden is Orden.RESUME:
        if estado.pausa_ms is None:
            texto = ("No hay ninguna pausa que quitar." if estado.kill_ms is None else
                     "No hay ninguna pausa. La parada (/kill) solo se levanta en el VPS.")
            return replace(estado, resume_ms=None), texto
        return replace(estado, resume_ms=c.ts_ms), "\n".join([
            cabecera("❓", "¿Quitar la pausa?"),
            "",
            "Las dos carteras volverán a abrir operaciones.",
            f"Responde /si antes de las {_hora(c.ts_ms + CONFIRMAR_MS, segundos=True)}.",
        ]) + sigue_kill

    if c.orden is Orden.SI:
        pendiente = estado.resume_ms
        if (pendiente is None or estado.pausa_ms is None
                or not 0 <= c.ts_ms - pendiente <= CONFIRMAR_MS):
            return replace(estado, resume_ms=None), \
                "No hay nada que confirmar (un /resume caduca a los 60 s)."
        return replace(estado, pausa_ms=None, resume_ms=None), "\n".join([
            cabecera("▶️", "Pausa quitada", "las dos carteras"),
            "",
            "Vuelven a abrir operaciones desde la próxima vela.",
        ]) + sigue_kill

    if c.orden is Orden.CERRAR_TODO:
        pausa = estado.pausa_ms if estado.pausa_ms is not None else c.ts_ms
        return replace(estado, pausa_ms=pausa, resume_ms=None), "\n".join([
            cabecera("🖐", "Cerrar todo", "las dos carteras, desde el panel"),
            "",
            "• Se venden TODAS las posiciones a mercado al cierre de la vela en curso.",
            "• Se cancelan las entradas pendientes y el bot queda EN PAUSA.",
            "• Para volver a operar: quitar la pausa (/resume o el panel).",
        ]) + sigue_kill

    if c.orden is Orden.LEVANTAR_KILL:
        return replace(estado, kill_ms=None, resume_ms=None), "\n".join([
            cabecera("✅", "Parada levantada en el VPS"),
            "",
            f"<b>Motivo:</b> {esc(c.texto)}",
        ])

    raise ValueError(f"orden sin tratar: {c.orden}")


def cerrar_todo_en(comandos: Iterable[Comando], decision_ms: int, paso_ms: int) -> bool:
    """Si en la decision del CIERRE `decision_ms` toca vender todo: hay un "cerrar todo" enviado
    durante esa vela (despues de la decision anterior y hasta esta). Lo usan el bucle y el juez."""
    return any(c.orden is Orden.CERRAR_TODO and decision_ms - paso_ms < c.ts_ms <= decision_ms
               for c in comandos)


def reconstruir(comandos: Iterable[Comando]) -> Estado:
    """El estado manual actual, reproduciendo los comandos EJECUTADOS en orden."""
    estado = Estado()
    for c in comandos:
        estado, _ = aplicar(estado, c)
    return estado


# --------------------------------------------------------------------------
# 3. La respuesta a /status
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FotoCartera:
    """Lo que ensenya /status de una cartera. Lo rellena el servicio leyendo su base."""

    nombre: str                     # "baseline" | "ai"
    modo: Mode
    equity_usd: float | None        # None: todavia sin ninguna vela
    cambio_hoy_usd: float           # equity ahora menos al empezar el dia UTC
    cerradas_hoy: int
    posiciones: int
    ultima_vela_ms: int | None
    llamadas_ia: int | None = None  # solo la cartera de la IA


NOMBRE_CORTO = {"baseline": "Baseline", "ai": "IA"}


def _modo_corto(m: Mode) -> str:
    return m.name.removeprefix("CLOSE_ONLY_")


def _vela(ts_ms: int | None, ahora_ms: int) -> str:
    if ts_ms is None:
        return "-"
    formato = "%H:%M" if ahora_ms - ts_ms < 86_400_000 else "%d/%m"
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime(formato)


def texto_estado(
    carteras: Sequence[FotoCartera],
    *,
    ahora_ms: int,
    max_posiciones: int,
    max_llamadas: int,
    manual: Estado,
    noticias: Mapping[str, Sequence[str]] | None,
) -> str:
    """Corto, para el movil: una columna por cartera. Sin el detalle de las posiciones
    (eso es del panel). Nunca nombra a Claude: "IA" (decision del propietario del 25/09)."""
    filas: list[tuple[str, list[str]]] = [
        ("", [NOMBRE_CORTO.get(c.nombre, c.nombre) for c in carteras]),
        ("Modo", [_modo_corto(c.modo) for c in carteras]),
        ("Equity", ["-" if c.equity_usd is None else usd(c.equity_usd) for c in carteras]),
        ("Hoy", [usd(c.cambio_hoy_usd, signo=True) for c in carteras]),
        ("Cerradas hoy", [str(c.cerradas_hoy) for c in carteras]),
        ("Posiciones", [f"{c.posiciones}/{max_posiciones}" for c in carteras]),
        ("Llamadas IA", ["-" if c.llamadas_ia is None else f"{c.llamadas_ia}/{max_llamadas}"
                         for c in carteras]),
        ("Última vela", [_vela(c.ultima_vela_ms, ahora_ms) for c in carteras]),
    ]
    ancho_k = max(len(k) for k, _ in filas)
    anchos = [max(len(v[i]) for _, v in filas) for i in range(len(carteras))]
    tabla = "\n".join(
        f"{k:<{ancho_k}}  " + "  ".join(f"{v:>{a}}" for v, a in zip(vs, anchos, strict=True))
        for k, vs in filas
    )

    lineas = [cabecera("📊", "Estado", _hora(ahora_ms)), ""]
    if manual.kill_ms is not None:
        lineas.append(f"🛑 <b>Parada</b> desde las {_hora(manual.kill_ms)} (se levanta en el VPS)")
    if manual.pausa_ms is not None:
        lineas.append(f"⏸ <b>En pausa</b> desde las {_hora(manual.pausa_ms)} · /resume para quitarla")
    if manual.kill_ms is not None or manual.pausa_ms is not None:
        lineas.append("")
    lineas.append(f"<pre>{esc(tabla)}</pre>")
    if noticias is None:
        lineas.append("📰 Noticias: sin datos (el servicio de noticias no responde)")
    elif noticias:
        lineas.append("📰 <b>Avisos de noticias:</b>")
        lineas += [f"• {esc(par)}: {esc(', '.join(tipos))}" for par, tipos in sorted(noticias.items())]
    else:
        lineas.append("📰 Noticias: sin avisos activos")
    return "\n".join(lineas)

