"""La copia de claves del `.env` al VPS (15/10/2026): solo las nombradas, sin tocar el resto, sin valores vacios."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import env_fusionar as ef  # noqa: E402

ACTUAL = "# comentario\nA=1\nHEALTHCHECK_INGESTA=http://x\nB=2\n"


def test_cambia_en_su_sitio_anyade_al_final_y_no_toca_lo_demas():
    texto, estado = ef.fusionar(ACTUAL, {"B": "3", "C": "4", "A": "1"})
    assert texto == "# comentario\nA=1\nHEALTHCHECK_INGESTA=http://x\nB=3\nC=4\n"
    assert estado == {"A": "igual", "B": "cambiada", "C": "anyadida"}


def test_nunca_vacia_ni_la_del_portatil_ni_un_nombre_raro():
    for mala in ({"B": ""}, {"HEALTHCHECK_COPIA_PORTATIL": "u"}, {"b c": "1"}):
        with pytest.raises(ValueError):
            ef.fusionar(ACTUAL, mala)


def test_la_huella_no_es_el_valor():
    assert ef.huella("secreto") != "secreto" and len(ef.huella("secreto")) == 12
