"""El calculo de V5 (plan, seccion 13; aclaracion 3): percentil 90 del coste de 10.000 € a mercado, el par mas caro.
Escritos ANTES del codigo, con libros inventados."""

from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2" / "calcular_v5.py"
spec = importlib.util.spec_from_file_location("calcular_v5", RUTA)
v5 = importlib.util.module_from_spec(spec)
sys.modules["calcular_v5"] = v5
spec.loader.exec_module(v5)


def test_coste_de_una_orden_que_recorre_el_libro():
    asks = [[100.0, 50.0], [101.0, 100.0]]           # 5.000 € a 100 y el resto a 101
    bids = [[99.0, 200.0]]
    mid = (100.0 + 99.0) / 2
    compra = v5.coste(asks, 10_000, mid)
    q = 50.0 + 5_000 / 101.0
    assert math.isclose(compra, (10_000 / q) / mid - 1, rel_tol=1e-12)
    assert math.isclose(v5.coste(bids, 10_000, mid), 1 - 99.0 / mid, rel_tol=1e-12)
    assert v5.coste([[100.0, 1.0]], 10_000, mid) is None              # sin profundidad


def test_percentil_90_y_el_par_mas_caro(tmp_path):
    db = tmp_path / "libros.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE libros (par TEXT, ms INTEGER, ts_libro INTEGER, asks TEXT, bids TEXT)")
    for i in range(10):
        ancho = 0.01 * (i + 1)                         # 0,01 .. 0,10 puntos de spread
        for par, factor in (("BTC-EUR", 1.0), ("ETH-EUR", 2.0)):
            a, b = 100.0 + ancho * factor, 100.0 - ancho * factor
            c.execute("INSERT INTO libros VALUES (?, ?, 0, ?, ?)", (par, i, json.dumps([[a, 1e6]]), json.dumps([[b, 1e6]])))
    c.commit()
    c.close()
    r = v5.calcular(db)
    assert r["pares"]["ETH-EUR"]["p90"] > r["pares"]["BTC-EUR"]["p90"]
    assert r["deslizamiento_por_lado"] == r["pares"]["ETH-EUR"]["p90"]
    assert r["pares"]["BTC-EUR"]["sin_profundidad"] == 0


def test_no_corre_antes_del_final_del_recolector(tmp_path):
    with pytest.raises(PermissionError, match="30"):
        v5.comprobar_fecha(datetime(2026, 10, 29, 23, tzinfo=UTC))
    v5.comprobar_fecha(datetime(2026, 10, 30, 1, tzinfo=UTC))
