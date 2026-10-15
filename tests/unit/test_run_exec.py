"""El servicio del ejecutor (`scripts/run_exec.py`): las comprobaciones de arranque y el estado, sin red ni claves."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from core.config import load_settings
from execution import store as db
from tests.okx_simulado import OkxSimulado

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("run_exec", RAIZ / "scripts" / "run_exec.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
S = load_settings()


def test_la_cuenta_demo_del_02_10_deja_arrancar():
    assert m.motivos_cuenta({"data": [{"perm": "read_only,trade", "feeType": "1", "acctLv": "1"}]}) == []


def test_no_arranca_con_retirada_sin_trading_o_sin_comision_en_usdc():
    assert any("retirada" in x for x in m.motivos_cuenta({"data": [{"perm": "read_only,trade,withdraw",
                                                                     "feeType": "1"}]}))
    assert any("trading" in x for x in m.motivos_cuenta({"data": [{"perm": "read_only", "feeType": "1"}]}))
    assert any("feeType = 0" in x for x in m.motivos_cuenta({"data": [{"perm": "read_only,trade", "feeType": "0"}]}))
    assert m.motivos_cuenta({}) != []


def test_los_instrumentos_son_los_del_demo_con_las_comisiones_configuradas():
    """Ticks del demo (preparacion-fase-4 12): ETH 1 $, no 0,01."""
    ok = OkxSimulado({}, {}, [0])
    ins = m.instrumentos_de(ok.markets, tuple(S.whitelist), S)
    assert ins["ETH/USDC"].tick_size == 1.0 and ins["DOGE/USDC"].tick_size == 0.0001
    assert ins["BTC/USDC"].taker_fee == S.exchange.fees.taker_pct / 100
    assert set(ins) == set(S.whitelist)
    sin_xrp = {k: v for k, v in ok.markets.items() if k != "XRP/USDC"}
    assert "XRP/USDC" not in m.instrumentos_de(sin_xrp, tuple(S.whitelist), S), "sin par en el exchange, fuera"


def test_el_estado_de_una_base_nueva(tmp_path):
    conn = db.conectar(tmp_path / "exec.db")
    db.migrar(conn)
    texto = m.estado(conn)
    assert "foto: ninguna" in texto and "modos: NORMAL" in texto and "cerradas hoy: 0" in texto


def test_solo_el_ejecutor_y_las_comprobaciones_del_demo_leen_las_claves_de_okx():
    """Regla 19 y disenyo de la fase 4: `ploutos-exec` es el UNICO servicio con las claves. Los demas que las leen
    son scripts de comprobacion que se lanzan a mano. Ningun modulo de `execution/` las toca: se las pasa el servicio."""
    permitidos = {"core/secrets.py", "scripts/run_exec.py", "scripts/comprobar_cuenta_demo.py",
                  "scripts/fijar_comision_usdc.py", "scripts/pruebas_demo.py", "scripts/verify_okx_key.py",
                  "scripts/check_exec.py", "scripts/adoptar_posiciones_demo.py"}
    leen = set()
    for ruta in RAIZ.rglob("*.py"):
        rel = ruta.relative_to(RAIZ).as_posix()
        if rel.startswith((".venv", "tests/")):
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Attribute) and n.attr in ("okx_api_key", "okx_api_secret", "okx_password")
               for n in ast.walk(arbol)):
            leen.add(rel)
    assert leen <= permitidos, sorted(leen - permitidos)
    assert "scripts/run_exec.py" in leen



def test_tras_un_parado_llega_su_en_marcha_y_solo_uno(tmp_path):
    from portfolio import store as papel_store
    conn = db.conectar(tmp_path / "exec.db")
    db.migrar(conn)
    assert m.aviso_pendiente(conn) is None, "un primer arranque no avisa"
    papel_store.encolar_avisos(conn, 1_000, [("parada", "exec:parada:1000", "parado")])
    assert m.aviso_pendiente(conn) == 1_000
    papel_store.encolar_avisos(conn, 2_000, [("arranque", "exec:arranque:2000", "en marcha")])
    assert m.aviso_pendiente(conn) is None
