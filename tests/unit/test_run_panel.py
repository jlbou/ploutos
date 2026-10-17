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


# --- Hueco S5 (DNS rebinding): el panel solo contesta a su propio nombre (api/guardia.py) ---

def _estado(nombre):
    salida = '{"Self": {"DNSName": "%s", "HostName": "x"}}' % nombre
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=salida, stderr="")


def test_los_nombres_del_panel_salen_de_tailscale():
    """IP:puerto, el nombre de MagicDNS y el corto: los tres con los que se entra. Nada escrito en el repositorio."""
    hosts = rp.hosts_permitidos("100.70.1.2", 8765, _run=_estado("Ploutos.ejemplo.ts.net."))
    assert hosts == {"100.70.1.2:8765", "ploutos.ejemplo.ts.net:8765", "ploutos:8765"}


def test_sin_nombre_de_tailscale_solo_por_ip():
    for run in (_estado(""), _estado("algo.otra-cosa.com.")):
        assert rp.hosts_permitidos("100.70.1.2", 8765, _run=run) == {"100.70.1.2:8765"}

    def roto(*a, **k):
        raise FileNotFoundError("tailscale")
    assert rp.hosts_permitidos("100.70.1.2", 8765, _run=roto) == {"100.70.1.2:8765"}


def test_en_la_propia_maquina_ip_y_localhost():
    def nunca(*a, **k):
        raise AssertionError("en local no se pregunta a Tailscale")
    assert rp.hosts_permitidos("127.0.0.1", 8765, _run=nunca) == {"127.0.0.1:8765", "localhost:8765"}


def test_el_servicio_arranca_con_el_cierre_puesto():
    """Enchufado: main() le pasa los nombres a crear_app (si no, el cierre existiria y no se usaria)."""
    texto = SCRIPT.read_text(encoding="utf-8")
    assert "hosts=hosts_permitidos(" in texto
