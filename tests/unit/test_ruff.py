"""El revisor de codigo (ruff) sin nada que decir (decision del propietario del 25/09/2026).

Solo errores probables (E9, F, B; ver `[tool.ruff]` en pyproject.toml), sin formato. Como un
test mas, para que no dependa de acordarse de pasarlo. Ruff solo esta en el portatil (extra
`dev`): donde no esta (el VPS), el test se salta y lo dice.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(importlib.util.find_spec("ruff") is None,
                    reason="ruff no esta instalado (solo va en el portatil: pip install -e .[dev])")
def test_ruff_no_encuentra_nada():
    r = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."],
                       cwd=RAIZ, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, "ruff ha encontrado errores probables:\n" + r.stdout + r.stderr
