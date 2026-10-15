"""El repositorio se construye para ser PUBLICO (decision del propietario del 15/10/2026): en git no puede haber su
nombre, su correo, el proveedor ni el nombre de Tailscale del VPS, ni rutas de su ordenador. Lo personal va en
`CLAUDE.local.md` (fuera de git). Este test mira TODO lo que esta en git, no solo el codigo."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ESTE = "tests/unit/test_sin_datos_personales.py"
# Las marcas de la copia publica del 07/10 y alguna mas. "journal" no cuenta.
MARCAS = re.compile(r"(?<![a-z])jou(?!rnal)|Jou(?!rnal)|JOU(?!RNAL)|taila2be4f|netcup|Nuremberg|Projectes|joel|"
                    r"leon06|gmail|v2202609425045526619", re.IGNORECASE)
BINARIOS = {".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".ttf", ".gz", ".db", ".pdf"}


def _en_git() -> list[str]:
    salida = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    return [f for f in salida.decode("utf-8").split("\0") if f]


def test_lo_personal_no_esta_en_git():
    assert "CLAUDE.local.md" not in _en_git(), "lo personal va fuera de git"


def test_ningun_fichero_de_git_tiene_datos_personales():
    malos = []
    for f in _en_git():
        if f == ESTE or Path(f).suffix.lower() in BINARIOS or not (REPO / f).is_file():
            continue
        texto = (REPO / f).read_bytes().decode("utf-8", errors="ignore")
        for n, linea in enumerate(texto.splitlines(), 1):
            if MARCAS.search(linea):
                malos.append(f"{f}:{n}: {linea.strip()[:100]}")
    assert not malos, f"{len(malos)} lineas con datos personales; las primeras:\n" + "\n".join(malos[:20])
