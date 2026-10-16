"""La comprobacion de la cuenta real para operar en euros (16/10): sin red, solo como lee las respuestas."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(S))
spec = importlib.util.spec_from_file_location("comprobar_cuenta_eur", S / "comprobar_cuenta_eur.py")
cc = importlib.util.module_from_spec(spec)
sys.modules["comprobar_cuenta_eur"] = cc
spec.loader.exec_module(cc)


def test_un_par_disponible_y_uno_que_falta():
    inst = [{"instId": "BTC-EUR", "state": "live", "minSz": "0.0001", "baseCcy": "BTC", "tickSz": "0.1"}]
    assert "live" in cc.resumen_par(inst, "BTC-EUR") and "0.0001" in cc.resumen_par(inst, "BTC-EUR")
    assert "NO esta disponible" in cc.resumen_par(inst, "ETH-EUR")


def test_el_euro():
    assert "no aparece" in cc.resumen_euro([])
    assert "ingresar True" in cc.resumen_euro([{"ccy": "EUR", "chain": "SEPA", "canDep": True, "canWd": False}])
