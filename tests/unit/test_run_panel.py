"""El panel solo escucha en Tailscale (scripts/run_panel.py; decision del propietario del 25/09)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_panel.py"
_spec = importlib.util.spec_from_file_location("run_panel", SCRIPT)
rp = importlib.util.module_from_spec(_spec)
sys.modules["run_panel"] = rp
_spec.loader.exec_module(rp)


@pytest.mark.parametrize("host", ["100.101.102.103", "100.64.0.1", "127.0.0.1"])
def test_solo_tailscale_o_la_propia_maquina(host):
    assert rp.comprobar(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "203.0.113.7", "192.168.1.10", "::", "ploutos", ""])
def test_nunca_todas_ni_una_publica(host):
    with pytest.raises(rp.SinTailscale):
        rp.comprobar(host)


def test_la_ip_sale_de_tailscale():
    ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="100.70.1.2\nfd7a::1\n", stderr="")  # noqa: E731
    assert rp.ip_de_tailscale(_run=ok) == "100.70.1.2"


def test_sin_tailscale_no_arranca():
    parado = lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="Tailscale is stopped.")  # noqa: E731
    with pytest.raises(rp.SinTailscale):
        rp.ip_de_tailscale(_run=parado)

    def no_instalado(*a, **k):
        raise FileNotFoundError("tailscale")
    with pytest.raises(rp.SinTailscale):
        rp.ip_de_tailscale(_run=no_instalado)


def test_el_servicio_no_pone_otra_ip():
    """El servicio arranca sin --host: la IP la decide Tailscale, no una linea que alguien cambie."""
    unidad = (Path(__file__).resolve().parents[2] / "deploy" / "ploutos-panel.service").read_text(encoding="utf-8")
    exec_start = next(l for l in unidad.splitlines() if l.startswith("ExecStart="))
    assert "--host" not in exec_start and "0.0.0.0" not in unidad
