"""El juez de la fase 3 (scripts/check_fase3.py), con bases de papel de verdad y un reloj fijo."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from portfolio import store

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_fase3.py"
_spec = importlib.util.spec_from_file_location("check_fase3", SCRIPT)
cf3 = importlib.util.module_from_spec(_spec)
sys.modules["check_fase3"] = cf3
_spec.loader.exec_module(cf3)

H4 = 4 * 3600_000
T0 = 1_790_337_600_000                  # 25/09/2026 12:00 UTC: la primera vela de las dos carteras


def base(tmp_path, nombre, velas, candidatos=(), llenas=0):
    """Una base de papel con `velas` velas procesadas desde T0 y candidatos en las velas dadas."""
    c = store.connect(tmp_path / f"{nombre}.db")
    store.migrate(c)
    with c:
        c.executemany("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                      [(T0 + i * H4, 50.0, 3 if i < llenas else 0, 0) for i in range(velas)])
        c.execute("INSERT INTO paper_cursor (timeframe, last_ts_ms) VALUES ('4h', ?)", (T0 + (velas - 1) * H4,))
        for ts, n in candidatos:
            c.executemany("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, kind) VALUES (?,?,?,'candidate')",
                          [(ts, f"d-{ts}-{i}", "BTC/USDC") for i in range(n)])
    return c


def llamada(c, ts, n, outcome="ok", valid=1, latencia=20.0, retraso_s=4, kind="decision"):
    with c:
        c.execute("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates, latency_s,"
                  " input_tokens, output_tokens, cache_created, cost_usd_equiv) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, ts + H4 + retraso_s * 1000, kind, outcome, valid, "x", n,
                   None if outcome.startswith("skipped") else latencia, 3, 1800, 18000, 0.095))


def juzgar(tmp_path, velas=43, cands=((T0, 1), (T0 + H4, 2)), ahora=None, correr=None, preparar=None, llenas=0):
    b = base(tmp_path, "base", velas, cands, llenas)
    a = base(tmp_path, "ai", velas, cands, llenas)
    for ts, n in cands:
        llamada(a, ts, n)
    if preparar:
        preparar(a)
    ahora = ahora or T0 + velas * H4 + 20 * 60_000        # 20 min despues del cierre de la ultima
    carteras = [cf3.Cartera.de(n, c, "4h", 3) for n, c in (("baseline", b), ("IA", a))]
    return cf3.juzgar(*carteras, cf3.llamadas_de(a), ahora_ms=ahora, paso_ms=H4, max_dia=40, max_5h=8,
                      timeout_s=90, correr=correr)


def test_una_semana_en_orden_es_cumplido(tmp_path):
    codigo, inf = juzgar(tmp_path, velas=42)                # 42 velas de 4 h = 7 dias justos
    assert inf.fallas == [] and codigo == 0
    texto = "\n".join(inf.lineas)
    assert "llamadas: 2 (0 sonda(s))" in texto and "pico 2/dia (tope 40) y 2 en 5 h (tope 8)" in texto
    assert "0.190 $ en total" in texto and "latencia: mediana 20.0 s" in texto
    assert "3 candidato(s) en 2 vela(s)" in texto


def test_menos_de_una_semana_es_aun_no(tmp_path):
    codigo, inf = juzgar(tmp_path, velas=41)
    assert inf.fallas == [] and codigo == 2


def test_una_vela_con_candidatos_sin_fila_en_el_journal_es_falla(tmp_path):
    def sin_fila(a):
        with a:
            a.execute("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, kind) VALUES (?, 'd-z', 'ETH/USDC',"
                      " 'candidate')", (T0 + 5 * H4,))
    codigo, inf = juzgar(tmp_path, preparar=sin_fila)
    assert codigo == 1 and any("sin fila en el journal" in f for f in inf.fallas)


def test_el_journal_y_los_candidatos_tienen_que_cuadrar(tmp_path):
    codigo, inf = juzgar(tmp_path, preparar=lambda a: llamada(a, T0 + 9 * H4, 2))
    assert codigo == 1 and any("sin candidatos apuntados" in f for f in inf.fallas)
    assert any("dice 2 candidato(s) y hay 0" in f for f in inf.fallas)


def test_una_vela_perdida_por_una_parada_es_falla(tmp_path):
    def parada(a):
        with a:
            a.execute("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, kind) VALUES (?, 'd-s', 'SOL/USDC',"
                      " 'candidate')", (T0 + 7 * H4,))
        llamada(a, T0 + 7 * H4, 1, outcome="skipped_stale", valid=0)
    codigo, inf = juzgar(tmp_path, preparar=parada)
    assert codigo == 1 and any("sin decidir por una parada" in f for f in inf.fallas)


def test_las_invalidas_controladas_se_cuentan_pero_no_son_falla(tmp_path):
    def invalidas(a):
        for i, (outcome, valid) in enumerate((("timeout", 0), ("ok", 0), ("error", 0))):
            ts = T0 + (10 + i) * H4
            with a:
                a.execute("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, kind) VALUES (?,?,?,'candidate')",
                          (ts, f"d-i{i}", "ETH/USDC"))
            llamada(a, ts, 1, outcome=outcome, valid=valid)
    codigo, inf = juzgar(tmp_path, preparar=invalidas)
    assert inf.fallas == [] and codigo == 0
    texto = "\n".join(inf.lineas)
    assert "invalida (fuera de contrato) 1" in texto and "timeout 1" in texto and "3 sin decision util" in texto


def test_una_cartera_atrasada_es_falla_pero_con_margen_tras_el_cierre(tmp_path):
    # La ultima vela procesada abrio en T0 + 42*H4 - H4; la siguiente cierra en T0 + 43*H4.
    tarde = T0 + 43 * H4 + 30 * 60_000
    codigo, inf = juzgar(tmp_path, velas=42, ahora=tarde)
    assert codigo == 1 and sum("va atrasada" in f for f in inf.fallas) == 2
    otra = tmp_path / "otra"
    otra.mkdir()
    recien = T0 + 43 * H4 + 5 * 60_000                      # recien cerrada: aun se le da margen
    codigo, inf = juzgar(otra, velas=42, ahora=recien)
    assert inf.fallas == [] and codigo == 0


def test_el_pico_de_la_ventana_de_5h_y_las_sondas(tmp_path):
    def mas(a):
        llamada(a, T0 + H4, 0, kind="probe", retraso_s=60)
    codigo, inf = juzgar(tmp_path, preparar=mas)
    texto = "\n".join(inf.lineas)
    assert "llamadas: 3 (1 sonda(s))" in texto and "y 3 en 5 h" in texto      # 4 h y 1 min: dentro


def test_la_cartera_llena_para_la_decision_5(tmp_path):
    _c, inf = juzgar(tmp_path, llenas=10)
    assert "cartera llena en 10 de 43 velas" in "\n".join(inf.lineas)


@pytest.mark.parametrize("codigos, falla", [((0, 2), False), ((2, 2), False), ((0, 1), True), ((None, 0), True)])
def test_el_juez_de_papel_de_las_dos_carteras(tmp_path, codigos, falla):
    it = iter(codigos)
    vistos = []

    def correr(args):
        vistos.append(tuple(args))
        return next(it), "...\nRESULTADO: algo"
    codigo, inf = juzgar(tmp_path, correr=correr)
    assert (codigo == 1) is falla
    assert vistos[0] == ("scripts/check_paper.py",) and "--decider" in vistos[1] and "ai" in vistos[1]


def test_percentil_por_rango_mas_cercano():
    assert cf3.percentil([1.0], 95) == 1.0
    assert cf3.percentil([3.0, 1.0, 2.0, 4.0], 50) == 2.0
    assert cf3.percentil(list(map(float, range(1, 21))), 95) == 19.0


def test_nunca_nombra_a_claude():
    assert "claude" not in SCRIPT.read_text(encoding="utf-8").lower().replace("claude.max_calls", "") \
        .replace("claude.timeout", "")
