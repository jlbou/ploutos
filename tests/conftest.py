"""Fixtures compartidas."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.config import Settings, load_settings
from data.store.db import Database, migrate

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


@pytest.fixture(autouse=True)
def _sin_telegram_de_verdad(monkeypatch):
    """NINGUN test ve las credenciales de Telegram del `.env` del portatil.

    Los bucles de papel leen `.env` al arrancar y mandan los avisos pendientes en
    cada vuelta (`tick`). Sin esto, pasar los tests mandaria mensajes de verdad al
    movil del propietario. Una variable de entorno vacia manda sobre el `.env` y
    `core.secrets` la trata como ausente.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    # Y ninguno manda latidos de verdad al vigilante (taparian una caida real).
    for nombre in ("HEALTHCHECK_INGESTA", "HEALTHCHECK_PAPEL", "HEALTHCHECK_PAPEL_IA", "HEALTHCHECK_COPIA",
                   "HEALTHCHECK_NOTICIAS"):
        monkeypatch.setenv(nombre, "")


@pytest.fixture(scope="session")
def real_settings_dict() -> dict[str, Any]:
    """El settings.yaml de verdad, como diccionario."""
    return yaml.safe_load(REAL_SETTINGS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def settings_dict(real_settings_dict: dict[str, Any]) -> dict[str, Any]:
    """Copia mutable, para que cada test la retuerza a su gusto."""
    return copy.deepcopy(real_settings_dict)


@pytest.fixture
def settings() -> Settings:
    """La configuracion real del proyecto."""
    return load_settings(REAL_SETTINGS_PATH)


@pytest.fixture
def write_settings(tmp_path: Path):
    """Escribe un dict como settings.yaml temporal y devuelve su ruta."""

    def _write(data: dict[str, Any]) -> Path:
        path = tmp_path / "settings.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Base de datos temporal, ya migrada."""
    database = Database(tmp_path / "test.db")
    database.connect()
    migrate(database)
    yield database
    database.close()


# --------------------------------------------------------------------------
# Prueba de mutacion (criterio de avance ampliado de la fase 2)
# --------------------------------------------------------------------------
#
# Con PLOUTOS_MUTATE_RULE=N se desactiva la regla N: se sustituye por una que
# aprueba siempre. Si con la regla desactivada los tests siguen todos en verde,
# esos tests no la protegen.
#
# Lo usa scripts/mutation_check.py, que recorre las 19.

_mutate = os.environ.get("PLOUTOS_MUTATE_RULE")
if _mutate:
    import risk.rules as _rules
    from risk.types import RuleResult as _RuleResult

    _target = int(_mutate)

    def _always_ok(number: int, name: str):
        def _fn(req, st, lim, cfg):
            return _RuleResult(number, name, True, "MUTADA: aprueba siempre")

        return _fn

    _rules._REGISTRY[:] = [
        (n, name, _always_ok(n, name) if n == _target else fn)
        for n, name, fn in _rules._REGISTRY
    ]
