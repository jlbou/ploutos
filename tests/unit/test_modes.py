"""Maquina de modos (PRD seccion 5).

Lo critico: el modo efectivo es el MAS RESTRICTIVO, y CLOSE_ONLY_CAPITAL es
enclavado. Si el enclavamiento falla, el suelo de 25 $ deja de ser un suelo.
"""

from __future__ import annotations

import pytest

from core.modes import Mode, ModeLatchedError, ModeMachine


@pytest.fixture
def machine() -> ModeMachine:
    return ModeMachine()


# --- estado inicial ---


def test_arranca_en_normal(machine):
    assert machine.effective is Mode.NORMAL
    assert machine.can_open
    assert machine.can_close
    assert machine.active == frozenset()


# --- quien puede abrir ---


@pytest.mark.parametrize(
    "mode",
    [
        Mode.CLOSE_ONLY_QUOTA,
        Mode.CLOSE_ONLY_DEGRADED,
        Mode.CLOSE_ONLY_DAILY,
        Mode.CLOSE_ONLY_MANUAL,
        Mode.CLOSE_ONLY_CAPITAL,
        Mode.HALTED,
    ],
)
def test_solo_normal_abre_posiciones(mode):
    """Regla transversal: cualquier modo que no sea NORMAL bloquea entradas."""
    assert not mode.can_open
    assert Mode.NORMAL.can_open


@pytest.mark.parametrize(
    "mode",
    [
        Mode.NORMAL,
        Mode.CLOSE_ONLY_QUOTA,
        Mode.CLOSE_ONLY_DEGRADED,
        Mode.CLOSE_ONLY_DAILY,
        Mode.CLOSE_ONLY_MANUAL,
        Mode.CLOSE_ONLY_CAPITAL,
    ],
)
def test_todos_menos_halted_pueden_cerrar(mode):
    """Un modo de solo cierre tiene que poder, precisamente, cerrar."""
    assert mode.can_close


def test_halted_no_cierra_por_defecto():
    assert not Mode.HALTED.can_close


# --- el mas restrictivo gana ---


def test_un_modo_activo_es_el_efectivo(machine):
    machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota agotada")
    assert machine.effective is Mode.CLOSE_ONLY_QUOTA
    assert not machine.can_open


def test_coexisten_quota_y_capital_gana_capital(machine):
    """El caso que el informe 1.4 senyala como el que se suele hacer mal."""
    machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota agotada")
    machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity <= 25")
    assert machine.effective is Mode.CLOSE_ONLY_CAPITAL


def test_halted_gana_a_todo(machine):
    machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity <= 25")
    machine.activate(Mode.HALTED, "kill switch")
    assert machine.effective is Mode.HALTED
    assert not machine.can_close


def test_quitar_el_mas_restrictivo_deja_el_siguiente(machine):
    machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota")
    machine.activate(Mode.CLOSE_ONLY_DEGRADED, "datos")
    machine.deactivate(Mode.CLOSE_ONLY_DEGRADED, "datos OK")
    assert machine.effective is Mode.CLOSE_ONLY_QUOTA
    assert not machine.can_open


def test_quitar_todos_vuelve_a_normal(machine):
    machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota")
    machine.deactivate(Mode.CLOSE_ONLY_QUOTA, "cuota OK")
    assert machine.effective is Mode.NORMAL
    assert machine.can_open


# --- enclavamiento (regla 7) ---


def test_capital_no_se_levanta_automaticamente(machine):
    """Regla 7: aunque el equity rebote, no se vuelve a abrir."""
    machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity <= 25")
    with pytest.raises(ModeLatchedError, match="enclavado"):
        machine.deactivate(Mode.CLOSE_ONLY_CAPITAL, "equity de vuelta a 26")


def test_capital_solo_sale_con_reset_manual(machine):
    machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity <= 25")
    change = machine.manual_reset(Mode.CLOSE_ONLY_CAPITAL, "el propietario lo resetea")
    assert change is not None
    assert machine.effective is Mode.NORMAL


def test_halted_tambien_es_enclavado(machine):
    machine.activate(Mode.HALTED, "kill switch")
    with pytest.raises(ModeLatchedError):
        machine.deactivate(Mode.HALTED, "ya paso")
    machine.manual_reset(Mode.HALTED, "el propietario lo resetea")
    assert machine.effective is Mode.NORMAL


def test_equity_rebota_pero_sigue_sin_abrir(machine):
    """La escena completa: cae, se enclava, rebota, y no abre."""
    machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity 24.8")
    assert not machine.can_open
    # el equity vuelve a 26 $ y el codigo intenta levantarlo solo
    with pytest.raises(ModeLatchedError):
        machine.deactivate(Mode.CLOSE_ONLY_CAPITAL, "equity 26")
    assert not machine.can_open
    assert machine.effective is Mode.CLOSE_ONLY_CAPITAL


# --- idempotencia e historial ---


def test_activar_dos_veces_no_duplica(machine):
    first = machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota")
    second = machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota otra vez")
    assert first is not None
    assert second is None
    assert len(machine.history) == 1


def test_desactivar_lo_que_no_esta_activo_no_hace_nada(machine):
    assert machine.deactivate(Mode.CLOSE_ONLY_QUOTA, "no estaba") is None
    assert machine.history == ()


def test_normal_no_se_activa(machine):
    with pytest.raises(ValueError, match="ausencia de restricciones"):
        machine.activate(Mode.NORMAL, "?")


def test_el_historial_registra_el_antes_y_el_despues(machine):
    machine.activate(Mode.CLOSE_ONLY_QUOTA, "cuota")
    change = machine.activate(Mode.CLOSE_ONLY_CAPITAL, "equity")
    assert change.effective_before is Mode.CLOSE_ONLY_QUOTA
    assert change.effective_after is Mode.CLOSE_ONLY_CAPITAL
    assert change.activated is True
    assert change.reason == "equity"


def test_el_motivo_se_conserva(machine):
    machine.activate(Mode.CLOSE_ONLY_DAILY, "perdida del dia 3.05 $")
    assert machine.reason_for(Mode.CLOSE_ONLY_DAILY) == "perdida del dia 3.05 $"


# --- orden de restriccion ---


def test_los_rangos_estan_ordenados():
    assert Mode.NORMAL.rank < Mode.CLOSE_ONLY_QUOTA.rank
    assert Mode.CLOSE_ONLY_QUOTA.rank < Mode.CLOSE_ONLY_CAPITAL.rank
    assert Mode.CLOSE_ONLY_CAPITAL.rank < Mode.HALTED.rank


def test_todos_los_modos_del_prd_existen():
    """PRD seccion 5, mas CLOSE_ONLY_MANUAL (la pausa de Telegram, el propietario 25/09): ni uno mas."""
    assert {str(m) for m in Mode} == {
        "NORMAL",
        "CLOSE_ONLY_QUOTA",
        "CLOSE_ONLY_DEGRADED",
        "CLOSE_ONLY_DAILY",
        "CLOSE_ONLY_MANUAL",
        "CLOSE_ONLY_CAPITAL",
        "HALTED",
    }
