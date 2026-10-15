"""Fase 0: crear y verificar el bot de Telegram (PRD seccion 9).

Te guia paso a paso y comprueba cada cosa. NUNCA imprime el token, ni siquiera
en los mensajes de error (la API de Telegram lleva el token en la URL, asi que
cualquier traza lo filtraria si no se limpiase).

Uso:
    python scripts/setup_telegram.py            # diagnostica y te dice que falta
    python scripts/setup_telegram.py --chat-id  # busca tu chat_id
    python scripts/setup_telegram.py --test     # manda un mensaje de prueba
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.secrets import ENV_PATH, load_secrets  # noqa: E402
from notify.telegram import TelegramError, call  # noqa: E402  (una sola forma de hablar con la API)

BOTFATHER = """
Todavia no hay token. Para crear el bot:

  1. En Telegram, busca  @BotFather  y abre el chat.
  2. Manda  /newbot
  3. Te pide un NOMBRE (el que se ve).      Ejemplo: Ploutos
  4. Te pide un USUARIO, que debe acabar en 'bot' y ser unico.
                                            Ejemplo: mi_ploutos_bot
  5. Te responde con un token, con esta pinta:
         <numero del bot>:<unos 35 caracteres de letras, numeros, - y _>
  6. Copialo en el fichero .env de este repositorio, en la linea:

         TELEGRAM_BOT_TOKEN=<el token entero>

  7. Vuelve a ejecutar este script.

El token es una credencial: da control total del bot. No lo pegues en el chat
ni lo subas a git. El fichero .env ya esta en .gitignore.
"""

CHAT_ID_HELP = """
Falta tu chat_id: es el numero que identifica TU conversacion con el bot, y
sirve para que el bot solo te hable a ti (PRD seccion 9).

  1. En Telegram, abre el chat con tu bot (buscalo por su usuario).
  2. Pulsa START o mandale cualquier mensaje, por ejemplo: hola
  3. Vuelve a ejecutar:  python scripts/setup_telegram.py --chat-id
"""


def ensure_env_file() -> None:
    if ENV_PATH.is_file():
        return
    example = ENV_PATH.parent / ".env.example"
    print(f"No existe {ENV_PATH.name}. Creandolo a partir de .env.example...")
    ENV_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Creado {ENV_PATH}. Rellena TELEGRAM_BOT_TOKEN y vuelve a ejecutar.")


def show_status() -> None:
    secrets = load_secrets()
    print("Estado de los secretos (solo si estan puestos, nunca su valor):")
    for name, present in secrets.status().items():
        print(f"   {'[x]' if present else '[ ]'} {name}")
    print()


def find_chat_id(token: str) -> int | None:
    updates = call(token, "getUpdates", {"limit": 100})
    chats: dict[int, str] = {}
    for update in updates:
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
        )
        if not message:
            continue
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        who = chat.get("username") or chat.get("first_name") or chat.get("title") or "?"
        chats[chat_id] = f"{who} ({chat.get('type')})"

    if not chats:
        print(CHAT_ID_HELP)
        return None

    print("Conversaciones encontradas:")
    for chat_id, who in chats.items():
        print(f"   chat_id = {chat_id}   <- {who}")
    print()
    if len(chats) == 1:
        chat_id = next(iter(chats))
        print("Anyade esta linea a tu .env:")
        print()
        print(f"   TELEGRAM_CHAT_ID={chat_id}")
        print()
        return chat_id
    print("Hay varias. Elige la tuya y ponla en .env como TELEGRAM_CHAT_ID.")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fase 0: crear y verificar el bot de Telegram"
    )
    parser.add_argument("--chat-id", action="store_true",
                        help="buscar tu chat_id en los mensajes recibidos")
    parser.add_argument("--test", action="store_true",
                        help="mandar un mensaje de prueba")
    args = parser.parse_args()

    ensure_env_file()
    show_status()

    secrets = load_secrets()
    if not secrets.has_telegram:
        print(BOTFATHER)
        return 2

    token = secrets.telegram_bot_token.get_secret_value()  # type: ignore[union-attr]

    # --- 1. el token vale? ---
    try:
        me = call(token, "getMe")
    except TelegramError as exc:
        print(f"El token no funciona: {exc}")
        print()
        print("Revisa que lo copiaste entero (incluido el numero y los dos puntos)")
        print("y sin espacios ni comillas alrededor.")
        return 1

    print(f"Bot verificado: @{me['username']}  (nombre: {me.get('first_name')})")
    print(f"   id del bot: {me['id']}")
    print()

    # --- 2. chat_id ---
    if args.chat_id or not secrets.has_telegram_chat:
        chat_id = find_chat_id(token)
        if chat_id is None:
            return 2
        if not secrets.has_telegram_chat:
            print("Ponlo en .env y vuelve a ejecutar con --test.")
            return 2
    else:
        chat_id = secrets.telegram_chat_id
        print(f"chat_id configurado: {chat_id}")
        print()

    # --- 3. mensaje de prueba ---
    if args.test:
        text = (
            "Ploutos: bot de Telegram verificado.\n"
            "Fase 0 en marcha. Todavia no opera ni tiene claves de OKX."
        )
        call(token, "sendMessage", {"chat_id": chat_id, "text": text})
        print("Mensaje de prueba enviado. Miralo en Telegram.")
        print()
        print("Si te ha llegado, el bot de Telegram de la fase 0 esta CERRADO.")
        return 0

    print("Todo listo. Para la comprobacion final:")
    print("   python scripts/setup_telegram.py --test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
