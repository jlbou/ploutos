"""¿Puede la cuenta REAL de OKX operar BTC-EUR y ETH-EUR e ingresar euros? (paso 2, mientras V5; propietario, 16/10/2026).

Solo con la clave de SOLO LECTURA (`OKX_LECTURA_*`); si tiene trading o retirada, no consulta nada. No ensenya saldos
ni nada de la credencial: solo si cada cosa esta disponible.

1. La cuenta (`account/config`): el modo y los permisos de la clave.
2. Los pares para ESTA cuenta (`account/instruments`): BTC-EUR y ETH-EUR, su estado y su minimo por orden.
3. El euro (`asset/currencies`): si se puede ingresar y retirar.
4. Los ingresos en euros (`fiat/deposit-payment-methods`): que metodos hay (p. ej. SEPA).

    ssh <alias> "cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/comprobar_cuenta_eur.py"
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from comprobar_comisiones_eur import permisos, solo_lectura  # noqa: E402

PARES = ("BTC-EUR", "ETH-EUR")


def datos(respuesta: dict[str, Any]) -> list[dict[str, Any]]:
    return (respuesta or {}).get("data") or []


def resumen_par(instrumentos: list[dict[str, Any]], par: str) -> str:
    x = next((i for i in instrumentos if i.get("instId") == par), None)
    if x is None:
        return f"{par}: NO esta disponible para esta cuenta"
    return f"{par}: estado {x.get('state')}, minimo por orden {x.get('minSz')} {x.get('baseCcy')}, tick {x.get('tickSz')}"


def resumen_euro(monedas: list[dict[str, Any]]) -> str:
    eur = [c for c in monedas if c.get("ccy") == "EUR"]
    if not eur:
        return "EUR: no aparece en asset/currencies"
    return "EUR: " + "; ".join(f"{c.get('chain') or '-'}: ingresar {c.get('canDep')}, retirar {c.get('canWd')}" for c in eur)


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
        cfg = await client.private_get_account_config()
        perm = permisos(cfg)
        if not solo_lectura(perm):
            print("NO SE CONSULTA NADA: la clave no es solo de lectura.")
            return 1
        c = (datos(cfg) or [{}])[0]
        print(f"1. Cuenta: modo {c.get('acctLv')} (1 = spot simple), permisos de la clave {sorted(perm)}")
        inst = datos(await client.private_get_account_instruments({"instType": "SPOT"}))
        for par in PARES:
            print("2. " + resumen_par(inst, par))
        print("3. " + resumen_euro(datos(await client.private_get_asset_currencies({"ccy": "EUR"}))))
        try:
            metodos = datos(await client.private_get_fiat_deposit_payment_methods({"ccy": "EUR"}))
            nombres = sorted({str(m.get("paymentMethod")) for m in metodos})
            print(f"4. Ingresos en euros: {', '.join(nombres) or 'ninguno'}")
        except Exception as exc:  # noqa: BLE001
            print(f"4. Ingresos en euros: no se pudo consultar ({type(exc).__name__}, codigo "
                  f"{', '.join(sorted(set(re.findall(r'\\b5\\d{4}\\b', str(exc))))) or '?'})")
        return 0
    except Exception as exc:  # noqa: BLE001 - nunca el mensaje entero
        print(f"OKX no contesto bien: {type(exc).__name__}, codigo "
              f"{', '.join(sorted(set(re.findall(r'\\b5\\d{4}\\b', str(exc))))) or '?'}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
