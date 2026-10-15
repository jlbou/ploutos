"""La revision semanal de actualizaciones (scripts/revisar_actualizaciones.py): un aviso solo si hay algo.

Sin red: las versiones se pasan a mano; nada llama a PyPI ni manda un Telegram.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "revisar_actualizaciones.py"
_spec = importlib.util.spec_from_file_location("revisar_actualizaciones", SCRIPT)
ra = importlib.util.module_from_spec(_spec)
sys.modules["revisar_actualizaciones"] = ra
_spec.loader.exec_module(ra)

AL_DIA = {"ccxt": ("4.5.84", "4.5.84"), "fastapi": ("0.141.1", "0.141.1")}


def test_comparar_versiones():
    assert ra.mas_nueva("4.5.82", "4.5.84") and ra.mas_nueva("2.1.266", "2.1.274")
    assert not ra.mas_nueva("4.5.84", "4.5.84") and not ra.mas_nueva("4.5.84", "4.5.9")
    assert ra.mas_nueva("0.9.9", "0.10.0")          # 10 > 9, no texto


def test_si_no_hay_nada_nuevo_no_se_manda_nada():
    assert ra.mensaje(tailscale=("1.102.4", "1.102.4"), librerias=AL_DIA, ia=("2.1.266", "2.1.266"),
                      ubuntu=[]) is None


def test_lo_nuevo_se_avisa_y_tailscale_se_cuenta_como_instalado():
    texto = ra.mensaje(tailscale=("1.102.4", "1.104.0"),
                       librerias={**AL_DIA, "ccxt": ("4.5.82", "4.5.84")}, ia=("2.1.266", "2.1.274"),
                       ubuntu=["libfoo", "bar"])
    assert "Instalado solo" in texto and "1.102.4 → 1.104.0" in texto
    assert "ccxt 4.5.82 → 4.5.84" in texto and "fastapi" not in texto
    assert "el programa de la IA 2.1.266 → 2.1.274" in texto
    assert "2 paquete(s)" in texto
    assert "claude" not in texto.lower()


def test_una_version_que_no_se_pudo_leer_no_se_inventa():
    assert ra.mensaje(tailscale=None, librerias={"ccxt": ("4.5.82", None)}, ia=("2.1.266", None),
                      ubuntu=[]) is None


def test_ubuntu_pendientes_sin_tailscale_ni_cabecera():
    salida = "Listing... Done\nlibexpat1/noble-updates 2.6.1 amd64 [upgradable from: 2.6.0]\n" \
             "tailscale/unknown 1.104.0 amd64 [upgradable from: 1.102.4]\n"
    ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=salida, stderr="")  # noqa: E731
    assert ra.ubuntu_pendientes(_run=ok) == ["libexpat1"]


def test_el_script_del_sistema_solo_instala_tailscale_y_sin_reiniciar_el_bot():
    sh = (Path(__file__).resolve().parents[2] / "deploy" / "actualizar-semanal.sh").read_text(encoding="utf-8")
    instalaciones = [l for l in sh.splitlines() if "apt-get install" in l]
    assert len(instalaciones) == 1 and "--only-upgrade tailscale" in instalaciones[0]
    assert "NEEDRESTART_SUSPEND=1" in instalaciones[0]
    assert "pip install" not in sh
