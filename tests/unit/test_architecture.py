"""Invariantes de arquitectura (PRD seccion 13).

"risk/ no depende de ai/" es una regla que un comentario no sostiene: en
cuanto alguien anyada un import por comodidad, un fallo de la IA puede tumbar
el motor de riesgo. Aqui se comprueba leyendo el arbol sintactico.

Este test esta desde la fase 1, con `risk/` todavia vacio, a proposito: asi
protege el limite desde el primer fichero que se escriba dentro.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (paquete, paquete prohibido, motivo)
FORBIDDEN: list[tuple[str, str, str]] = [
    ("risk", "ai", "un fallo de la IA no puede tumbar el motor de riesgo"),
    ("risk", "execution", "el motor de riesgo decide, no ejecuta"),
    ("core", "ai", "el nucleo no depende de la IA"),
    ("core", "risk", "el nucleo no depende del motor de riesgo"),
    ("data", "ai", "la ingesta no depende de la IA"),
    # La capa de estrategia propone; no ejecuta ni pregunta a la IA por su
    # cuenta. Quien orquesta esas dos cosas es el bucle principal.
    ("strategy", "execution", "el generador de candidatos propone, no ejecuta"),
    # `features/` es calculo puro sobre velas. Si empieza a mirar el estado de
    # la cartera o los candidatos, deja de poder probarse con una serie suelta
    # y aparece el look-ahead bias por la puerta de atras.
    ("features", "strategy", "los indicadores no saben nada de la cartera"),
    ("features", "risk", "los indicadores no saben nada de la cartera"),
    ("features", "ai", "los indicadores son calculo puro"),
    # El baseline es la mitad de CONTROL del experimento que decide si la IA
    # aporta algo. Si importase `ai/`, dejaria de ser un control.
    ("strategy", "ai", "el baseline sin IA no puede depender de la IA"),
    # `portfolio/` no consulta a la IA. El informe seccion 1.3[9] es explicito:
    # el gestor de posiciones trabaja "sin IA".
    ("portfolio", "ai", "el gestor de posiciones trabaja sin IA"),
    # El ejecutor manda lo que el motor ya aprobo. Si dependiera de la IA, un fallo
    # de la IA podria dejar posiciones sin su OCO (regla 13).
    ("execution", "ai", "el ejecutor no depende de la IA"),
    # Los avisos tienen que llegar precisamente cuando la IA falla: si `notify/`
    # dependiera de `ai/`, un fallo de la IA dejaria sin el aviso de que ha fallado.
    ("notify", "ai", "avisar de un fallo de la IA no puede depender de la IA"),
    ("notify", "execution", "avisar no es operar"),
    # El panel (fase 5) SOLO LEE: ni pregunta a la IA ni habla con el exchange (el propietario, 25/09).
    ("api", "ai", "el panel ensenya lo que paso; no consulta a la IA"),
    ("api", "execution", "el panel no opera"),
]

# NO esta prohibido `portfolio` -> `strategy`, y se anyadio por error una vez.
# El informe seccion 1.7 pone el coste de oportunidad en `portfolio/`, y ese
# calculo compara `EV_nuevo(candidato)` contra las posiciones abiertas: sin ver
# candidatos no se puede hacer. Ademas `portfolio/loop.py` es el orquestador
# del bucle, y un orquestador tiene que conocer las capas que encadena.
#
# Lo que SI se mantiene es que el EJECUTOR (`portfolio/paper.py`) siga sin
# saber nada de estrategia: recibe veredictos ya aprobados y los simula. Eso lo
# comprueba el test de abajo, a nivel de fichero y no de paquete.
EJECUTOR_PURO = "portfolio/paper.py"

# El par de bytes que no puede aparecer en lo que va al servidor.
# Se define con codigos y no literal para que ningun editor lo convierta en
# un salto de linea de verdad, que es como se rompio la primera version.
CRLF = bytes([13, 10])


def imported_modules(path: Path) -> set[str]:
    """Modulos de primer nivel que importa un fichero."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # import relativo: dentro del propio paquete
            if node.module:
                found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize(
    "package,forbidden,reason",
    FORBIDDEN,
    ids=[f"{p}-no-importa-{f}" for p, f, _ in FORBIDDEN],
)
def test_dependencias_prohibidas(package: str, forbidden: str, reason: str):
    package_dir = REPO_ROOT / package
    if not package_dir.is_dir():
        pytest.skip(f"{package}/ todavia no existe")

    offenders: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        if forbidden in imported_modules(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"{package}/ importa {forbidden}/ en {offenders}. {reason}."
    )


def test_el_detector_funciona_de_verdad(tmp_path):
    """Prueba de mutacion del propio test: si el detector no detecta, no vale."""
    culprit = tmp_path / "culpable.py"
    culprit.write_text("from ai.analyst import decide\n", encoding="utf-8")
    assert "ai" in imported_modules(culprit)

    culprit.write_text("import ai.analyst\n", encoding="utf-8")
    assert "ai" in imported_modules(culprit)

    innocent = tmp_path / "inocente.py"
    innocent.write_text("from core.config import Settings\n", encoding="utf-8")
    assert "ai" not in imported_modules(innocent)


def test_los_paquetes_del_informe_existen():
    """Estructura de carpetas del informe seccion 6."""
    for package in (
        "core", "data", "features", "strategy", "risk",
        "execution", "portfolio", "learning", "notify", "api",
    ):
        assert (REPO_ROOT / package).is_dir(), f"falta el paquete {package}/"


def test_claude_runtime_esta_vacio():
    """Informe seccion 1.5: `claude -p` se ejecuta desde un directorio vacio.

    Si hay un CLAUDE.md o un .mcp.json ahi dentro, cada llamada carga contexto
    de mas y gasta cuota (regla 18).
    """
    runtime = REPO_ROOT / "claude_runtime"
    if not runtime.is_dir():
        pytest.skip("claude_runtime/ todavia no existe")
    intruders = [
        p.name for p in runtime.iterdir() if p.name not in {".gitkeep", ".gitignore"}
    ]
    assert not intruders, f"claude_runtime/ debe estar vacio, contiene {intruders}"


def test_el_ejecutor_no_sabe_de_estrategia():
    """`portfolio/paper.py` recibe ordenes ya aprobadas y las simula.

    Si empezara a importar `strategy/`, seria que ha empezado a opinar sobre
    que operar, y entonces habria dos sitios decidiendo lo mismo. El
    orquestador (`portfolio/loop.py`) SI puede: es su trabajo encadenar capas.
    """
    ejecutor = REPO_ROOT / EJECUTOR_PURO
    importados = imported_modules(ejecutor)
    for prohibido in ("strategy", "features", "ai"):
        assert prohibido not in importados, (
            f"{EJECUTOR_PURO} importa {prohibido}/: el ejecutor no decide"
        )


def test_el_juez_de_la_fase_4_no_reutiliza_el_ejecutor():
    """`execution/juez.py` juzga al ejecutor: si razonara con su codigo (conciliacion, plan, peticiones...),
    un error compartido pasaria sin que nadie lo viera. De `execution/` solo puede usar `ids`, el contrato
    de los identificadores, y el proyecto no le hace falta para nada mas."""
    juez = REPO_ROOT / "execution" / "juez.py"
    arbol = ast.parse(juez.read_text(encoding="utf-8"))
    propios = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            propios |= {f"{nodo.module}.{a.name}" for a in nodo.names}
        elif isinstance(nodo, ast.Import):
            propios |= {a.name for a in nodo.names}
    del_proyecto = {m for m in propios if m.split(".")[0] in {"core", "data", "features", "strategy", "risk",
                                                              "ai", "execution", "portfolio", "notify", "api"}}
    assert del_proyecto == {"execution.ids"}


def test_los_setups_del_slider_existen_de_verdad():
    """`risk/limits.py` nombra los setups con TEXTO para no importar
    `strategy/`: el motor de riesgo no puede depender de la capa de estrategia.

    La duplicacion es deliberada, pero solo es segura si alguien comprueba que
    los dos lados siguen diciendo lo mismo. Sin este test, renombrar un setup
    dejaria el nivel 1 del slider permitiendo un setup que ya no existe, y el
    generador no produciria nada sin que nada avisara.
    """
    from risk.limits import SLIDER_LEVELS
    from strategy.setups import setup_names

    reales = set(setup_names())
    for level, config in SLIDER_LEVELS.items():
        desconocidos = set(config["setups"]) - reales
        assert not desconocidos, (
            f"el nivel {level} del slider permite {desconocidos}, que no "
            f"existen. Los setups reales son {sorted(reales)}"
        )

    # Y del nivel 3 en adelante tienen que estar TODOS: si se anyade un cuarto
    # setup y nadie toca el slider, no se usaria nunca en modo normal.
    assert set(SLIDER_LEVELS[3]["setups"]) == reales


def test_los_ficheros_del_servidor_no_llevan_CRLF():
    """SEGUNDA VEZ QUE PASA, asi que ahora lo comprueba un test.

    `deploy/sync.sh` copia el arbol de trabajo tal cual con tar, no un
    checkout de git, asi que `.gitattributes` no protege de nada aqui: lo que
    este en el disco de Windows es lo que llega al servidor.

    Un script con finales de linea de Windows falla en Linux con un error de
    sintaxis que no se parece en nada a la causa real (el interprete ve un
    retorno de carro pegado a cada comando) y cuesta un rato entender.

    Lo provoca escribir estos ficheros con `Path.write_text()` desde Windows:
    por defecto traduce los saltos de linea. Hay que pasar el parametro
    `newline` explicito o escribir bytes.
    """
    ofensores = []
    for patron in ("deploy/*.sh", "deploy/*.service", "deploy/*.timer", "deploy/*.conf"):
        for path in sorted(REPO_ROOT.glob(patron)):
            if CRLF in path.read_bytes():
                ofensores.append(path.name)
    assert not ofensores, (
        f"estos ficheros van al servidor con CRLF y fallaran alli: {ofensores}"
    )


def test_el_limite_de_reinicios_esta_en_la_seccion_que_lee_systemd():
    """`StartLimitIntervalSec` va en [Unit]: en [Service] systemd lo IGNORA (solo avisa en el
    journal). Estuvo mal en los tres servicios hasta el despliegue del 25/09/2026."""
    mal = []
    for path in sorted(REPO_ROOT.glob("deploy/*.service")):
        seccion = None
        for linea in path.read_text(encoding="utf-8").splitlines():
            if linea.startswith("["):
                seccion = linea.strip()
            elif linea.startswith(("StartLimitIntervalSec", "StartLimitBurst")) and seccion != "[Unit]":
                mal.append(f"{path.name}: {linea} en {seccion}")
    assert not mal, mal


def test_el_env_no_esta_en_git():
    """Regla 19: los secretos fuera del repositorio."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert not (REPO_ROOT / ".env").exists() or ".env" in gitignore


def test_existe_env_example_y_no_tiene_valores():
    """El ejemplo documenta que secretos hacen falta, sin filtrar ninguno."""
    example = REPO_ROOT / ".env.example"
    assert example.is_file()
    for line in example.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        assert value.strip() in ("", "true", "false"), (
            f"{name} tiene un valor en .env.example: {value!r}"
        )


# Los servicios que NO pueden depender de la IA. Con la tabla FORBIDDEN, ningun
# paquete que importan puede importar `ai/`; lo unico que falta es que no lo
# importe el propio script.
#
# Historia: hasta la pieza 9 (23/09/2026) esto decia "ningun servicio usa ai/",
# la condicion de la excepcion del propietario para escribir la fase 3 antes de cerrar la
# 2. Con la pieza 9 la IA tiene SU servicio (`run_paper_ai.py`), y la regla que
# queda es la que importa para el experimento: el grupo de control y la ingesta
# no dependen del codigo de la IA ni para arrancar. Un error de import en `ai/`
# tumbaria el baseline, y con el la comparacion de la fase 6.
SIN_IA = ("scripts/run_paper.py", "scripts/run_ingest.py")


@pytest.mark.parametrize("script", SIN_IA)
def test_la_ingesta_y_el_baseline_no_dependen_de_la_ia(script):
    assert "ai" not in imported_modules(REPO_ROOT / script), (
        f"{script} importa ai/: el grupo de control y la ingesta tienen que "
        f"funcionar aunque ai/ no cargue"
    )


def test_la_cartera_de_la_ia_si_usa_ai():
    """Que la anterior no se cumpla por no mirar donde toca."""
    assert "ai" in imported_modules(REPO_ROOT / "scripts" / "run_paper_ai.py")
