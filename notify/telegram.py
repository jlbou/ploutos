"""El cliente de Telegram (PRD seccion 9).

Dos reglas que no hay que deshacer:

1. **El token NUNCA sale en un error.** La API de Telegram lleva el token en la
   URL (`/bot<token>/sendMessage`), asi que cualquier traza de `urllib` lo
   filtraria. Todo texto de error pasa por `core.secrets.scrub_url`.
2. **`send_message` nunca lanza.** Un aviso que falla no puede tumbar al que
   avisa: si Telegram esta caido, el bucle sigue y el fallo queda en el
   resultado (y en el log de quien llame).

Sin dependencias nuevas: `urllib` de la biblioteca estandar. Lo usa tambien
`scripts/setup_telegram.py` (fase 0), para que haya UNA sola forma de hablar
con la API.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from core.secrets import scrub_url

API = "https://api.telegram.org"
TIMEOUT = 20
# Telegram corta en 4.096 caracteres. Un aviso tan largo es un fallo de quien lo
# escribe, pero se recorta en vez de perderlo entero.
MAX_LEN = 4096
RECORTE = "\n[...recortado]"


class TelegramError(Exception):
    pass


def call(
    token: str, method: str, params: dict[str, Any] | None = None,
    *, timeout: float = TIMEOUT, _open: Any = urllib.request.urlopen,
) -> Any:
    """Llama a la API de Telegram. El token nunca aparece en los errores."""
    url = f"{API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "ploutos/0.1"}
    )
    try:
        with _open(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        try:
            description = json.loads(body).get("description", body)
        except json.JSONDecodeError:
            description = body
        raise TelegramError(
            f"HTTP {exc.code} en {method}: {scrub_url(description, token)}"
        ) from None
    except Exception as exc:
        raise TelegramError(
            f"no se pudo contactar con Telegram en {method}: "
            f"{scrub_url(str(exc), token)}"
        ) from None
    if not payload.get("ok"):
        raise TelegramError(
            f"{method} devolvio error: "
            f"{scrub_url(str(payload.get('description')), token)}"
        )
    return payload["result"]


@dataclass(frozen=True, slots=True)
class Envio:
    ok: bool
    detalle: str


def recortar(texto: str) -> str:
    if len(texto) <= MAX_LEN:
        return texto
    return texto[: MAX_LEN - len(RECORTE)] + RECORTE


def a_texto_plano(texto_html: str) -> str:
    """El mismo aviso sin etiquetas: lo que se manda si Telegram rechaza el HTML."""
    return html.unescape(re.sub(r"<[^>]+>", "", texto_html))


def send_message(
    token: str | None, chat_id: str | None, texto_html: str,
    *, timeout: float = TIMEOUT, _open: Any = urllib.request.urlopen,
) -> Envio:
    """Manda un aviso con formato HTML de Telegram. NUNCA lanza.

    HTML y no Markdown: con Markdown, un `_` (el de `pullback_trend`) rompe el
    formato y Telegram rechaza el mensaje entero; en HTML solo hay que escapar
    `<`, `>` y `&`, y eso lo hace `notify.messages` con todo texto variable.
    Si aun asi Telegram no entiende el HTML, se reenvia en TEXTO PLANO: un
    aviso feo es mejor que un aviso que no llega.
    """
    if not token or not chat_id:
        return Envio(False, "sin TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")

    def enviar(texto: str, modo: str | None) -> None:
        params = {"chat_id": chat_id, "text": recortar(texto), "disable_web_page_preview": "true"}
        if modo:
            params["parse_mode"] = modo
        call(token, "sendMessage", params, timeout=timeout, _open=_open)

    try:
        try:
            enviar(texto_html, "HTML")
        except TelegramError as exc:
            if "parse entities" not in str(exc):
                raise
            enviar(a_texto_plano(texto_html), None)
            return Envio(True, f"enviado en texto plano: Telegram rechazo el HTML ({exc})")
    except TelegramError as exc:
        return Envio(False, str(exc))
    except Exception as exc:  # pragma: no cover - red de seguridad: nunca lanza
        return Envio(False, scrub_url(f"{type(exc).__name__}: {exc}", token))
    return Envio(True, "enviado")
