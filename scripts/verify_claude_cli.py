"""Verifica que `claude -p` sirve para lo que la fase 3 necesita.

"Verificar, no suponer": el informe seccion 1.5 da por hechos flags y
comportamientos del CLI, y varios no son como dice. Esto lo comprueba contra el
binario de verdad en vez de contra la documentacion.

    .venv/Scripts/python.exe scripts/verify_claude_cli.py              # sin gastar cuota
    .venv/Scripts/python.exe scripts/verify_claude_cli.py --call       # UNA llamada real
    .venv/Scripts/python.exe scripts/verify_claude_cli.py --sin-sesion # idem, SIN la sesion

(En el VPS, `.venv/bin/python`. Con el python del sistema falla al importar
`pydantic`, y eso no es un problema del token.)

Por defecto NO llama a Claude: la regla 18 da 40 llamadas al dia y no tiene
sentido gastarlas en comprobar que existe un flag. Con `--call` hace una sola,
con el prompt mas pequenyo que sirve para algo.

`--sin-sesion` existe porque en el portatil el CLI usa la sesion iniciada
ANTES que el token del `.env`, asi que una llamada que funciona no demuestra
que el token valga. Lanza el CLI con un entorno limpio y un directorio de
configuracion vacio, que es lo que habra en el VPS. Primero hace un CONTROL sin
token, que tiene que fallar: si no falla, el CLI esta encontrando credenciales
en otro sitio y la prueba no demostraria nada.

Exit 0 = todo lo que la fase 3 necesita esta disponible.
Exit 1 = falta algo (se dice que).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Directorio vacio desde el que se invoca (informe seccion 1.5): si hubiera un
# CLAUDE.md o un .mcp.json, cada llamada cargaria contexto de mas y gastaria
# cuota (regla 18).
RUNTIME = REPO / "claude_runtime"

# Flags que el informe seccion 1.5 usa o menciona.
FLAGS_NECESARIOS = [
    "--json-schema",
    "--output-format",
    "--append-system-prompt",
    "--no-session-persistence",
    "--model",
]
FLAGS_UTILES = [
    "--restricted",
    "--disable-slash-commands",
    "--strict-mcp-config",
    "--setting-sources",
    "--disallowedTools",
    "--max-budget-usd",
]
# Flags que el informe da por hechos y NO existen.
FLAGS_INEXISTENTES = ["--max-turns", "--append-system-prompt-file"]

# Los flags con los que conviene llamar, y por que cada uno. Medido el
# 22/09/2026: sin ellos la llamada tardaba 26 s y usaba 3 turnos porque Claude
# se ponia a usar herramientas; con ellos, 8 s y 2 turnos.
FLAGS_RECOMENDADOS = [
    "--no-session-persistence",   # cada decision empieza limpia
    "--restricted",               # sin Bash, sin WebFetch: el analista no ejecuta nada
    "--disable-slash-commands",   # sin skills que carguen contexto
    "--strict-mcp-config",        # sin servidores MCP del usuario
    "--setting-sources", "",      # sin ajustes personales del propietario
]

ESQUEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["open", "skip"]},
                    "cid": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    # PRD seccion 6: la IA SOLO puede reducir el tamanyo.
                    "size_multiplier": {"type": "number", "minimum": 0.5, "maximum": 1.0},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "cid", "confidence", "size_multiplier", "reasons"],
                "additionalProperties": False,
            },
        },
        "market_read": {"type": "string", "maxLength": 300},
    },
    "required": ["decisions", "market_read"],
    "additionalProperties": False,
}

CID_REAL = "d-verificacion-1"
PROMPT = json.dumps(
    {
        "portfolio": {"equity": 50.0, "slots_free": 2},
        "limits": {"risk_per_trade_usd": 0.50, "max_positions": 3},
        "candidates": [
            {
                "cid": CID_REAL,
                "symbol": "TRX/USDC",
                "setup": "pullback_trend",
                "tf": "4h",
                "entry": 0.3416,
                "stop": 0.33765,
                "target": 0.36148,
                "rr": 5.03,
                "cost_rt_pct": 0.269,
                "regime": "trend_up",
                "features": {"rsi14": 48, "adx14": 46.8, "atr_pct": 0.51},
            }
        ],
    },
    separators=(",", ":"),
) + "\nElige entre los candidatos. Responde solo con el JSON del esquema."


def entorno_limpio(casa: str | Path, token: str | None = None) -> dict[str, str]:
    """El entorno con el que se lanza el CLI para que NO encuentre la sesion.

    Quita toda variable `CLAUDE*` y `ANTHROPIC*`: una sesion de Claude Code
    lanzada desde la app de escritorio hereda del host, entre otras,
    `ANTHROPIC_BASE_URL`, y medir con eso no es medir lo que habra en el VPS.
    La configuracion y la casa apuntan a un directorio vacio.

    El token solo se anyade si se pasa, y solo aqui, al entorno del proceso
    hijo: nunca a la linea de comandos, donde lo veria cualquiera con `ps`.
    """
    env = {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))
    }
    for clave in ("CLAUDE_CONFIG_DIR", "HOME", "USERPROFILE"):
        env[clave] = str(casa)
    if token is not None:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def tapar(texto: str | None, secreto: str | None) -> str:
    """Por si el CLI devolviera el token en un error: nunca llega a pantalla."""
    texto = texto or ""
    return texto.replace(secreto, "***") if secreto else texto


def seccion(titulo: str) -> None:
    print()
    print(titulo)
    print("-" * len(titulo))


def comprobar_binario() -> tuple[bool, str]:
    if shutil.which("claude") is None:
        return False, ""
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=30
        )
        return True, out.stdout.strip()
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def comprobar_flags(ayuda: str) -> list[str]:
    problemas = []
    seccion("Flags")
    for flag in FLAGS_NECESARIOS:
        existe = flag in ayuda
        print(f"   {'OK ' if existe else 'FALTA'}  {flag}")
        if not existe:
            problemas.append(f"falta el flag {flag}, que la fase 3 necesita")
    for flag in FLAGS_UTILES:
        print(f"   {'OK ' if flag in ayuda else '--'}   {flag}  (util, no critico)")
    for flag in FLAGS_INEXISTENTES:
        if flag in ayuda:
            print(f"   NUEVO  {flag} ahora SI existe (el informe lo daba por hecho)")
        else:
            print(f"   ---   {flag} no existe, como ya se sabia")
    return problemas


def comprobar_token() -> list[str]:
    """Mira el token del `.env`, no el del entorno ni el de la sesion.

    ESTA COMPROBACION EXISTE POR UN FALLO REAL (22/09/2026): el token del
    `.env` tenia un ESPACIO en mitad de la cadena, metido al pegarlo (un salto
    de linea de la terminal que se convirtio en espacio). No se habia notado
    porque en el portatil el CLI usa las credenciales de la sesion iniciada y
    nunca llega a mirar el token. En el VPS no hay sesion: alli el token es lo
    unico que hay, y habria fallado la primera vez que la fase 3 pidiera algo.

    Comprobar que "el token esta puesto" no basta. Hay que mirar que tenga
    forma de token.
    """
    problemas: list[str] = []
    try:
        from core.secrets import Secrets
    except ImportError as exc:  # pragma: no cover
        return [
            f"no se pudo leer la configuracion de secretos ({exc}). "
            f"Lanza el script con el python del .venv, no con el del sistema"
        ]

    secretos = Secrets()
    token = secretos.claude_code_oauth_token
    if token is None:
        print("   no hay CLAUDE_CODE_OAUTH_TOKEN en el .env")
        print("   Se genera con `claude setup-token` y se pega en el .env.")
        return ["falta el token de Claude, y la fase 3 no arranca sin el"]

    valor = token.get_secret_value()
    print(f"   token presente, {len(valor)} caracteres")

    # Nunca se imprime el valor: solo si tiene forma de token.
    if valor != valor.strip():
        problemas.append("el token tiene espacios al principio o al final")
    interiores = [i for i, c in enumerate(valor.strip()) if c.isspace()]
    if interiores:
        print(f"   ROTO: hay espacios dentro del token (posicion {interiores[0]})")
        print("   Se parte al pegarlo cuando la terminal lo corta en dos lineas.")
        print("   Hay que regenerarlo con `claude setup-token` y pegarlo entero.")
        problemas.append("el token tiene espacios dentro: esta corrupto")
    elif not valor.startswith("sk-ant-"):
        problemas.append("el token no empieza por 'sk-ant-': no parece un token")
    else:
        print("   formato correcto (sin espacios, prefijo esperado)")

    if not problemas:
        print("   OJO: que el formato sea correcto no prueba que el token VALGA.")
        print("   Eso lo prueba --sin-sesion (o una llamada desde el VPS).")
    return problemas


def validar_contrato(datos: dict) -> list[str]:
    """Las reglas del contrato del informe seccion 1.5 que el esquema NO cubre."""
    fallos = []
    for d in datos.get("decisions", []):
        if d.get("cid") != CID_REAL:
            fallos.append(
                f"invento el cid {d.get('cid')!r}: el parser TIENE que rechazarlo"
            )
        mult = d.get("size_multiplier")
        if mult is None or not (0.5 <= float(mult) <= 1.0):
            fallos.append(f"size_multiplier fuera de [0,5; 1,0]: {mult}")
    return fallos


def llamar(
    env: dict[str, str] | None = None, secreto: str | None = None
) -> tuple[dict | None, list[str]]:
    problemas: list[str] = []
    seccion("Una llamada real" + (" (sin sesion)" if env is not None else ""))

    if not RUNTIME.is_dir():
        RUNTIME.mkdir(parents=True)
    intrusos = [p.name for p in RUNTIME.iterdir() if p.name not in {".gitkeep", ".gitignore"}]
    if intrusos:
        problemas.append(
            f"claude_runtime/ no esta vacio ({intrusos}): cada llamada cargaria "
            f"ese contexto y gastaria cuota de mas"
        )

    cmd = [
        "claude", "-p", PROMPT,
        "--json-schema", json.dumps(ESQUEMA),
        "--output-format", "json",
        "--model", "sonnet",
        *FLAGS_RECOMENDADOS,
    ]
    inicio = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180,
            cwd=RUNTIME, stdin=subprocess.DEVNULL, env=env,
        )
    except subprocess.TimeoutExpired:
        problemas.append("la llamada paso de 180 s")
        return None, problemas
    tardo = time.monotonic() - inicio

    if proc.returncode != 0:
        print(f"   la llamada fallo (codigo {proc.returncode})")
        print(f"   {tapar(proc.stderr or proc.stdout, secreto)[:400]}")
        problemas.append("la llamada a claude fallo; revisa el token de la suscripcion")
        return None, problemas

    try:
        sobre = json.loads(proc.stdout)
    except json.JSONDecodeError:
        problemas.append("la salida no es JSON pese a --output-format json")
        return None, problemas

    if sobre.get("is_error"):
        problemas.append(
            f"claude devolvio error: {tapar(str(sobre.get('result')), secreto)[:200]}"
        )
        return sobre, problemas

    uso = sobre.get("usage", {})
    print(f"   latencia            {tardo:.1f} s (timeout configurado: 90 s)")
    print(f"   turnos              {sobre.get('num_turns')}")
    print(f"   tokens de entrada   {uso.get('input_tokens')}")
    print(f"   tokens de salida    {uso.get('output_tokens')}")
    print(f"   cache creada        {uso.get('cache_creation_input_tokens')}")
    print(f"   cache leida         {uso.get('cache_read_input_tokens')}")
    print(f"   coste equivalente   {sobre.get('total_cost_usd', 0):.4f} $")
    # El journal lo guarda en ai_calls.modelo (protocolo de la fase 6): aqui se ve si el CLI lo da.
    modelos = sorted(sobre.get("modelUsage") or {}) if isinstance(sobre.get("modelUsage"), dict) else []
    print(f"   modelo              {', '.join(modelos) or 'NO LO DICE (sin modelUsage)'}")

    if tardo > 90:
        problemas.append(
            f"tardo {tardo:.0f} s, mas que el timeout de 90 s de settings.yaml"
        )

    # `structured_output` es la salida ya parseada: mejor que parsear `result`.
    datos = sobre.get("structured_output")
    if datos is None:
        problemas.append("no hay `structured_output` en el sobre")
        return sobre, problemas

    print(f"   decisiones          {len(datos.get('decisions', []))}")
    fallos = validar_contrato(datos)
    for f in fallos:
        print(f"   OJO: {f}")
    print("   el contrato se respeta" if not fallos else "")
    return sobre, problemas


def control_sin_token(casa: Path) -> list[str]:
    """Sin sesion y sin token, el CLI TIENE que negarse. Si no, la prueba no vale."""
    seccion("Control: sin sesion y sin token (tiene que fallar)")
    proc = subprocess.run(
        ["claude", "-p", "ok", "--output-format", "json", *FLAGS_RECOMENDADOS],
        capture_output=True, text=True, timeout=120,
        cwd=RUNTIME, stdin=subprocess.DEVNULL, env=entorno_limpio(casa),
    )
    try:
        sobre = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sobre = {}
    rechazado = proc.returncode != 0 or bool(sobre.get("is_error"))
    print(f"   codigo {proc.returncode}: {str(sobre.get('result', proc.stderr))[:120]!r}")
    if not rechazado:
        return [
            "el control SIN token funciono: el CLI encuentra credenciales en otro "
            "sitio y la prueba sin sesion no demostraria nada"
        ]
    print("   rechazado, como tiene que ser: el aislamiento funciona")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica claude -p para la fase 3")
    parser.add_argument("--call", action="store_true", help="hace UNA llamada real")
    parser.add_argument(
        "--sin-sesion", action="store_true",
        help="hace la llamada real SIN la sesion del portatil, solo con el token "
             "del .env, como sera en el VPS (implica --call)",
    )
    args = parser.parse_args()

    print("Verificacion de `claude -p` para la fase 3")
    print("=" * 74)

    problemas: list[str] = []

    seccion("Binario")
    hay, version = comprobar_binario()
    if not hay:
        print("   claude NO esta instalado en esta maquina")
        print()
        print("   En el VPS se instala con `sudo bash deploy/install-claude.sh`")
        print("   (sin Node.js: es la instalacion nativa). Sin eso la fase 3 no")
        print("   puede arrancar alli, por mucho que funcione en el portatil.")
        return 1
    print(f"   claude {version}")
    from ai.invoke import VERIFIED_VERSION  # noqa: PLC0415 (solo aqui hace falta)
    if not version.startswith(VERIFIED_VERSION + " "):
        print(f"   OJO: lo verificado es la {VERIFIED_VERSION}. Con otra version hay que")
        print("   repetir esta verificacion Y la prueba en seco antes de fiarse.")

    ayuda = subprocess.run(
        ["claude", "--help"], capture_output=True, text=True, timeout=30
    ).stdout
    problemas += comprobar_flags(ayuda)

    seccion("Autenticacion")
    problemas += comprobar_token()

    if args.sin_sesion:
        if problemas:
            print()
            print("   no se hace la llamada sin sesion: arregla antes lo de arriba")
        else:
            from core.secrets import Secrets

            token = Secrets().claude_code_oauth_token.get_secret_value().strip()
            casa = Path(tempfile.mkdtemp(prefix="ploutos-sin-sesion-"))
            try:
                problemas += control_sin_token(casa)
                if not problemas:
                    _sobre, mas = llamar(entorno_limpio(casa, token), secreto=token)
                    problemas += mas
            finally:
                shutil.rmtree(casa, ignore_errors=True)
    elif args.call:
        _sobre, mas = llamar()
        problemas += mas
    else:
        seccion("Una llamada real")
        print("   omitida. Con --call se hace una (gasta 1 de las 40 de la regla 18).")

    seccion("Resultado")
    if problemas:
        for p in problemas:
            print(f"   - {p}")
        return 1
    print("   todo lo que la fase 3 necesita esta disponible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
