"""La llamada a claude -p (`ai/invoke.py`), sin red y sin claude de verdad."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime


from ai.contract import SCHEMA_JSON
from ai.invoke import (
    ENV_HEREDABLE, FLAGS, REPO, VERIFIED_VERSION, build_command, build_env, call_analyst,
)
from ai.prompt import SYSTEM_PROMPT, LimitsView, build_input
from ai.quota import CallOutcome
from features.regime import Regime
from strategy.candidates import Candidate, make_decision_id

NOW = datetime(2026, 9, 22, 16, tzinfo=UTC)
TOKEN = "sk-ant-oat01-TOKEN-FALSO-DE-PRUEBA"


def entrada():
    ts = int(NOW.timestamp() * 1000)
    did = make_decision_id("TRX/USDC", "pullback_trend", ts)
    c = Candidate(cid=did, decision_id=did, symbol="TRX/USDC", setup="pullback_trend",
                  timeframe="4h", entry=0.3416, stop=0.33765, target=0.36148,
                  reward_risk=5.03, cost_rt_pct=0.269, spread_pct=0.02,
                  regime=Regime.TREND_UP, bar_ts_ms=ts, created_at=NOW)
    return build_input(now=NOW, mode="NORMAL", equity_usd=50, free_quote_usd=50,
                       positions=[], limits=LimitsView(3, 3, 0.5, 3.0, 6), candidates=[c])


class FakeRun:
    """Hace de subprocess.run y apunta con que se le llamo."""

    def __init__(self, stdout="", returncode=0, stderr="", timeout=False):
        self.stdout, self.returncode, self.stderr, self.timeout = stdout, returncode, stderr, timeout
        self.kwargs = None
        self.args = None

    def __call__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        if self.timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


def sobre(structured, **kw):
    base = {"type": "result", "is_error": False, "result": "", "num_turns": 2,
            "total_cost_usd": 0.0745, "structured_output": structured,
            "usage": {"input_tokens": 2, "output_tokens": 567,
                      "cache_creation_input_tokens": 16919}}
    base.update(kw)
    return json.dumps(base)


def llamar(fake, tmp_path):
    return call_analyst(entrada(), token=TOKEN, config_dir=tmp_path / "home",
                        claude_bin="claude", _run=fake)


# --------------------------------------------------------------------------
# Regla 19: el entorno se CONSTRUYE, no se hereda
# --------------------------------------------------------------------------


def test_el_entorno_no_lleva_ninguna_clave_del_padre(monkeypatch, tmp_path):
    monkeypatch.setenv("OKX_API_KEY", "clave-okx-falsa")
    monkeypatch.setenv("OKX_API_SECRET", "secreto-okx-falso")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-falso")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://host.local")
    env = build_env(TOKEN, tmp_path)
    assert not any(k.startswith(("OKX", "TELEGRAM", "ANTHROPIC")) for k in env)
    assert not {"clave-okx-falsa", "secreto-okx-falso", "telegram-falso"} & set(env.values())
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN


def test_la_lista_heredable_no_tiene_nada_con_pinta_de_secreto():
    for nombre in ENV_HEREDABLE:
        assert not any(p in nombre for p in ("KEY", "SECRET", "TOKEN", "PASS")), nombre


def test_el_cli_no_se_actualiza_solo(tmp_path):
    """Un CLI que cambia por su cuenta invalida lo verificado. Tiene que ir en el
    entorno: con `--setting-sources ''` no se lee ningun settings.json."""
    env = build_env(TOKEN, tmp_path)
    assert env["DISABLE_UPDATES"] == env["DISABLE_AUTOUPDATER"] == "1"
    assert "--setting-sources" in FLAGS


def test_el_instalador_del_vps_pone_la_version_verificada():
    script = (REPO / "deploy" / "install-claude.sh").read_text(encoding="utf-8")
    assert f'CLAUDE_VERSION="{VERIFIED_VERSION}"' in script


def test_el_instalador_no_se_bloquea_a_si_mismo():
    """Con DISABLE_UPDATES el instalador no instala NADA y aun asi dice "Installation complete"
    (despliegue del 25/09). Esa variable va en la llamada del bot, no en la instalacion."""
    script = (REPO / "deploy" / "install-claude.sh").read_text(encoding="utf-8")
    llamada = next(l for l in script.splitlines() if 'bash "${TMP}/install.sh"' in l)
    previa = script.splitlines()[script.splitlines().index(llamada) - 1]
    assert "DISABLE_UPDATES" not in llamada + previa


def test_la_config_y_la_casa_son_propias(tmp_path):
    env = build_env(TOKEN, tmp_path)
    assert env["CLAUDE_CONFIG_DIR"] == env["HOME"] == env["USERPROFILE"] == str(tmp_path)


def test_el_proceso_recibe_ese_entorno_y_no_otro(monkeypatch, tmp_path):
    monkeypatch.setenv("OKX_API_KEY", "clave-okx-falsa")
    fake = FakeRun(sobre({"decisions": [], "market_read": "."}))
    llamar(fake, tmp_path)
    assert "OKX_API_KEY" not in fake.kwargs["env"]
    assert fake.kwargs["stdin"] is subprocess.DEVNULL
    assert str(fake.kwargs["cwd"]).endswith("claude_runtime")


# --------------------------------------------------------------------------
# Los flags medidos
# --------------------------------------------------------------------------


def test_el_comando_lleva_los_flags_verificados():
    cmd = build_command("claude", "PROMPT", "sonnet")
    assert cmd[:3] == ["claude", "-p", "PROMPT"]
    assert cmd[cmd.index("--json-schema") + 1] == SCHEMA_JSON, "en linea, no una ruta"
    assert cmd[cmd.index("--append-system-prompt") + 1] == SYSTEM_PROMPT
    for flag in ("--restricted", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in cmd
    assert "--max-turns" not in cmd and "--append-system-prompt-file" not in cmd
    assert "--bare" not in cmd, "con --bare no se lee el token de la suscripcion"
    assert set(FLAGS) <= set(cmd)


# --------------------------------------------------------------------------
# Todo acaba en un resultado, nunca en una excepcion
# --------------------------------------------------------------------------


def test_una_llamada_buena(tmp_path):
    cid = next(iter(entrada()["candidates"]))["cid"]
    fake = FakeRun(sobre({"decisions": [{"type": "open", "ref": cid, "confidence": 0.6,
                                         "size_multiplier": 0.8, "reasons": ["ok"]}],
                          "market_read": "."}))
    r = llamar(fake, tmp_path)
    assert r.outcome is CallOutcome.OK and r.parsed.ok
    assert r.parsed.opens[0].size_multiplier == 0.8
    assert (r.output_tokens, r.cache_created, r.cost_usd_equiv) == (567, 16919, 0.0745)


def test_un_cid_inventado_llega_como_invalida(tmp_path):
    fake = FakeRun(sobre({"decisions": [{"type": "open", "ref": "d-inventado",
                                         "confidence": 0.9, "reasons": ["x"]}],
                          "market_read": "."}))
    r = llamar(fake, tmp_path)
    assert r.outcome is CallOutcome.OK and not r.parsed.ok and r.parsed.opens == ()


def test_sin_login_es_auth(tmp_path):
    r = llamar(FakeRun(sobre(None, is_error=True, result="Not logged in · Please run /login"),
                       returncode=1), tmp_path)
    assert r.outcome is CallOutcome.AUTH and not r.parsed.ok


def test_el_timeout_no_revienta(tmp_path):
    r = llamar(FakeRun(timeout=True), tmp_path)
    assert r.outcome is CallOutcome.TIMEOUT and r.parsed.opens == ()


def test_sin_binario_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _n: None)
    r = call_analyst(entrada(), token=TOKEN, config_dir=tmp_path)
    assert r.outcome is CallOutcome.ERROR and not r.parsed.ok


def test_el_token_nunca_sale_en_el_detalle(tmp_path):
    r = llamar(FakeRun("", returncode=1, stderr=f"fallo con {TOKEN}"), tmp_path)
    assert TOKEN not in r.detail


# --------------------------------------------------------------------------
# El modelo que respondio (protocolo de la fase 6: tramos por camino de decision)
# --------------------------------------------------------------------------


def test_se_apunta_el_modelo_que_respondio_si_el_cli_lo_dice(tmp_path):
    uso = {"claude-sonnet-x": {"inputTokens": 2}, "claude-haiku-y": {"inputTokens": 1}}
    llamada = llamar(FakeRun(stdout=sobre({"decisions": []}, modelUsage=uso)), tmp_path)
    assert llamada.modelo == "claude-haiku-y,claude-sonnet-x"


def test_sin_model_usage_el_modelo_queda_vacio_y_no_rompe(tmp_path):
    llamada = llamar(FakeRun(stdout=sobre({"decisions": []})), tmp_path)
    assert llamada.modelo is None
    assert llamar(FakeRun(stdout=sobre({"decisions": []}, modelUsage="raro")), tmp_path).modelo is None
