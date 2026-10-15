"""Pone la comision del spot en la moneda de cotizacion (USDC) en la cuenta DEMO de OKX: `feeType = 1`.

Decision 2 de la fase 4 (docs/archivo/diseno-fase-4.md): con la comision en la moneda que se RECIBE (el valor por
defecto, `feeType = 0`), comprar 0,15 ETH deja 0,14985 y la OCO de 0,15 pide mas de lo que hay. Con `feeType = 1`
la cantidad comprada es exacta y la contabilidad cuadra con la del papel. Verificado el 23/09 en la documentacion:
`POST /api/v5/account/set-fee-type`, solo spot (docs/preparacion-fase-4.md, seccion 5).

el propietario, 28/09/2026: lo hago yo por la API, YA (excepcion acotada a "nada de claves hasta la fase 4": solo el demo,
reversible, sin ordenes; de paso se comprueba que la clave sigue viva antes del 02/10). En la cuenta real sera otra
decision. No imprime nada de la credencial. Se ejecuta en el VPS (la clave solo funciona desde su IP):

    ssh ploutos "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/fijar_comision_usdc.py"            # solo lee
    ssh ploutos "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/fijar_comision_usdc.py --aplicar"  # cambia y relee

El dia que empiece la fase 4, volver a lanzarlo SIN --aplicar: si OKX reinicia el demo, el ajuste podria perderse.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EN_USDC = "1"
QUE_ES = {"0": "en la moneda que se recibe (por defecto)", "1": "en la moneda de cotizacion (USDC)"}
CODIGOS_OKX = ("50101", "50105", "50110", "50111", "50113", "50114", "50119")


def fee_type_de(respuesta: dict[str, Any]) -> str | None:
    """El `feeType` de la respuesta de /api/v5/account/config, o None si no viene."""
    datos = (respuesta or {}).get("data") or [{}]
    valor = datos[0].get("feeType")
    return None if valor is None else str(valor)


async def fijar(client: Any, aplicar: bool) -> int:
    """Lee, y con `aplicar` cambia a USDC y relee. Devuelve el codigo de salida."""
    antes = fee_type_de(await client.private_get_account_config())
    print(f"Ahora: feeType = {antes} ({QUE_ES.get(antes or '', 'desconocido')})")
    if antes == EN_USDC:
        print("Ya esta en USDC: no hay nada que cambiar.")
        return 0
    if not aplicar:
        print("Sin --aplicar no se cambia nada.")
        return 0
    respuesta = await client.private_post_account_set_fee_type({"feeType": EN_USDC})
    if str(respuesta.get("code")) != "0":
        print(f"OKX no lo ha aceptado: code {respuesta.get('code')} {respuesta.get('msg', '')}")
        return 1
    despues = fee_type_de(await client.private_get_account_config())
    print(f"Despues: feeType = {despues} ({QUE_ES.get(despues or '', 'desconocido')})")
    if despues != EN_USDC:
        print("FALLA: OKX dijo que si, pero la configuracion no ha cambiado.")
        return 1
    print("Hecho: la comision del spot se cobra en USDC.")
    return 0


async def main() -> int:
    import ccxt.async_support as ccxt

    from core.config import load_settings
    from core.secrets import load_secrets

    ap = argparse.ArgumentParser(description="Comision del spot en USDC (feeType = 1), solo en el demo")
    ap.add_argument("--aplicar", action="store_true", help="cambiarla (sin esto solo se lee)")
    args = ap.parse_args()

    settings, secrets = load_settings(), load_secrets()
    if not secrets.has_okx:
        print("Faltan las credenciales de OKX en .env.")
        return 2
    if not secrets.okx_demo:
        print("La clave NO es la del demo: en la cuenta real esto es otra decision del propietario. No se toca nada.")
        return 2
    client = ccxt.okx({
        "hostname": settings.exchange.hostname,
        "apiKey": secrets.okx_api_key.get_secret_value(),
        "secret": secrets.okx_api_secret.get_secret_value(),
        "password": secrets.okx_password.get_secret_value(),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
        "headers": {"User-Agent": "ploutos/0.1"},
    })
    client.set_sandbox_mode(True)
    try:
        print(f"Entorno: DEMO, host {settings.exchange.hostname}")
        return await fijar(client, args.aplicar)
    except Exception as exc:  # noqa: BLE001 - solo el tipo y el codigo de OKX: nunca la URL ni las cabeceras
        codigo = next((c for c in CODIGOS_OKX if c in str(exc)), "")
        print(f"Error: {type(exc).__name__} {codigo}".strip())
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
