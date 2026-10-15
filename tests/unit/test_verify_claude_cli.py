"""El entorno "sin sesion" de `scripts/verify_claude_cli.py`.

Si este entorno deja pasar una sola variable del host, la prueba del token
puede dar "funciona" usando credenciales que no son las del `.env`, y el fallo
aparece el dia que la fase 3 arranca en el VPS.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_claude_cli.py"
_spec = importlib.util.spec_from_file_location("verify_claude_cli", SCRIPT)
vcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vcc)


@pytest.fixture
def host(monkeypatch):
    """Un entorno como el de una sesion lanzada desde la app de escritorio."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://host.local")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-del-host")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token-del-host")
    monkeypatch.setenv("claude_code_entrypoint", "desktop")
    monkeypatch.setenv("PATH_DE_PRUEBA", "se-queda")


def test_quita_todo_lo_de_claude_y_anthropic(host, tmp_path):
    env = vcc.entorno_limpio(tmp_path)
    heredadas = [k for k in env if k.upper().startswith(("CLAUDE", "ANTHROPIC"))
                 and k != "CLAUDE_CONFIG_DIR"]
    assert heredadas == []
    assert env["PATH_DE_PRUEBA"] == "se-queda"


def test_la_configuracion_y_la_casa_apuntan_al_directorio_vacio(host, tmp_path):
    env = vcc.entorno_limpio(tmp_path)
    for clave in ("CLAUDE_CONFIG_DIR", "HOME", "USERPROFILE"):
        assert env[clave] == str(tmp_path)


def test_sin_token_no_hay_token(host, tmp_path):
    # El control tiene que ir sin NINGUN token, tampoco el del host.
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in vcc.entorno_limpio(tmp_path)


def test_con_token_va_el_del_env_y_no_el_del_host(host, tmp_path):
    env = vcc.entorno_limpio(tmp_path, token="token-del-env")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "token-del-env"


def test_tapar_nunca_deja_el_secreto():
    assert vcc.tapar("error con sk-ant-XYZ dentro", "sk-ant-XYZ") == "error con *** dentro"
    assert vcc.tapar(None, "sk-ant-XYZ") == ""
    assert vcc.tapar("sin secreto", None) == "sin secreto"
