"""Copia al `.env` del VPS SOLO las claves que se nombran, desde el `.env` del portatil (decision del propietario del
15/10/2026). Nunca ensenya un valor: compara la huella (SHA-256) de cada clave aqui y alli.

    .venv/Scripts/python.exe deploy/env_a_vps.py <alias> CLAVE [CLAVE ...]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_fusionar import SOLO_PORTATIL, huella, leer  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    alias, claves = sys.argv[1], sys.argv[2:]
    locales = leer((REPO / ".env").read_text(encoding="utf-8-sig"))
    faltan = [k for k in claves if not locales.get(k, "").strip()]
    if not claves or faltan or SOLO_PORTATIL & set(claves):
        print(f"No se copia nada: sin claves, vacias o del portatil: {faltan or sorted(SOLO_PORTATIL & set(claves))}")
        return 1
    carga = "".join(f"{k}={locales[k]}\n" for k in claves)
    r = subprocess.run(["ssh", alias, "sudo -u ploutos python3 /opt/ploutos/deploy/env_fusionar.py /opt/ploutos/.env"],
                       input=carga, capture_output=True, text=True, timeout=60)
    print(r.stdout.strip() or r.stderr.strip()[-300:])
    ok = r.returncode == 0
    lineas = {ln.split(": ", 1)[0]: ln for ln in r.stdout.splitlines() if ": " in ln}
    for k in claves:
        igual = lineas.get(k, "").endswith(f"huella {huella(locales[k])}")
        print(f"  {k}: {'la huella COINCIDE con la del portatil' if igual else 'NO coincide'}")
        ok &= igual
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
