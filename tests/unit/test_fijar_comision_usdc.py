"""La comision del spot en USDC en el demo (scripts/fijar_comision_usdc.py), con un OKX falso: ni red ni claves."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fijar_comision_usdc.py"
_spec = importlib.util.spec_from_file_location("fijar_comision_usdc", SCRIPT)
fc = importlib.util.module_from_spec(_spec)
sys.modules["fijar_comision_usdc"] = fc
_spec.loader.exec_module(fc)


class OkxFalso:
    def __init__(self, fee_type="0", acepta=True, cambia=True):
        self.fee_type, self.acepta, self.cambia, self.pedidos = fee_type, acepta, cambia, []

    async def private_get_account_config(self):
        return {"code": "0", "data": [{"feeType": self.fee_type, "acctLv": "1"}]}

    async def private_post_account_set_fee_type(self, params):
        self.pedidos.append(params)
        if not self.acepta:
            return {"code": "51000", "msg": "Parameter error"}
        if self.cambia:
            self.fee_type = params["feeType"]
        return {"code": "0", "data": [{"feeType": params["feeType"]}]}


def test_sin_aplicar_solo_lee(capsys):
    okx = OkxFalso()
    assert asyncio.run(fc.fijar(okx, aplicar=False)) == 0
    assert okx.pedidos == [] and "Sin --aplicar" in capsys.readouterr().out


def test_aplicar_cambia_a_usdc_y_lo_comprueba(capsys):
    okx = OkxFalso()
    assert asyncio.run(fc.fijar(okx, aplicar=True)) == 0
    assert okx.pedidos == [{"feeType": "1"}] and okx.fee_type == "1"
    assert "Hecho" in capsys.readouterr().out


def test_si_ya_esta_en_usdc_no_se_pide_nada():
    okx = OkxFalso(fee_type="1")
    assert asyncio.run(fc.fijar(okx, aplicar=True)) == 0 and okx.pedidos == []


def test_si_okx_lo_rechaza_o_no_cambia_es_un_fallo(capsys):
    assert asyncio.run(fc.fijar(OkxFalso(acepta=False), aplicar=True)) == 1
    assert asyncio.run(fc.fijar(OkxFalso(cambia=False), aplicar=True)) == 1
    assert "FALLA" in capsys.readouterr().out


def test_lee_el_fee_type_aunque_la_respuesta_venga_rara():
    assert fc.fee_type_de({"data": [{"feeType": 1}]}) == "1"
    assert fc.fee_type_de({"data": []}) is None and fc.fee_type_de({}) is None
