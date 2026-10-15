"""Prueba de mutacion de las reglas duras.

CRITERIO DE AVANCE AMPLIADO DE LA FASE 2 (decidido con el propietario el 22/09/2026):

    "Tests de propiedades en verde" no basta. Un test mal escrito pasa en verde
    sin comprobar nada, y es el fallo mas comun y mas dificil de ver.

Esto lo cierra: desactiva cada regla dura una por una (se sustituye por otra que
aprueba siempre) y comprueba que **al menos un test se pone en rojo**. Si con la
regla desactivada todo sigue verde, esos tests no la protegen.

    python scripts/mutation_check.py
    python scripts/mutation_check.py --rule 7

    exit 0 -> todas las reglas comprobables estan protegidas
    exit 1 -> alguna regla se puede desactivar sin que nadie se entere
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from risk.rules import all_rules  # noqa: E402

# Reglas que no se pueden mutar de forma significativa, con el motivo.
# Se informan aparte en vez de contarlas como fallo: no protegerlas AQUI es
# correcto, porque se comprueban en otro sitio.
NOT_MUTABLE = {
    2: "se valida en core.config al arrancar (test_config.py); aqui solo confirma",
    5: "es configuracion, se valida en core.config al arrancar",
    19: "el motor de riesgo NUNCA ve credenciales; que no pueda comprobarlas "
        "es la regla cumpliendose. Se verifica con scripts/verify_okx_key.py",
}

TEST_PATHS = ["tests/unit/test_risk_rules.py", "tests/property"]


def run_tests(rule_number: int | None) -> tuple[int, int, int]:
    """Lanza los tests. Devuelve (codigo, pasados, fallados)."""
    env = dict(os.environ)
    if rule_number is not None:
        env["PLOUTOS_MUTATE_RULE"] = str(rule_number)
    else:
        env.pop("PLOUTOS_MUTATE_RULE", None)

    python = REPO / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = REPO / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    result = subprocess.run(
        [str(python), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         *TEST_PATHS],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    passed = failed = 0
    for line in result.stdout.splitlines():
        if " passed" in line or " failed" in line:
            for part in line.replace(",", "").split():
                if part.isdigit():
                    continue
            import re

            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
    return result.returncode, passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba de mutacion de las reglas duras")
    parser.add_argument("--rule", type=int, default=None, help="mutar solo esta regla")
    args = parser.parse_args()

    print("Prueba de mutacion de las reglas duras")
    print("=" * 74)
    print()
    print("Se desactiva cada regla y se comprueba que algun test se pone en rojo.")
    print("Una regla que se puede desactivar sin que nadie se entere no esta")
    print("protegida por ningun test.")
    print()

    print("Linea base (sin mutar): ", end="", flush=True)
    code, passed, failed = run_tests(None)
    if code != 0:
        print(f"FALLA con {failed} test(s) en rojo.")
        print()
        print("La suite tiene que estar en verde ANTES de mutar nada; si no, no se")
        print("puede distinguir un fallo provocado de uno que ya estaba.")
        return 1
    print(f"{passed} tests en verde")
    print()

    rules = all_rules()
    if args.rule is not None:
        rules = [r for r in rules if r[0] == args.rule]
        if not rules:
            print(f"No existe la regla {args.rule}")
            return 2

    header = f"{'regla':>6}  {'nombre':<26}{'verde':>7}{'ROJO':>7}  resultado"
    print(header)
    print("-" * len(header))

    unprotected: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    started = time.time()

    for number, name, _fn in rules:
        if number in NOT_MUTABLE:
            skipped.append((number, name))
            print(f"{number:>6}  {name:<26}{'-':>7}{'-':>7}  no mutable")
            continue

        _code, passed, failed = run_tests(number)
        if failed > 0:
            print(f"{number:>6}  {name:<26}{passed:>7}{failed:>7}  PROTEGIDA")
        else:
            print(f"{number:>6}  {name:<26}{passed:>7}{failed:>7}  <-- SIN PROTEGER")
            unprotected.append((number, name))

    elapsed = time.time() - started
    print()
    print(f"({elapsed:.0f} s)")
    print()

    if skipped:
        print("Reglas no mutables, y por que:")
        for number, name in skipped:
            print(f"  {number:>2}. {name}: {NOT_MUTABLE[number]}")
        print()

    if unprotected:
        print("RESULTADO: FALLA")
        print()
        print("Estas reglas se pueden desactivar sin que ningun test se entere:")
        for number, name in unprotected:
            print(f"  regla {number}: {name}")
        print()
        print("Hay que escribir un test que las cubra antes de dar la fase por buena.")
        return 1

    total = len(rules) - len(skipped)
    print(f"RESULTADO: CORRECTO. Las {total} reglas mutables estan protegidas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
