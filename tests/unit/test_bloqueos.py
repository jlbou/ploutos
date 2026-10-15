"""Bloqueos silenciosos (`portfolio/bloqueos.py` y `scripts/check_bloqueos.py`).

01/10/2026: OKX retiro BTC/USD, la regla 17 dejo las dos carteras sin entradas 5 velas (20 h) y ningun juez lo
vio, porque el bot cumplia la regla. Este juez avisa cuando TODAS las monedas caen por un motivo de sistema.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from portfolio import store
from portfolio.bloqueos import motivos_de_sistema, tramos_bloqueados

H4 = 4 * 3600_000
T0 = 1_790_740_800_000          # 30/09/2026 04:00 UTC
MONEDAS = ["BTC/USDC", "ETH/USDC", "SOL/USDC"]
PARIDAD = "paridad de usdc: paridad de USDC desconocida"
LLENA = "hueco libre: 3/3 huecos ocupados (pendientes incluidas)"


def vela(ts, *, todas=None, **por_moneda):
    """Las filas de una vela: por defecto todas `filtered` con `todas`; `por_moneda` cambia alguna."""
    filas = []
    for s in MONEDAS:
        kind, detalle = por_moneda.get(s.split("/")[0], ("filtered", todas))
        filas.append((ts, s, kind, detalle))
    return filas


def test_los_motivos_de_sistema_y_los_de_mercado():
    assert motivos_de_sistema(f"{LLENA}; {PARIDAD}") == ["paridad de usdc"]
    assert motivos_de_sistema("sin la vela de esta hora: la ingesta no la escribio a tiempo") == ["sin vela"]
    assert motivos_de_sistema("frescura: fuentes no frescas") == ["frescura"]
    for mercado in (LLENA, "atr: ATR 5.3 % demasiado alto", "spread: 0.2 % > 0.1 %", "cooldown: hasta 12:00",
                    "correlacion: 2 correlacionadas", "cupo diario: 6/6", "modo: en CLOSE_ONLY_MANUAL no se abren",
                    "evento: eventos activos: delisting"):
        assert motivos_de_sistema(mercado) == [], mercado


def test_el_incidente_del_30_09_es_un_tramo():
    """La cartera llena Y la paridad desconocida: cuenta (la paridad sola ya impedia entrar)."""
    velas = [T0 + k * H4 for k in range(7)]
    filas = vela(velas[0], todas=LLENA)
    for ts in velas[1:6]:
        filas += vela(ts, todas=f"{LLENA}; {PARIDAD}")
    filas += vela(velas[6], todas=LLENA)
    [t] = tramos_bloqueados(velas, filas, MONEDAS)
    assert (t.desde_ms, t.hasta_ms, t.velas, t.motivos) == (velas[1], velas[5], 5, ("paridad de usdc",))


def test_una_cartera_llena_no_es_un_bloqueo():
    velas = [T0 + k * H4 for k in range(6)]
    filas = [f for ts in velas for f in vela(ts, todas=LLENA)]
    assert tramos_bloqueados(velas, filas, MONEDAS) == []


@pytest.mark.parametrize("paso", [("candidate", "d-... ETH/USDC"), ("sin_senyal", "rango: lejos del suelo"),
                                  ("filtered", "atr: ATR 6 % demasiado alto")])
def test_una_moneda_que_pasa_o_cae_por_mercado_rompe_el_bloqueo(paso):
    velas = [T0 + k * H4 for k in range(3)]
    filas = vela(velas[0], todas=PARIDAD) + vela(velas[1], todas=PARIDAD, ETH=paso) + vela(velas[2], todas=PARIDAD)
    assert [t.velas for t in tramos_bloqueados(velas, filas, MONEDAS)] == [1, 1]


def test_una_moneda_sin_filas_no_cuenta_como_bloqueada():
    """Si una moneda no tiene fila, no se sabe que le paso: no se afirma un bloqueo."""
    velas = [T0]
    filas = [f for f in vela(T0, todas=PARIDAD) if f[1] != "SOL/USDC"]
    assert tramos_bloqueados(velas, filas, MONEDAS) == []


# --------------------------------------------------------------------------
# El juez, con una base de papel de verdad
# --------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_bloqueos.py"


def _juez():
    spec = importlib.util.spec_from_file_location("check_bloqueos", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def base(tmp_path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    yield c
    c.close()


def _guardar(conn, velas, filas):
    with conn:
        conn.executemany("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                         [(ts, 50.0, 0, 0) for ts in velas])
        conn.executemany("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail)"
                         " VALUES (?,NULL,?,NULL,?,?)", filas)


def test_el_juez_falla_si_el_bloqueo_llega_a_las_ultimas_24_h(base):
    velas = [T0 + k * H4 for k in range(5)]
    _guardar(base, velas, [f for ts in velas for f in vela(ts, todas=PARIDAD)])
    m = _juez()
    fallos, notas, n = m.juzgar(base, MONEDAS, velas[-1] + H4, 24, 3)
    assert n == 5 and len(fallos) == 1 and "5 velas" in fallos[0] and "paridad de usdc" in fallos[0]
    # Dos dias despues ya no es FALLA: queda como nota (ya paso).
    fallos, notas, _n = m.juzgar(base, MONEDAS, velas[-1] + 48 * 3600_000, 24, 3)
    assert fallos == [] and len(notas) == 1


def test_el_juez_no_falla_por_dos_velas(base):
    velas = [T0 + k * H4 for k in range(4)]
    filas = vela(velas[0], todas=LLENA) + vela(velas[1], todas=PARIDAD) + vela(velas[2], todas=PARIDAD)
    filas += vela(velas[3], todas=LLENA)
    _guardar(base, velas, filas)
    assert _juez().juzgar(base, MONEDAS, velas[-1] + H4, 24, 3)[:2] == ([], [])


def test_el_juez_sale_con_1_si_falla(base, tmp_path, monkeypatch, capsys):
    from core.config import load_settings
    whitelist = list(load_settings().whitelist)
    velas = [T0 + k * H4 for k in range(3)]
    _guardar(base, velas, [(ts, s, "filtered", PARIDAD) for ts in velas for s in whitelist])
    m = _juez()
    monkeypatch.setattr("sys.argv", ["check_bloqueos.py", "--paper-db", str(tmp_path / "paper.db"),
                                     "--ahora-ms", str(velas[-1] + H4)])
    assert m.main() == 1
    assert "FALLA" in capsys.readouterr().out
