"""La llamada a `claude -p` (pieza 6 del plan de la fase 3).

Todo lo que se sabe de la invocacion esta MEDIDO (docs/hallazgos-claude-cli.md):
- `--json-schema` recibe el esquema EN LINEA; `--append-system-prompt` en linea
  (`--append-system-prompt-file` no existe).
- Las herramientas vienen ENCENDIDAS: `--restricted` y compania las apagan. Un
  analista que puede ejecutar Bash puede hacer cosas, y el PRD seccion 6 dice que
  la IA opina, no hace.
- `< /dev/null`, desde `claude_runtime/` (vacio), sin sesiones persistentes.
- La salida parseada viene en `structured_output`.

REGLA 19: LA IA NUNCA VE CLAVES NI VARIABLES DE ENTORNO. El entorno del proceso
de Claude NO se hereda y se filtra: se CONSTRUYE desde cero con una lista cerrada.
Motivo concreto: `ploutos-ingest.service` carga `.env` como variables de entorno
(`EnvironmentFile=`), asi que las claves de OKX viven en ese proceso. Un hijo que
heredase el entorno se las llevaria. Aqui solo entra lo que Node necesita para
arrancar, un directorio de configuracion propio y el token de Claude.

El directorio de configuracion propio (`CLAUDE_CONFIG_DIR`, `HOME`) hace que el CLI
no use la sesion ni los ajustes personales de nadie: en el portatil se comporta
como en el VPS (verificado el 22/09/2026 con `verify_claude_cli.py --sin-sesion`).

A 22/09/2026 esto NO lo llama ningun servicio (test de arquitectura). Lo usa
`scripts/dry_run_analyst.py`, la prueba en seco autorizada por el propietario.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.contract import SCHEMA_JSON
from ai.parser import ParseResult, parse
from ai.prompt import SYSTEM_PROMPT, candidate_ids, position_ids, render
from ai.quota import CallOutcome, Classification, classify

REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "claude_runtime"

# La version del CLI con la que se verificaron los flags, el coste y el contrato
# (docs/hallazgos-claude-cli.md). `deploy/install-claude.sh` instala ESTA (hay test).
# Cambiarla = volver a pasar `scripts/verify_claude_cli.py` y la prueba en seco.
VERIFIED_VERSION = "2.1.266"

# Sin actualizaciones: la instalacion nativa se actualiza sola en segundo plano, y
# un CLI que cambia por su cuenta invalida lo verificado (en 2.1.266 ya faltaban
# flags que el informe daba por hechos). Va en el ENTORNO porque con
# `--setting-sources ''` no se lee ningun settings.json. `DISABLE_UPDATES` corta
# tambien `claude update`; `DISABLE_AUTOUPDATER`, la comprobacion de fondo.
SIN_ACTUALIZACIONES = {"DISABLE_UPDATES": "1", "DISABLE_AUTOUPDATER": "1"}

# Lo unico que se hereda del entorno del padre, y solo si existe. Es lo que Node y
# el CLI necesitan para arrancar en Linux y en Windows. Nada con "KEY", "SECRET",
# "TOKEN" ni "PASS" en el nombre: lo comprueba un test.
ENV_HEREDABLE = (
    "PATH", "LANG", "LC_ALL", "TZ",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMDATA",
)

FLAGS = (
    "--output-format", "json",
    "--no-session-persistence",
    "--restricted",
    "--disable-slash-commands",
    "--strict-mcp-config",
    "--setting-sources", "",
)


def build_env(token: str, config_dir: Path) -> dict[str, str]:
    """El entorno COMPLETO del proceso de Claude. Construido, no filtrado."""
    env = {k: os.environ[k] for k in ENV_HEREDABLE if k in os.environ}
    for clave in ("CLAUDE_CONFIG_DIR", "HOME", "USERPROFILE"):
        env[clave] = str(config_dir)
    env.update(SIN_ACTUALIZACIONES)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def build_command(claude_bin: str, prompt: str, model: str) -> list[str]:
    return [
        claude_bin, "-p", prompt,
        "--json-schema", SCHEMA_JSON,
        "--append-system-prompt", SYSTEM_PROMPT,
        "--model", model,
        *FLAGS,
    ]


def _run_claude(
    args: list[str], *, token: str, config_dir: Path, timeout_s: float, _run: Any,
) -> Classification:
    """La UNICA forma de lanzar el CLI: la usan la llamada y la sonda.

    Una sola copia de lo delicado (el entorno cerrado de la regla 19, el
    directorio vacio, stdin cerrado, que fallos cuentan como que) para que un
    arreglo no llegue a una y no a la otra (revision del 23/09/2026). Nunca lanza.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        proc = _run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, cwd=RUNTIME, stdin=subprocess.DEVNULL,
            env=build_env(token, config_dir),
        )
        return classify(proc.returncode, proc.stdout, proc.stderr, secret=token)
    except subprocess.TimeoutExpired:
        return classify(None, "", timed_out=True)
    except OSError as exc:
        return classify(1, "", f"{type(exc).__name__}: {exc}", secret=token)


@dataclass(frozen=True, slots=True)
class AnalystCall:
    """Una llamada, con todo lo que hay que registrar (plan de la fase 3, pieza 8)."""

    outcome: CallOutcome
    parsed: ParseResult
    latency_s: float
    detail: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_created: int | None = None
    cost_usd_equiv: float | None = None
    num_turns: int | None = None
    # Lo que devolvio el modelo, tal cual, para el journal y para depurar: sin
    # esto, una salida invalida no se puede explicar despues.
    structured: Any = None
    result_text: str = ""
    # El modelo que respondio de verdad (`modelUsage` del sobre), si el CLI lo dice.
    # `model: sonnet` es un alias: sin esto no se sabria si cambio por debajo.
    modelo: str | None = None


def _num(sobre: dict[str, Any] | None, *ruta: str) -> Any:
    x: Any = sobre or {}
    for r in ruta:
        x = x.get(r) if isinstance(x, dict) else None
    return x


def _modelos(sobre: dict[str, Any] | None) -> str | None:
    """Los modelos que usaron la llamada, ordenados; None si el sobre no lo dice."""
    uso = _num(sobre, "modelUsage")
    if not isinstance(uso, dict) or not uso:
        return None
    return ",".join(sorted(str(m) for m in uso))[:200]


def call_analyst(
    entrada: dict[str, Any],
    *,
    token: str,
    config_dir: Path,
    model: str = "sonnet",
    timeout_s: float = 90.0,
    claude_bin: str | None = None,
    _run: Any = subprocess.run,      # los tests lo sustituyen: nada de red en un test
) -> AnalystCall:
    """Llama al analista UNA vez. Nunca lanza: todo fallo es "no hacer nada".

    El presupuesto de la regla 18 NO se mira aqui: lo apunta quien llama, con
    `CallBudget.try_acquire`, ANTES de llamar.
    """
    cids = candidate_ids(entrada)
    pids = position_ids(entrada)
    binario = claude_bin or shutil.which("claude")
    if binario is None:
        return AnalystCall(CallOutcome.ERROR, ParseResult.invalid("claude no instalado", cids),
                           0.0, "no se encuentra el binario de claude")
    inicio = time.monotonic()
    clasif = _run_claude(build_command(binario, render(entrada), model),
                         token=token, config_dir=config_dir, timeout_s=timeout_s, _run=_run)
    latencia = time.monotonic() - inicio

    sobre = clasif.envelope
    if clasif.outcome is CallOutcome.OK:
        resultado = parse(_num(sobre, "structured_output"), cids, pids)
    else:
        resultado = ParseResult.invalid(f"llamada fallida: {clasif.outcome.value}", cids)
    return AnalystCall(
        outcome=clasif.outcome,
        parsed=resultado,
        latency_s=latencia,
        detail=clasif.detail,
        input_tokens=_num(sobre, "usage", "input_tokens"),
        output_tokens=_num(sobre, "usage", "output_tokens"),
        cache_created=_num(sobre, "usage", "cache_creation_input_tokens"),
        cost_usd_equiv=_num(sobre, "total_cost_usd"),
        num_turns=_num(sobre, "num_turns"),
        structured=_num(sobre, "structured_output"),
        result_text=str(_num(sobre, "result") or "")[:4000],
        modelo=_modelos(sobre),
    )


def summary(call: AnalystCall) -> str:
    return json.dumps({
        "outcome": call.outcome.value, "ok": call.parsed.ok, "detalle": call.parsed.reason,
        "latencia_s": round(call.latency_s, 1), "coste": call.cost_usd_equiv,
    }, ensure_ascii=False)


# La sonda de CLOSE_ONLY_QUOTA (informe seccion 3.1): lo mas barato que demuestra
# que Claude responde. Sin esquema ni prompt de sistema: solo importa si contesta.
PROBE_PROMPT = "Responde solo: ok"


def probe_claude(
    *, token: str, config_dir: Path, model: str = "sonnet", timeout_s: float = 60.0,
    claude_bin: str | None = None, _run: Any = subprocess.run,
) -> Classification:
    """Una sonda. Nunca lanza. Cuenta como llamada para la regla 18: quien la
    lance tiene que pasar antes por `CallBudget.try_acquire(kind="probe")`."""
    binario = claude_bin or shutil.which("claude")
    if binario is None:
        return classify(1, "", "no se encuentra el binario de claude")
    return _run_claude([binario, "-p", PROBE_PROMPT, "--model", model, *FLAGS],
                       token=token, config_dir=config_dir, timeout_s=timeout_s, _run=_run)
