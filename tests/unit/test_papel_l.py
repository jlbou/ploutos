"""El papel de L (scripts/papel_l.py) y su juez (scripts/check_papel_l.py), sin red ni Telegram.

Lo que importa: que avise de CADA operacion nueva una sola vez (compras, ventas, stops y objetivos entre semana),
que el mensaje no nombre a la IA, que los huecos se cuenten y que el juez siga el criterio fijado por el propietario el 10/10.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


pl = _cargar("papel_l")
cj = _cargar("check_papel_l")

LUNES = pl.ms("2026-10-19")
H4 = 4 * 3600_000
DIA = 86_400_000


def resultado(ops=(), abiertas=None, final=50.0, caida=0.05, btc_caida=0.30, btc_rend=-0.1):
    return {"ops": list(ops), "abiertas": abiertas or {},
            "metricas": {"final": final, "rendimiento": final / 50 - 1, "caida_max": caida},
            "btc": {"rendimiento": btc_rend, "caida_max": btc_caida}}


def op(simbolo, entrada, salida, motivo, neto=-1.0):
    return {"simbolo": simbolo, "entrada_ms": entrada, "salida_ms": salida, "entrada": 10.0, "salida": 9.0,
            "neto": neto, "motivo": motivo}


def pos(t):
    return {"t": t, "entrada": 10.0, "qty": 1.5, "coste": 15.03, "stop": 8.5, "objetivo": 20.0}


# --- eventos ---------------------------------------------------------------------------------------------------------

def test_la_primera_pasada_avisa_de_las_compras_abiertas():
    ev = pl.eventos(None, resultado(abiertas={"SOL/USDC": pos(LUNES)}))
    assert [(e["tipo"], e["simbolo"]) for e in ev] == [("compra", "SOL/USDC")]


def test_lo_ya_avisado_no_se_repite():
    r = resultado(abiertas={"SOL/USDC": pos(LUNES)})
    assert pl.eventos(r, r) == []


def test_un_stop_entre_semana_se_avisa_como_venta():
    antes = resultado(abiertas={"SOL/USDC": pos(LUNES)})
    ahora = resultado(ops=[op("SOL/USDC", LUNES, LUNES + 3 * DIA, "stop")])
    ev = pl.eventos(antes, ahora)
    assert [(e["tipo"], e["motivo"]) for e in ev] == [("venta", "stop")]


def test_compra_y_venta_entre_dos_pasadas_se_avisan_las_dos():
    ahora = resultado(ops=[op("ETH/USDC", LUNES, LUNES + H4, "stop")])
    ev = pl.eventos(resultado(), ahora)
    assert [e["tipo"] for e in ev] == ["compra", "venta"]


def test_la_rotacion_del_lunes_vende_y_compra():
    antes = resultado(abiertas={"SOL/USDC": pos(LUNES)})
    ahora = resultado(ops=[op("SOL/USDC", LUNES, LUNES + 7 * DIA, "rotacion", 2.0)],
                      abiertas={"NEAR/USDC": pos(LUNES + 7 * DIA)})
    ev = pl.eventos(antes, ahora)
    assert [(e["tipo"], e["simbolo"]) for e in ev] == [("venta", "SOL/USDC"), ("compra", "NEAR/USDC")]


def test_sin_operaciones_nuevas_no_hay_mensaje():
    assert pl.mensaje([], resultado()) is None


def test_el_mensaje_dice_cada_operacion_y_no_nombra_a_la_ia():
    ahora = resultado(ops=[op("SOL/USDC", LUNES, LUNES + 2 * DIA, "objetivo", 15.0)],
                      abiertas={"NEAR/USDC": pos(LUNES)})
    texto = pl.mensaje(pl.eventos(None, ahora), ahora)
    assert texto is not None
    assert "compra <b>SOL</b>" in texto and "vende <b>SOL</b>" in texto and "compra <b>NEAR</b>" in texto
    assert "objetivo" in texto and "+15.00 $" in texto
    assert "Claude" not in texto and "IA" not in texto


# --- datos -----------------------------------------------------------------------------------------------------------

def _base(ruta, velas):
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE candles (symbol TEXT, timeframe TEXT, ts_open_ms INTEGER, open REAL, high REAL, "
                "low REAL, close REAL, volume REAL, closed INTEGER, source TEXT, ingested_ms INTEGER, "
                "PRIMARY KEY (symbol, timeframe, ts_open_ms))")
    con.execute("CREATE TABLE instruments (symbol TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO instruments VALUES (?)", [("BTC/USDC",), ("ETH/USDC",)])
    con.executemany("INSERT INTO candles VALUES (?,?,?,1,1,1,1,1,?,'rest',0)", velas)
    con.commit()
    con.close()


def test_la_ingesta_anyade_solo_velas_cerradas_y_manda_la_historia(tmp_path):
    _base(tmp_path / "h.db", [("BTC/USDC", "4h", LUNES, 1)])
    _base(tmp_path / "i.db", [("BTC/USDC", "4h", LUNES, 1), ("BTC/USDC", "4h", LUNES + H4, 1),
                              ("BTC/USDC", "4h", LUNES + 2 * H4, 0), ("BTC/USDC", "1m", LUNES, 1)])
    info = pl.construir_datos(tmp_path / "d.db", tmp_path / "h.db", tmp_path / "i.db")
    assert info == {"anyadidas": 1, "en_las_dos": 1, "distintas": 0}


def test_los_huecos_se_cuentan_por_moneda(tmp_path):
    velas = [("BTC/USDC", "4h", LUNES + i * H4, 1) for i in range(6)]
    velas += [("ETH/USDC", "4h", LUNES + i * H4, 1) for i in (0, 1, 2, 5)]
    _base(tmp_path / "d.db", velas)
    # A las 26:00 del lunes, con 2 h de margen, deben estar las 6 velas del lunes (la ultima cerro a las 24:00).
    assert pl.huecos(tmp_path / "d.db", LUNES, LUNES + DIA + 2 * H4 // 2) == {"ETH/USDC": 2}


def test_un_hueco_recien_hecho_no_cuenta_y_los_del_final_si(tmp_path):
    """Revision del 15/10: el backfill rellena lo reciente; y si faltan las ultimas velas, tambien es un hueco."""
    velas = [("BTC/USDC", "4h", LUNES + i * H4, 1) for i in range(5)]          # falta la de las 20:00
    velas += [("ETH/USDC", "4h", LUNES + i * H4, 1) for i in range(6)]
    _base(tmp_path / "d.db", velas)
    assert pl.huecos(tmp_path / "d.db", LUNES, LUNES + DIA + 30 * 60_000) == {}          # cerro hace 30 min
    assert pl.huecos(tmp_path / "d.db", LUNES, LUNES + DIA + 3 * 3600_000) == {"BTC/USDC": 1}


# --- el juez ---------------------------------------------------------------------------------------------------------

def meta(pasada):
    return {"pasada_ms": pasada, "huecos": {}}


def test_antes_de_empezar_no_hay_nada_que_juzgar():
    assert cj.juzgar(None, None, pl.ms("2026-10-12"))[0] == 2


def test_en_curso_es_aun_no():
    ahora = pl.ms("2026-11-01")
    assert cj.juzgar(resultado(), meta(ahora - 3600_000), ahora)[0] == 2


def test_si_no_corre_o_hay_huecos_falla():
    ahora = pl.ms("2026-11-01")
    assert cj.juzgar(resultado(), meta(ahora - 30 * 3600_000), ahora)[0] == 1
    assert cj.juzgar(resultado(), {"pasada_ms": ahora, "huecos": {"SOL/USDC": 3}}, ahora)[0] == 1


def test_el_corte_del_25_por_ciento_la_descarta():
    ahora = pl.ms("2026-11-01")
    codigo, lineas = cj.juzgar(resultado(caida=0.26), meta(ahora), ahora)
    assert codigo == 1 and any("corte anticipado" in x for x in lineas)


def test_al_final_pasa_si_no_pierde_y_cae_menos_de_dos_tercios_de_btc():
    fin = pl.ms("2027-01-11")
    assert cj.juzgar(resultado(final=50.0, caida=0.10, btc_caida=0.30), meta(fin), fin)[0] == 0
    assert cj.juzgar(resultado(final=49.99, caida=0.10, btc_caida=0.30), meta(fin), fin)[0] == 1
    assert cj.juzgar(resultado(final=55.0, caida=0.21, btc_caida=0.30), meta(fin), fin)[0] == 1


def test_la_caida_vela_a_vela_es_solo_informacion():
    """Revision 6 (el propietario, 15/10): el criterio sigue con los cierres diarios; la de cada vela de 4 h se ensenya, nada mas."""
    ahora = pl.ms("2026-11-01")
    r = resultado(caida=0.20)
    r["metricas"]["caida_max_velas"], r["btc"]["caida_max_velas"] = 0.27, 0.35
    codigo, lineas = cj.juzgar(r, meta(ahora), ahora)
    assert codigo == 2, "pasar del 25 % vela a vela no corta: el corte fijado es con los cierres diarios"
    assert any("vela a vela: L 27.0 %" in x and "pasaria del corte" in x for x in lineas)
    assert not any("vela a vela" in x for x in cj.juzgar(resultado(), meta(ahora), ahora)[1]), "sin el dato, nada"
