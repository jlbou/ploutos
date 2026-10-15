"""Comprueba la cuenta DEMO de OKX antes de operar (paso 2 del guion de la fase 4). SOLO LEE: ninguna orden.

Lo que mira, y cuando NO se opera:
1. **Permisos de la clave** (`perm` de `/api/v5/account/config`): tiene que tener lectura y trading y NUNCA
   retirada (regla 19). `verify_okx_key.py` lo deduce de un rechazo y a veces no es concluyente; este campo lo
   dice OKX directamente.
2. **La comision en USDC** (`feeType = 1`, decision 2 de la fase 4): si OKX reinicio el demo, se pierde.
3. **Las comisiones reales de la cuenta** (`/api/v5/account/trade-fee`, SPOT): decision del propietario del 23/09, "si las
   reales son MAS CARAS que las configuradas, no se opera". Dos detalles de esa API: el signo va al reves (negativo
   = la pagas) y para los pares contra USDC se leen `makerUSDC`/`takerUSDC`, no `maker`/`taker` (son los de USDT).
   **Par por par:** van por grupos (`groupId` del instrumento) y no todos pagan lo mismo. El 02/10, en el demo,
   NEAR-USDC (grupo 13) pagaba 0,20 % / 0,35 % y los otros cuatro (grupo 12) 0,10 % / 0,20 %; mirando solo BTC no
   se vio.
4. **El saldo:** cuanto USDC hay (total, no libre: regla 6) y que otras monedas quedan.

No imprime nada de la credencial: solo tipos de error y codigos de OKX. Se ejecuta en el VPS (la IP de la clave):
    ssh ploutos "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/comprobar_cuenta_demo.py"

    exit 0 -> todo en orden para operar en el demo
    exit 1 -> algo impide operar (se dice que)
    exit 2 -> sin credenciales del demo
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution.comisiones import comision_usdc, motivos_par  # noqa: E402 - la misma regla que el ejecutor

CODIGOS_OKX = ("50101", "50105", "50110", "50111", "50113", "50114", "50119")
DEMO = ("BTC-USDC", "ETH-USDC", "SOL-USDC", "DOGE-USDC", "NEAR-USDC")   # los 5 del demo contra USDC


def permisos(config: dict[str, Any]) -> set[str]:
    """Los permisos de la clave: `perm` = "read_only,trade" (y "withdraw" si la tuviera)."""
    datos = (config or {}).get("data") or [{}]
    return {p.strip() for p in str(datos[0].get("perm", "")).split(",") if p.strip()}


def veredicto(perm: set[str], fee_type: str | None, reales: dict[str, tuple[float | None, float | None]],
              configuradas: tuple[float, float]) -> list[str]:
    """Los motivos para NO operar; vacio = en orden. `reales`: (maker, taker) de cada par."""
    motivos = []
    if "withdraw" in perm:
        motivos.append("la clave TIENE permiso de retirada (regla 19): quitarlo en OKX antes de nada")
    if "trade" not in perm:
        motivos.append(f"la clave no tiene permiso de trading (perm = {sorted(perm)})")
    if fee_type != "1":
        motivos.append(f"feeType = {fee_type}: la comision no esta en USDC (fijar_comision_usdc.py --aplicar)")
    if not reales:
        motivos.append("ninguna comision leida: no se puede comparar")
    for par, valores in reales.items():
        motivos += motivos_par(par, valores, configuradas)
    return motivos


async def main() -> int:
    import ccxt.async_support as ccxt

    from core.config import load_settings
    from core.secrets import load_secrets

    settings, secrets = load_settings(), load_secrets()
    if not secrets.has_okx:
        print("Faltan las credenciales de OKX en .env.")
        return 2
    if not secrets.okx_demo:
        print("La clave NO es la del demo: este script es para el demo de la fase 4. No se mira nada.")
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
        config = await client.private_get_account_config()
        perm = permisos(config)
        fee_type = str(((config.get("data") or [{}])[0]).get("feeType"))
        print(f"1. Permisos de la clave: {', '.join(sorted(perm)) or '(vacio)'}")
        print(f"2. Comision cobrada en: {'USDC (feeType = 1)' if fee_type == '1' else f'feeType = {fee_type}'}")

        conf = (settings.exchange.fees.maker_pct, settings.exchange.fees.taker_pct)
        print(f"3. Comisiones de la cuenta, par por par (configuradas: maker {conf[0]} %, taker {conf[1]} %)")
        reales = {}
        for par in DEMO:
            fee = await client.private_get_account_trade_fee({"instType": "SPOT", "instId": par})
            reales[par] = comision_usdc(fee)
            datos = (fee.get("data") or [{}])[0]
            grupo = ",".join(str(g.get("groupId")) for g in datos.get("feeGroup") or []) or "?"
            maker, taker = (f"{x:.3f}" if x is not None else "?" for x in reales[par])
            print(f"   {par}: maker {maker} %, taker {taker} % "
                  f"(nivel {datos.get('level', '?')}, grupo {grupo})")

        balance = await client.fetch_balance()
        totales = {k: v for k, v in (balance.get("total") or {}).items() if v}
        usdc = totales.pop("USDC", 0.0)
        print(f"4. Saldo: {usdc:,.2f} USDC (total)" + (f"; ademas: {', '.join(f'{k} {v:g}' for k, v in sorted(totales.items()))}"
                                                     if totales else "; nada mas"))
        motivos = veredicto(perm, fee_type, reales, conf)
        print()
        if motivos:
            for m in motivos:
                print(f"   NO: {m}")
            print("RESULTADO: NO se opera en el demo hasta resolverlo.")
            return 1
        print("RESULTADO: la cuenta demo esta en orden para la fase 4.")
        return 0
    except Exception as exc:  # noqa: BLE001 - solo el tipo y el codigo de OKX: nunca la URL ni las cabeceras
        codigo = next((c for c in CODIGOS_OKX if c in str(exc)), "")
        print(f"Error: {type(exc).__name__} {codigo}".strip())
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
