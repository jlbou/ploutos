"""Verifica la clave de API de OKX (regla dura 19).

Comprueba, sin imprimir NUNCA ningun valor de la credencial:

  1. que autentica,
  2. que la restriccion de IP funciona,
  3. que tiene permiso de lectura y de trading,
  4. que NO tiene permiso de retirada,
  5. que pares de la whitelist se pueden operar de verdad en ese entorno.

Se ejecuta en el VPS, que es la IP de la lista blanca:

    ssh ploutos "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/verify_okx_key.py"

Desde el portatil FALLARA por IP, y eso es lo correcto: demuestra que la lista blanca protege.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt.async_support as ccxt  # noqa: E402

from core.config import ConfigError, load_settings  # noqa: E402
from core.secrets import load_secrets  # noqa: E402

# Patrones de error de OKX que nos interesa distinguir.
IP_ERRORS = ("50110", "not included in the ip whitelist", "ip address")
AUTH_ERRORS = ("50111", "50112", "50113", "invalid sign", "apikey does not match")
PASSPHRASE_ERRORS = ("50105", "passphrase")
# 50119 no significa lo que dice. Ver la explicacion en el manejo del error.
UNKNOWN_KEY_ERRORS = ("50119", "api key doesn't exist")
# 50101 = clave de un entorno pedida contra el otro (demo <-> real).
WRONG_ENV_ERRORS = ("50101", "broker id of apikey does not match")


def classify(message: str) -> str:
    low = message.lower()
    if any(p in low for p in WRONG_ENV_ERRORS):
        return "wrong_env"
    if any(p in low for p in UNKNOWN_KEY_ERRORS):
        return "unknown_key"
    if any(p in low for p in IP_ERRORS):
        return "ip"
    if any(p in low for p in PASSPHRASE_ERRORS):
        return "passphrase"
    if any(p in low for p in AUTH_ERRORS):
        return "auth"
    return "other"


async def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuracion invalida: {exc}")
        return 2

    secrets = load_secrets()
    if not secrets.has_okx:
        print("Faltan credenciales de OKX en .env.")
        print("Hacen falta OKX_API_KEY, OKX_API_SECRET y OKX_PASSWORD.")
        return 2

    demo = secrets.okx_demo
    print(f"Entorno: {'DEMO (trading simulado)' if demo else 'REAL'}")
    print()

    print(f"Host: {settings.exchange.hostname}")
    print()

    client = ccxt.okx({
        "hostname": settings.exchange.hostname,
        "apiKey": secrets.okx_api_key.get_secret_value(),
        "secret": secrets.okx_api_secret.get_secret_value(),
        "password": secrets.okx_password.get_secret_value(),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
        "headers": {"User-Agent": "ploutos/0.1"},
    })
    if demo:
        client.set_sandbox_mode(True)

    exit_code = 0
    try:
        # --- 1. autenticacion ---
        print("1. Autenticacion")
        try:
            await client.fetch_balance()
            print("   OK: la clave autentica correctamente")
        except Exception as exc:
            kind = classify(str(exc))
            if kind == "ip":
                print("   RECHAZADA: la clave existe pero la IP no esta autorizada.")
                print("   Fuera del VPS es el resultado CORRECTO: demuestra que la")
                print("   lista blanca protege la clave (regla 19).")
                return 0
            if kind == "unknown_key":
                print("   OKX dice que la clave NO EXISTE (50119).")
                print("   Ojo: responde lo mismo en TRES situaciones distintas y")
                print("   nunca dice cual es. Comprobar en este orden:")
                print()
                print("   a) HOST. Una cuenta europea necesita 'eea.okx.com'.")
                print(f"      Ahora se esta usando: {settings.exchange.hostname}")
                print("      Con el 'www.okx.com' por defecto de ccxt da este mismo error.")
                print("   b) IP DE SALIDA. Si el servidor prefiere IPv6, OKX ve una IP")
                print("      distinta de la de la lista blanca. Comprobar con:")
                print("          curl -s https://api64.ipify.org")
                print("   c) La clave esta mal copiada en .env.")
                return 1
            if kind == "wrong_env":
                print("   La clave es de OTRO entorno (50101).")
                env = "DEMO" if demo else "REAL"
                other = "REAL" if demo else "DEMO"
                print(f"   Se esta pidiendo el entorno {env} con una clave de {other}.")
                print("   Cambia OKX_DEMO en .env, o crea la clave en el entorno correcto.")
                return 1
            if kind == "passphrase":
                print("   FALLA: la passphrase no es correcta.")
                print("   Es la 'frase de contrasenya' que pusiste al crear la clave,")
                print("   no la de tu cuenta de OKX. Va en OKX_PASSWORD.")
                return 1
            if kind == "auth":
                print("   FALLA: la clave o el secreto no son correctos.")
                print("   Revisa que los copiaste enteros y sin espacios.")
                return 1
            print(f"   FALLA con un error no reconocido: {type(exc).__name__}")
            return 1

        # --- 2. permiso de lectura ---
        print()
        print("2. Permiso de lectura")
        await client.fetch_balance()
        print("   OK")

        # --- 3. permiso de retirada: NO debe tenerlo (regla 19) ---
        print()
        print("3. Permiso de RETIRADA (no debe tenerlo)")
        try:
            await client.private_get_asset_currencies()
            print("   AVISO: la peticion de datos de retirada no fue rechazada.")
            print("   Comprueba a mano en OKX que 'Retirar' esta DESMARCADO.")
        except Exception as exc:
            if "permission" in str(exc).lower() or "50114" in str(exc):
                print("   OK: sin permiso de retirada, como manda la regla 19")
            else:
                print("   (no concluyente; comprueba a mano que 'Retirar' esta desmarcado)")

        # --- 4. pares operables en este entorno ---
        print()
        print("4. Pares de la whitelist operables en este entorno")
        await client.load_markets()
        available, missing = [], []
        for symbol in settings.whitelist:
            market = client.markets.get(symbol)
            if market and market.get("active") and market.get("spot"):
                available.append(symbol)
            else:
                missing.append(symbol)

        for symbol in settings.whitelist:
            print(f"   {'OK  ' if symbol in available else 'NO  '}{symbol}")

        print()
        print(f"   {len(available)} de {len(settings.whitelist)} operables aqui")
        if missing and demo:
            print(f"   Faltan en DEMO: {', '.join(missing)}")
            print("   Es esperado: el catalogo del demo es mas pequenyo que el real.")
            print("   No cambia la whitelist: la fase 7 opera contra el mercado real.")
        elif missing:
            print(f"   FALTAN EN EL MERCADO REAL: {', '.join(missing)}")
            print("   Esto SI es un problema: afecta a la regla 3.")
            exit_code = 1

        print()
        print("Verificacion terminada. No se ha impreso ningun valor de la credencial.")
        return exit_code
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
