"""Los avisos de Telegram, como texto (PRD seccion 9). Funciones PURAS.

En castellano (decision del propietario del 23/09/2026), con acentos (son para leerlos
en el movil) y con el formato HTML de Telegram: titulo en negrita con un icono
que dice de un vistazo si es bueno, malo o urgente, y los numeros en un bloque
monoespaciado para que queden alineados (pedido por el propietario el 23/09: "todo en el
mismo formato, muy soso").

TODO TEXTO VARIABLE PASA POR `esc()`. En HTML solo `<`, `>` y `&` son
peligrosos, pero un motivo como "perdida >= 3 $" sin escapar hace que Telegram
rechace el mensaje entero (si pasa, `notify.telegram` lo reenvia en texto
plano, pero no hay que llegar ahi).

Lo que pide el PRD seccion 9 y esta aqui:
- cierre de cada operacion: par, resultado en $ y en R, motivo, duracion;
- cambio de modo (y las reglas 7 y 9: "+ Telegram");
- parada del bot;
- error de autenticacion de Claude o de OKX;
- token de Claude a punto de caducar (14 dias antes, PRD seccion 6);
- resumen diario (`notify/resumen.py` saca los numeros de la base de papel).

Lo que NO esta todavia: el watchdog (un servicio aparte que avisa si el bot
cae: si el aviso lo diera el propio bot, un bot caido no avisaria) y los
comandos `/status`, `/pause`, `/closeonly`, `/kill`, que tienen que pasar por
el motor de riesgo (fase 4 en adelante).

Cada aviso dice de que cartera habla: en la fase 3 hay dos carteras de papel.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from core.config import DrawdownTier
from core.modes import Mode, ModeChange
from portfolio.paper import ExitReason, PaperTrade

MOTIVO = {
    ExitReason.STOP: "stop 🛑",
    ExitReason.TARGET: "objetivo 🎯",
    ExitReason.CANCELLED: "cancelada",
    ExitReason.NEWS: "noticia 📰 (venta a mercado)",
    ExitReason.MANUAL: "cierre manual 🖐 (desde el panel)",
}
CARTERA = {"baseline": "📐 Baseline", "ai": "🤖 IA"}
DIAS_AVISO_TOKEN = 14      # PRD seccion 6: avisar 14 dias antes de que caduque


def esc(texto: object) -> str:
    """Escapa texto variable para el HTML de Telegram."""
    return html.escape(str(texto), quote=False)


def cartera_de(nombre: str) -> str:
    return CARTERA.get(nombre, esc(nombre))


def usd(x: float, signo: bool = False) -> str:
    """0,42 $ / +0,42 $, con coma decimal."""
    texto = f"{x:+.2f}" if signo else f"{x:.2f}"
    return texto.replace(".", ",") + " $"


def numero(x: float, decimales: int = 2, signo: bool = False) -> str:
    texto = f"{x:+.{decimales}f}" if signo else f"{x:.{decimales}f}"
    return texto.replace(".", ",")


def precio(x: float) -> str:
    """Seis cifras significativas: sirve igual para BTC (65.000) que para DOGE (0,1)."""
    return f"{x:.6g}".replace(".", ",")


def hora(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%d/%m %H:%M UTC")


def duracion(ms: int) -> str:
    horas = max(0, ms) // 3_600_000
    if horas < 1:
        return "menos de 1 h"
    dias, horas = divmod(horas, 24)
    if dias == 0:
        return f"{horas} h"
    return f"{dias} d {horas} h" if horas else f"{dias} d"


def tabla(filas: Sequence[tuple[str, str]]) -> str:
    """Un bloque monoespaciado con las etiquetas alineadas."""
    ancho = max(len(k) for k, _v in filas)
    return "<pre>" + "\n".join(f"{esc(k):<{ancho}}  {esc(v)}" for k, v in filas) + "</pre>"


def cabecera(icono: str, titulo: str, subtitulo: str | None = None) -> str:
    linea = f"{icono} <b>{titulo}</b>"
    return f"{linea}\n<i>{subtitulo}</i>" if subtitulo else linea


# --------------------------------------------------------------------------
# Operaciones y modos
# --------------------------------------------------------------------------


def abierta(trade: PaperTrade) -> str:
    """Cuanto estuvo abierta. Las marcas son la APERTURA de la vela en que se lleno
    y la de la vela en que se cerro: si es la misma, se lleno y salto dentro de
    esa vela y no se sabe cuanto tardo (decir "menos de 1 h" seria inventarlo;
    caso real, ETH el 23/09)."""
    ms = trade.closed_ts_ms - trade.opened_ts_ms
    if ms <= 0:
        return "dentro de la misma vela"
    return duracion(ms)


def operacion_cerrada(trade: PaperTrade, cartera: str) -> str:
    gana = trade.net_pnl_usd >= 0
    return "\n".join([
        cabecera("🟢" if gana else "🔴", f"Operación cerrada · {esc(trade.symbol)}",
                 f"{cartera_de(cartera)} · {esc(trade.setup)}"),
        "",
        f"<b>{usd(trade.net_pnl_usd, signo=True)}</b>  ({numero(trade.r_multiple, signo=True)} R)"
        f"  · {MOTIVO[trade.reason]}",
        tabla([
            ("Entrada", precio(trade.entry_price)),
            ("Salida", precio(trade.exit_price)),
            ("Duración", abierta(trade)),
            ("Comisiones", usd(trade.fees_usd)),
        ]),
        f"<code>{esc(trade.decision_id)}</code>",
    ])


def cambio_de_modo(cambio: ModeChange, cartera: str, canceladas: int = 0) -> str:
    if not cambio.activated:
        icono = "✅" if cambio.effective_after is Mode.NORMAL else "↩️"
    elif cambio.mode is Mode.CLOSE_ONLY_CAPITAL:
        icono = "🚨"
    else:
        icono = "⚠️"
    verbo = "Entra en" if cambio.activated else "Sale de"
    puntos = []
    if cambio.effective_after is not Mode.NORMAL:
        puntos.append("Sin entradas nuevas; las posiciones siguen con su stop y su objetivo.")
    if cambio.activated and cambio.mode is Mode.CLOSE_ONLY_CAPITAL:
        puntos.append(
            "<b>ENCLAVADO</b> (regla 7): solo sale con reset manual, "
            "<code>run_paper.py --reset-capital \"motivo\"</code>."
        )
    if cambio.activated and cambio.mode is Mode.CLOSE_ONLY_DAILY:
        puntos.append("Hasta las 00:00 UTC (regla 10).")
    if cambio.activated and cambio.mode is Mode.CLOSE_ONLY_QUOTA:
        puntos.append("Sale solo cuando una sonda a la IA responda bien.")
    if cambio.activated and cambio.mode is Mode.CLOSE_ONLY_MANUAL:
        puntos.append("Pausa desde Telegram: se quita con /resume.")
    if cambio.activated and cambio.mode is Mode.HALTED:
        puntos.append("Parada: el bot no toca las posiciones. Solo se levanta en el VPS.")
    if canceladas:
        puntos.append(f"Entradas pendientes canceladas: {canceladas}.")
    lineas = [
        cabecera(icono, f"{verbo} {esc(cambio.mode.name)}", cartera_de(cartera)),
        "",
        f"<b>Motivo:</b> {esc(cambio.reason)}",
        f"<b>Modo efectivo:</b> <code>{esc(cambio.effective_before.name)}</code> → "
        f"<code>{esc(cambio.effective_after.name)}</code>",
    ]
    if puntos:
        lineas += [""] + [f"• {p}" for p in puntos]
    return "\n".join(lineas)


# --------------------------------------------------------------------------
# Regla 9: escalones de drawdown
# --------------------------------------------------------------------------


def _nivel(equity: float, escalones: Sequence[DrawdownTier]) -> int:
    return sum(1 for t in escalones if equity < t.equity_below_usd)


def escalon_cruzado(
    anterior: float | None, actual: float, escalones: Sequence[DrawdownTier]
) -> tuple[DrawdownTier, bool] | None:
    """Si el equity ha cruzado un escalon de la regla 9 entre dos lecturas.

    Devuelve (escalon, bajando) o None. Solo avisa al CRUZAR, no en cada vela
    por debajo: un aviso que se repite cada 4 h deja de leerse. Si cruza varios
    de golpe, da el mas grave (bajando) o el que deja atras (subiendo).
    Sin lectura anterior (arranque), no hay cruce que avisar.
    """
    if anterior is None:
        return None
    orden = sorted(escalones, key=lambda t: t.equity_below_usd, reverse=True)
    antes, ahora = _nivel(anterior, orden), _nivel(actual, orden)
    if ahora > antes:
        return orden[ahora - 1], True
    if ahora < antes:
        return orden[antes - 1], False
    return None


def aviso_escalon(cartera: str, equity: float, escalon: DrawdownTier, bajando: bool) -> str:
    limite = usd(escalon.equity_below_usd)
    if not bajando:
        return "\n".join([
            cabecera("📈", f"Equity por encima de {limite}", f"{cartera_de(cartera)} · regla 9"),
            "",
            f"Equity <b>{usd(equity)}</b>. Se levanta ese escalón.",
        ])
    medidas = [f"riesgo por operación ×{numero(escalon.risk_multiplier, 1)}"]
    if escalon.max_positions is not None:
        medidas.append(f"máximo {escalon.max_positions} posición(es)")
    return "\n".join([
        cabecera("📉", f"Equity por debajo de {limite}", f"{cartera_de(cartera)} · regla 9"),
        "",
        f"Equity <b>{usd(equity)}</b>.",
        f"Desde ahora: {', '.join(medidas)}.",
    ])


def aviso_paridad(cartera: str, bloquea: bool, detalle: str, limite_pct: float) -> str:
    """Regla 17: la paridad de USDC empieza o deja de bloquear las entradas (01/10/2026: estuvo 20 h
    bloqueando sin que nadie lo supiera, porque OKX retiro un par que se usaba para calcularla)."""
    if not bloquea:
        return "\n".join([
            cabecera("✅", "Paridad de USDC recuperada", f"{cartera_de(cartera)} · regla 17"),
            "",
            esc(detalle),
            "Se vuelve a entrar.",
        ])
    return "\n".join([
        cabecera("⚠️", "Regla 17: sin entradas nuevas", f"{cartera_de(cartera)} · paridad de USDC"),
        "",
        esc(detalle),
        f"No se entra mientras la paridad sea desconocida o se desvie mas del {numero(limite_pct, 1)} %.",
        "Las posiciones abiertas siguen con su stop y su objetivo.",
    ])


# --------------------------------------------------------------------------
# Paradas, errores y el token
# --------------------------------------------------------------------------


def bot_parado(servicio: str, motivo: str) -> str:
    return "\n".join([cabecera("⛔", f"{esc(servicio)} parado"), "", esc(motivo)])


def _espera(ms: int) -> str:
    s = max(0, ms) // 1000
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return duracion(ms)


def bot_en_marcha(servicio: str, parado_ms: int, ahora_ms: int) -> str:
    """El que sigue a un "parado" (el propietario, 26/09): que ha vuelto, y cuanto estuvo parado."""
    return "\n".join([
        cabecera("▶️", f"{esc(servicio)} en marcha de nuevo"),
        "",
        f"Parado a las {hora(parado_ms)}, en marcha a las {hora(ahora_ms)} ({_espera(ahora_ms - parado_ms)}).",
    ])


MOTIVO_DEMO = {"sl": "stop 🛑", "tp": "objetivo 🎯", "salida": "venta a mercado (noticia o cerrar todo)",
               "desconocido": "desconocido"}


def cierre_demo(*, simbolo: str, decision_id: str, pnl_usd: float, r: float | None, motivo: str, entrada: float,
                salida: float, duracion_ms: int, estimada: bool) -> str:
    """El cierre de una operacion del DEMO (fase 4), con lo mismo que el de papel (PRD 9: par, $ y R, motivo,
    duracion). `estimada`: el precio de salida no se pudo leer de OKX."""
    gana = pnl_usd >= 0
    r_txt = f"  ({numero(r, signo=True)} R)" if r is not None else ""
    return "\n".join([
        cabecera("🟢" if gana else "🔴", f"Operación cerrada · {esc(simbolo)}", "Demo de OKX"),
        "",
        f"<b>{usd(pnl_usd, signo=True)}</b>{r_txt}  · {esc(MOTIVO_DEMO.get(motivo, motivo))}",
        tabla([
            ("Entrada", precio(entrada)),
            ("Salida", precio(salida) + (" (ESTIMADO)" if estimada else "")),
            ("Duración", duracion(duracion_ms) if duracion_ms > 0 else "–"),
        ]),
        f"<code>{esc(decision_id)}</code>",
    ])


def error_autenticacion(servicio: str, detalle: str) -> str:
    """Claude u OKX rechazan las credenciales. `detalle` tiene que venir YA
    limpio (`ai.quota.classify(secret=...)` o `core.secrets.scrub_url`)."""
    return "\n".join([
        cabecera("🚨", f"Error de autenticación con {esc(servicio)}"),
        "",
        f"<code>{esc(detalle)}</code>",
        "Revisa la credencial en <code>/opt/ploutos/.env</code> (a mano, nunca por el chat).",
    ])


def token_por_caducar(caduca: date, hoy: date, dias_aviso: int = DIAS_AVISO_TOKEN) -> str | None:
    """El aviso del token de la IA, o None si todavia no toca.

    En lo que ve el propietario no se nombra a Claude (decision del 25/09): se dice "la IA". La unica
    excepcion es la orden literal para renovarlo, que se llama asi.
    """
    dias = (caduca - hoy).days
    if dias > dias_aviso:
        return None
    cuando = caduca.strftime("%d/%m/%Y")
    paso = "Genera otro con <code>claude setup-token</code> y ponlo en <code>.env</code>."
    if dias < 0:
        return "\n".join([
            cabecera("🚨", f"El acceso de la IA CADUCÓ el {cuando}"),
            "", "La IA no puede decidir.", paso,
        ])
    return "\n".join([
        cabecera("🔑", f"El acceso de la IA caduca el {cuando}"),
        "", f"Quedan <b>{dias} día(s)</b>.", paso,
    ])


# --------------------------------------------------------------------------
# Resumen diario
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResumenCartera:
    cartera: str
    equity_usd: float
    cambio_dia_usd: float          # equity al final del dia menos al empezarlo
    drawdown_max_pct: float
    cerradas_hoy: int
    resultado_hoy_usd: float       # neto de las cerradas hoy
    posiciones: int
    max_posiciones: int
    modo: str
    ultima_vela_ms: int | None
    llamadas_claude: int | None = None     # solo la cartera de la IA
    presupuesto_claude: int | None = None


def resumen_diario(dia: date, carteras: Sequence[ResumenCartera], extra: Sequence[str] = ()) -> str:
    bloques = [cabecera("📋", f"Resumen del {dia.strftime('%d/%m/%Y')}", "UTC")]
    for r in carteras:
        filas = [
            ("Equity", f"{usd(r.equity_usd)}  ({usd(r.cambio_dia_usd, signo=True)} hoy)"),
            ("Drawdown", f"{numero(r.drawdown_max_pct, 1)} % máx"),
            ("Cerradas", f"{r.cerradas_hoy}  ({usd(r.resultado_hoy_usd, signo=True)})"),
            ("Posiciones", f"{r.posiciones}/{r.max_posiciones}"),
        ]
        if r.llamadas_claude is not None:
            filas.append(("IA", f"{r.llamadas_claude}/{r.presupuesto_claude} llamadas"))
        estado = "🟢" if r.modo == "NORMAL" else "⚠️"
        bloque = [f"<b>{cartera_de(r.cartera)}</b>  {estado} <code>{esc(r.modo)}</code>", tabla(filas)]
        if r.ultima_vela_ms is not None:
            bloque.append(f"<i>Última vela {hora(r.ultima_vela_ms)}</i>")
        bloques.append("\n".join(bloque))
    bloques.extend(extra)
    return "\n\n".join(bloques)


# --------------------------------------------------------------------------
# Noticias (docs/diseno-noticias.md, pieza 7)
# --------------------------------------------------------------------------
#
# Los titulos y los enlaces vienen de FUERA (la API de anuncios de OKX): texto no confiable
# (PRD 6). El titulo va SIEMPRE por esc(); el enlace solo sale si es https y de okx.com, y
# tambien escapado. Aqui no se importa `features.news`: se reciben textos sueltos ("delisting",
# "critica"), asi los mensajes no dependen de la pieza de noticias para probarse.

TIPO_NOTICIA = {
    "delisting": "deslistado",
    "trading_suspension": "cotización suspendida",
    "incident": "incidente de seguridad",
    "migration": "migración del token",
    "volatility": "volatilidad anómala",
}
ICONO_GRAVEDAD = {"critica": "🚨", "alta": "⚠️"}


def _enlace_okx(url: str | None) -> str | None:
    """Solo https y de okx.com: un enlace raro en un titulo de fuera no se ensenya."""
    if not url or not url.startswith("https://"):
        return None
    host = url[len("https://"):].split("/", 1)[0].lower()
    if host != "okx.com" and not host.endswith(".okx.com"):
        return None
    return f'<a href="{esc(url)}">Ver el anuncio de OKX</a>'


def aviso_noticia(
    par: str, tipo: str, gravedad: str, titulo: str, *, url: str | None = None,
    hasta_ms: int | None = None, vendidas: Sequence[str] = (),
) -> str:
    """Una flag nueva. `vendidas`: las carteras en que se salio a mercado (decision 2 del propietario)."""
    lineas = [
        cabecera(ICONO_GRAVEDAD.get(gravedad, "⚠️"), f"{esc(par)}: {esc(TIPO_NOTICIA.get(tipo, tipo))}"),
        "",
        f"«{esc(titulo)}»",
    ]
    enlace = _enlace_okx(url)
    if enlace:
        lineas.append(enlace)
    lineas.append("")
    if gravedad == "critica":
        lineas.append("No se abre nada en esta moneda.")
        if vendidas:
            lineas.append("Vendido a mercado en: " + ", ".join(cartera_de(c) for c in vendidas) + ".")
    else:
        lineas.append("No se abre nada en esta moneda (las posiciones siguen con su OCO).")
    if hasta_ms is None:
        lineas.append("<b>No caduca sola.</b> Decide qué hacer: quitar la moneda de la lista (y de la "
                      "clave de OKX) o levantar el aviso si es una falsa alarma.")
    else:
        lineas.append(f"Hasta el {hora(hasta_ms)}.")
    return "\n".join(lineas)


def noticias_pendientes(pendientes: Sequence[tuple[str, str, int, str]], ahora_ms: int) -> str | None:
    """Para el resumen diario: los avisos que esperan una decision del propietario (decision 5).

    `pendientes`: (par, tipo, desde_ms, titulo). None si no hay ninguno: el resumen no se
    llena de secciones vacias.
    """
    if not pendientes:
        return None
    filas = [f"• <b>{esc(par)}</b>: {esc(TIPO_NOTICIA.get(tipo, tipo))}, hace {duracion(ahora_ms - desde)}"
             for par, tipo, desde, _t in pendientes]
    return "\n".join([cabecera("🚨", "Pendiente de decidir"), *filas])


def fuente_noticias_caida(desde_ms: int, ahora_ms: int) -> str:
    """La fuente cae: se avisa, pero NO se bloquea nada (decision del propietario del 22/09)."""
    return "\n".join([
        cabecera("📡", f"Sin anuncios de OKX desde hace {duracion(ahora_ms - desde_ms)}"),
        "",
        "No se bloquea nada: las noticias son un filtro, no una regla dura.",
        "Los avisos ya vistos se mantienen hasta que caduquen.",
    ])
