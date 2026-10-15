"""Fusiona en el `.env` del VPS SOLO las claves que llegan por la entrada (lineas CLAVE=valor), sin tocar las demas
(decision del propietario del 15/10/2026: el `.env` se edita en el portatil y Claude copia al VPS las claves por su
nombre). NUNCA imprime un valor: por cada clave dice si se anyadio, se cambio o ya era igual, y la huella (SHA-256)
de lo escrito para compararla con la del portatil.

    ... | python3 deploy/env_fusionar.py /opt/ploutos/.env      (lo lanza deploy/env_a_vps.py; como el usuario ploutos)
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

CLAVE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SOLO_PORTATIL = {"HEALTHCHECK_COPIA_PORTATIL"}


def leer(texto: str) -> dict[str, str]:
    out = {}
    for linea in texto.splitlines():
        if "=" in linea and not linea.lstrip().startswith("#"):
            k, v = linea.split("=", 1)
            out[k.strip()] = v
    return out


def fusionar(actual: str, nuevas: dict[str, str]) -> tuple[str, dict[str, str]]:
    """El texto nuevo del `.env` y lo que paso con cada clave. Las claves que ya estan se cambian en su sitio; las
    nuevas van al final. Nunca un valor vacio ni una clave del portatil."""
    estado, lineas, vistas = {}, actual.splitlines(), set()
    for k, v in nuevas.items():
        if not CLAVE.match(k) or k in SOLO_PORTATIL or not v.strip():
            raise ValueError(f"clave no admitida o vacia: {k}")
    for i, linea in enumerate(lineas):
        k = linea.split("=", 1)[0].strip() if "=" in linea and not linea.lstrip().startswith("#") else None
        if k in nuevas:
            vistas.add(k)
            estado[k] = "igual" if linea.split("=", 1)[1] == nuevas[k] else "cambiada"
            lineas[i] = f"{k}={nuevas[k]}"
    for k, v in nuevas.items():
        if k not in vistas:
            lineas.append(f"{k}={v}")
            estado[k] = "anyadida"
    return "\n".join(lineas) + "\n", estado


def huella(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:12]


def main() -> int:
    ruta = Path(sys.argv[1])
    nuevas = leer(sys.stdin.read())
    texto, estado = fusionar(ruta.read_text(encoding="utf-8"), nuevas)
    tmp = ruta.with_name(ruta.name + ".nuevo")
    # Nace con 600 (revision del 16/10: con write_text + chmod habia un instante legible por otros).
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)
    escritas = leer(ruta.read_text(encoding="utf-8"))
    for k in nuevas:
        print(f"{k}: {estado[k]}, huella {huella(escritas[k])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
