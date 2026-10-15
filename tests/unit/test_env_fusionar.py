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


def test_el_temporal_nace_con_permisos_600(tmp_path, monkeypatch):
    """Revision del 16/10: con write_text + chmod habia un instante legible por otros."""
    import io
    import os
    import stat
    ruta = tmp_path / ".env"
    ruta.write_text("A=1\n", encoding="utf-8")
    vistos = []
    real = os.replace

    def espia(origen, destino):
        if os.name != "nt":
            vistos.append(stat.S_IMODE(os.stat(origen).st_mode))
        real(origen, destino)

    monkeypatch.setattr(os, "replace", espia)
    monkeypatch.setattr(sys, "argv", ["x", str(ruta)])
    monkeypatch.setattr(sys, "stdin", io.StringIO("B=2\n"))
    assert ef.main() == 0
    assert ruta.read_text(encoding="utf-8") == "A=1\nB=2\n"
    assert all(m == 0o600 for m in vistos)
