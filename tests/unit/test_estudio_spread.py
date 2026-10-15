"""El estudio del spread de la whitelist (scripts/estudio_spread.py), con muestras inventadas."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "estudio_spread.py"
_spec = importlib.util.spec_from_file_location("estudio_spread", SCRIPT)
es = importlib.util.module_from_spec(_spec)
sys.modules["estudio_spread"] = es
_spec.loader.exec_module(es)

H = 3600_000
LUNES = 1_790_553_600_000          # 28/09/2026 00:00 UTC, lunes
SABADO = LUNES - 2 * 24 * H        # 26/09/2026 00:00 UTC


def serie(desde, horas, spread, cada_s=600, prof=10_000.0):
    """Una muestra cada `cada_s` segundos; `spread` puede ser una funcion de la hora UTC."""
    out = []
    for i in range(int(horas * 3600 / cada_s)):
        ts = desde + i * cada_s * 1000
        s = spread(ts // H % 24) if callable(spread) else spread
        out.append(es.Muestra(ts, s, prof))
    return out


def test_una_moneda_estrecha_pasa():
    r = es.resumir(serie(LUNES, 48, 0.02))
    assert r.veredicto == "PASA" and r.medio == 0.02 and r.dias == 2 and r.dias_sobre == 0
    assert r.sobre_medio_pct == 0 and r.cierres == 12 and r.cierres_bloqueados == 0


def test_de_media_pasa_pero_no_en_la_franja_asiatica():
    r = es.resumir(serie(LUNES, 24, lambda h: 0.07 if h < 8 else 0.035))
    assert r.medio < es.MAX_SPREAD_MEDIO_PCT and r.por_franja["asia"] == 0.07
    assert r.veredicto == "FALLA: en alguna franja"


def test_el_fin_de_semana_se_mira_aparte():
    muestras = serie(SABADO, 48, 0.06) + serie(LUNES, 24 * 5, 0.03)
    r = es.resumir(muestras)
    assert round(r.fin_de_semana, 9) == 0.06 and round(r.laborable, 9) == 0.03 and r.medio < es.MAX_SPREAD_MEDIO_PCT
    assert "en fin de semana" in r.veredicto and r.dias_sobre == 2


def test_la_regla_16_solo_cuenta_en_los_cierres_de_vela():
    # Por encima del 0,10 % a las 04:00 (un cierre) y a las 06:00 (no lo es).
    r = es.resumir(serie(LUNES, 24, lambda h: 0.15 if h in (4, 6) else 0.02))
    assert r.cierres == 6 and r.cierres_bloqueados == 1
    assert round(r.sobre_entrada_pct, 3) == round(100 * 2 / 24, 3)


def test_un_cierre_sin_muestra_en_los_dos_minutos_no_cuenta():
    muestras = [es.Muestra(LUNES + 4 * H + 3 * 60_000, 0.2, 1e4)]      # 3 min tarde
    assert es.en_los_cierres(muestras) == []
    muestras = [es.Muestra(LUNES + 4 * H + 10_000, 0.2, 1e4), es.Muestra(LUNES + 4 * H + 20_000, 0.01, 1e4)]
    assert es.en_los_cierres(muestras) == [0.2]                        # solo la primera


def test_la_profundidad_mira_el_p5():
    muestras = serie(LUNES, 24, 0.02, prof=10_000.0)
    muestras[5] = es.Muestra(muestras[5].ts_ms, 0.02, 50.0)           # un hueco puntual no tumba la moneda
    r = es.resumir(muestras)
    assert r.profundidad_min == 50.0 and r.veredicto == "PASA"
    assert es.resumir(serie(LUNES, 24, 0.02, prof=100.0)).veredicto == "FALLA: profundidad"


def test_lee_la_base_y_el_informe_avisa_de_lo_que_falta(tmp_path):
    c = sqlite3.connect(tmp_path / "p.db")
    c.execute("CREATE TABLE book_metrics (symbol TEXT, ts_ms INTEGER, mid REAL, spread_pct REAL, imbalance REAL,"
              " depth_bid_05pct REAL, depth_ask_05pct REAL, depth_bid_01pct REAL, depth_ask_01pct REAL, levels INT)")
    c.executemany("INSERT INTO book_metrics VALUES (?,?,1,?,0,?,?,0,0,10)",
                  [("BTC/USDC", LUNES + i * 10_000, 0.004, 5e4, 7e4) for i in range(10)])
    muestras = es.leer(c, LUNES, LUNES + H)
    assert list(muestras) == ["BTC/USDC"] and muestras["BTC/USDC"][0].profundidad_usd == 5e4
    texto = "\n".join(es.informe({"BTC/USDC": es.resumir(muestras["BTC/USDC"])}, LUNES, LUNES + H,
                                 ("BTC/USDC", "DOGE/USDC")))
    assert "sin muestras de DOGE/USDC" in texto and "al menos 14" in texto and "la cambia el propietario" in texto
    assert "claude" not in texto.lower()
