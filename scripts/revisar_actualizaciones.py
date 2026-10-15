"""La revision semanal de actualizaciones (decision del propietario del 26/09/2026): un Telegram solo si hay algo.

La lanza `deploy/actualizar-semanal.sh` los domingos a las 07:30 UTC (entre dos cierres de vela), despues
de actualizar Tailscale, que es lo UNICO que se instala solo. El resto solo se AVISA, porque tiene la
version fijada a proposito y cambiarla sin pasar los tests puede romper el bot (una ccxt nueva puede
cambiar como manda las ordenes; el CLI de la IA se verifico en una version concreta):

- las librerias del bot (lo instalado en el entorno contra lo ultimo de PyPI);
- el programa de la IA (`ai.invoke.VERIFIED_VERSION` contra el canal estable);
- los paquetes de Ubuntu pendientes que NO son de seguridad (los de seguridad ya entran solos cada dia).

Nunca nombra a Claude: "el programa de la IA" (decision del propietario del 25/09).

    .venv/bin/python scripts/revisar_actualizaciones.py --tailscale <antes> <despues>
    .venv/bin/python scripts/revisar_actualizaciones.py --seco        # ensenya el aviso sin mandarlo
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from notify.messages import cabecera, esc  # noqa: E402

PAQUETES = ("ccxt", "pandas", "numpy", "pydantic", "pydantic-settings", "PyYAML", "fastapi", "uvicorn",
            "websockets")
CANAL_IA = "https://downloads.claude.ai/claude-code-releases/stable"
UA = {"User-Agent": "ploutos/0.1"}
MAX_UBUNTU = 8


def version(texto: str) -> tuple:
    """"4.5.84" -> (4, 5, 84). Sin dependencias: lo que no es numero cuenta como 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.+-]", texto.strip()))


def mas_nueva(instalada: str, ultima: str) -> bool:
    return version(ultima) > version(instalada)


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return r.read().decode("utf-8").strip()


def ultimas_de_pypi(nombres: Sequence[str], get: Callable[[str], str] = _get) -> dict[str, str | None]:
    out = {}
    for n in nombres:
        try:
            out[n] = json.loads(get(f"https://pypi.org/pypi/{n}/json"))["info"]["version"]
        except Exception:
            out[n] = None                 # no se sabe: no se avisa de nada inventado
    return out


def instaladas(nombres: Sequence[str]) -> dict[str, str | None]:
    out = {}
    for n in nombres:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = None
    return out


def ubuntu_pendientes(_run=subprocess.run) -> list[str]:
    """Los paquetes de Ubuntu con version nueva que no se han instalado (no son de seguridad)."""
    try:
        r = _run(["apt", "list", "--upgradable"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted({l.split("/", 1)[0] for l in r.stdout.splitlines()
                   if "/" in l and not l.startswith("Listing") and not l.startswith("tailscale/")})


def mensaje(*, tailscale: tuple[str, str] | None, librerias: Mapping[str, tuple[str | None, str | None]],
            ia: tuple[str, str | None], ubuntu: Sequence[str]) -> str | None:
    """El aviso, o None si no hay nada que contar."""
    nuevas = [(n, a, b) for n, (a, b) in librerias.items() if a and b and mas_nueva(a, b)]
    ia_nueva = ia[1] is not None and mas_nueva(ia[0], ia[1])
    ts_cambio = tailscale is not None and tailscale[0] != tailscale[1]
    if not (nuevas or ia_nueva or ts_cambio or ubuntu):
        return None
    lineas = [cabecera("🔄", "Revisión semanal de actualizaciones")]
    if ts_cambio:
        lineas += ["", f"✅ <b>Instalado solo:</b> Tailscale {esc(tailscale[0])} → {esc(tailscale[1])}"]
    if nuevas or ia_nueva:
        lineas += ["", "<b>Versiones nuevas que NO se instalan solas</b> (hay que pasar los tests antes):"]
        lineas += [f"• {esc(n)} {esc(a)} → {esc(b)}" for n, a, b in nuevas]
        if ia_nueva:
            lineas.append(f"• el programa de la IA {esc(ia[0])} → {esc(ia[1])}")
    if ubuntu:
        mas = f" y {len(ubuntu) - MAX_UBUNTU} más" if len(ubuntu) > MAX_UBUNTU else ""
        lineas += ["", f"<b>Ubuntu:</b> {len(ubuntu)} paquete(s) pendiente(s) que no son de seguridad: "
                   f"{esc(', '.join(ubuntu[:MAX_UBUNTU]))}{mas}."]
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Revision semanal de actualizaciones")
    ap.add_argument("--tailscale", nargs=2, metavar=("ANTES", "DESPUES"))
    ap.add_argument("--seco", action="store_true")
    args = ap.parse_args()

    from ai.invoke import VERIFIED_VERSION
    try:
        ia = (VERIFIED_VERSION, _get(CANAL_IA))
    except Exception:
        ia = (VERIFIED_VERSION, None)
    inst, ult = instaladas(PAQUETES), ultimas_de_pypi(PAQUETES)
    texto = mensaje(tailscale=tuple(args.tailscale) if args.tailscale else None,
                    librerias={n: (inst[n], ult[n]) for n in PAQUETES}, ia=ia, ubuntu=ubuntu_pendientes())
    if texto is None:
        print("nada nuevo: no se manda nada")
        return 0
    if args.seco:
        print(texto)
        return 0
    from core.secrets import Secrets
    from notify.telegram import send_message
    s = Secrets()
    envio = send_message(s.valor("telegram_bot_token"), s.telegram_chat_id, texto)
    print(f"aviso: {envio.detalle}")
    return 0 if envio.ok else 1


if __name__ == "__main__":
    sys.exit(main())
