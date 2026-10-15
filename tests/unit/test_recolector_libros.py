"""El recolector de libros (V5) y su juez, sin red."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

S = Path(__file__).resolve().parents[2] / "scripts"


def _cargar(n):
    spec = importlib.util.spec_from_file_location(n, S / f"{n}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[n] = m
    spec.loader.exec_module(m)
    return m


rl = _cargar("recolector_libros")
cl = _cargar("check_libros")
H = 3600_000
AHORA = int(datetime(2026, 10, 20, 12, tzinfo=UTC).timestamp() * 1000)


def test_guarda_solo_precio_y_cantidad():
    d = json.loads(rl.linea("BTC-EUR", 1, {"ts": "5", "asks": [["10", "2", "0", "1"]], "bids": [["9", "3", "0", "2"]]}))
    assert d == {"par": "BTC-EUR", "ms": 1, "ts_libro": 5, "asks": [[10.0, 2.0]], "bids": [[9.0, 3.0]]}


def test_se_para_solo_al_final():
    assert not rl.terminado(datetime(2026, 10, 29, 23, tzinfo=UTC))
    assert rl.terminado(datetime(2026, 10, 30, 0, tzinfo=UTC))


def test_el_juez_cada_hora_esta_bien_y_un_hueco_falla():
    bien = [(p, AHORA - i * H) for p in rl.PARES for i in range(24)]
    assert cl.juzgar(bien, AHORA)[0] == 0
    hueco = [(p, ms) for p, ms in bien if not (p == "ETH-EUR" and ms > AHORA - 3 * H)]
    codigo, texto = cl.juzgar(hueco, AHORA)
    assert codigo == 1 and "ETH-EUR" in texto
    assert cl.juzgar([], AHORA)[0] == 2


def test_el_primer_dia_no_da_falla_por_llevar_poco():
    """16/10: a los pocos minutos de arrancar pedia 20 libros en 24 h y daba FALLA (aviso falso a las 00:30)."""
    recien = [(p, AHORA - 10 * 60_000) for p in rl.PARES]
    assert cl.juzgar(recien, AHORA)[0] == 0
    tres_horas = [(p, AHORA - i * H) for p in rl.PARES for i in range(3)]
    assert cl.juzgar(tres_horas, AHORA)[0] == 0
    # 10 h desde el primero y solo 2 libros (el ultimo reciente): falta casi todo -> FALLA
    pocos = [(p, ms) for p in rl.PARES for ms in (AHORA - 10 * H, AHORA - H)]
    assert cl.juzgar(pocos, AHORA)[0] == 1
