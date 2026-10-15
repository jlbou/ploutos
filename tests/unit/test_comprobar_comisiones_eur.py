"""La comprobacion de las comisiones contra euro (paso 2, V2): solo con una clave de lectura, sin red."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "comprobar_comisiones_eur.py"
spec = importlib.util.spec_from_file_location("comprobar_comisiones_eur", RUTA)
cc = importlib.util.module_from_spec(spec)
sys.modules["comprobar_comisiones_eur"] = cc
spec.loader.exec_module(cc)


def test_solo_vale_una_clave_de_lectura():
    assert cc.solo_lectura(cc.permisos({"data": [{"perm": "read_only"}]}))
    assert not cc.solo_lectura(cc.permisos({"data": [{"perm": "read_only,trade"}]}))
    assert not cc.solo_lectura(cc.permisos({"data": [{"perm": "read_only,withdraw"}]}))
    assert not cc.solo_lectura(cc.permisos({}))


def test_ensenya_los_campos_tal_cual_y_el_grupo():
    r = {"data": [{"maker": "-0.001", "taker": "-0.002", "makerUSDC": "", "level": "Lv1",
                   "feeGroup": [{"groupId": "1", "maker": "-0.0008", "taker": "-0.001"}]}]}
    c = cc.campos(r)
    assert c["maker"] == "-0.001" and c["taker"] == "-0.002" and "makerUSDC" not in c and "level" not in c
    assert c["feeGroup"] == [{"groupId": "1", "maker": "-0.0008", "taker": "-0.001"}]
    assert abs(cc.pct("-0.002") - 0.2) < 1e-12 and cc.pct("") is None
