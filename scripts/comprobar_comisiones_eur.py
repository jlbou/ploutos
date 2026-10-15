"""Las comisiones REALES de BTC-EUR y ETH-EUR en la cuenta de OKX (paso 2, comprobacion V2; propietario, 15/10/2026).

Usa una clave de la cuenta real SOLO DE LECTURA (`OKX_LECTURA_*` en el `.env`). **Si la clave tiene permiso de
trading o de retirada, no consulta nada** y lo dice: para esto basta leer. No imprime nada de la credencial.
Ensenya, par por par, el grupo de comisiones (`groupId`) y todos los campos maker/taker tal como los da OKX (el signo,
al reves: negativo = la pagas), y la lectura en % positivo.

    ssh <alias> "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/comprobar_comisiones_eur.py"

    exit 0 -> leidas      exit 1 -> la clave no es solo de lectura, o OKX no contesto      exit 2 -> sin clave
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PARES = ("BTC-EUR", "ETH-EUR")


def permisos(config: dict[str, Any]) -> set[str]:
    datos = (config or {}).get("data") or [{}]
    return {p.strip() for p in str(datos[0].get("perm", "")).split(",") if p.strip()}


def solo_lectura(perm: set[str]) -> bool:
    """Exactamente lectura: ni `trade` ni `withdraw` (ni nada mas)."""
    return perm == {"read_only"}


def campos(respuesta: dict[str, Any]) -> dict[str, Any]:
    """Los campos de comision de la respuesta (los maker/taker de primer nivel y los grupos), sin tocar."""
    datos = ((respuesta or {}).get("data") or [{}])[0]
    out = {k: v for k, v in datos.items() if ("maker" in k.lower() or "taker" in k.lower()) and v not in ("", None)}
    out["feeGroup"] = [{k: g.get(k) for k in ("groupId", "maker", "taker")} for g in datos.get("feeGroup") or []]
    return out


def pct(valor: Any) -> float | None:
    return None if valor in (None, "") else -float(valor) * 100.0


async def main() -> int:
    import ccxt.async_support as ccxt

    from core.config import load_settings
    from core.secrets import Secrets

    s, settings = Secrets(), load_settings()
    if not all((s.okx_lectura_api_key, s.okx_lectura_api_secret, s.okx_lectura_password)):
        print("Sin la clave de solo lectura (OKX_LECTURA_* en el .env): nada que hacer.")
        return 2
    client = ccxt.okx({"hostname": settings.exchange.hostname,
                       "apiKey": s.okx_lectura_api_key.get_secret_value(),
                       "secret": s.okx_lectura_api_secret.get_secret_value(),
                       "password": s.okx_lectura_password.get_secret_value(),
                       "options": {"defaultType": "spot"}})
    try:
        perm = permisos(await client.private_get_account_config())
        print(f"Permisos de la clave: {sorted(perm)}")
        if not solo_lectura(perm):
            print("NO SE CONSULTA NADA: la clave no es solo de lectura. Quitale trading y retirada en OKX.")
            return 1
        for par in PARES:
            c = campos(await client.private_get_account_trade_fee({"instType": "SPOT", "instId": par}))
            grupos = c.pop("feeGroup")
            print(f"\n{par}: grupo {', '.join(str(g['groupId']) for g in grupos) or '?'}")
            for k, v in c.items():
                print(f"  {k:12} {v:>10}  ->  {pct(v):.3f} %")
            for g in grupos:
                print(f"  grupo {g['groupId']}: maker {pct(g['maker'])} %, taker {pct(g['taker'])} %")
        return 0
    except Exception as exc:  # noqa: BLE001 - nunca el mensaje entero (podria llevar la cabecera)
        print(f"OKX no contesto bien: {type(exc).__name__}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
