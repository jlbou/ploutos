"""El analisis de la medicion larga de spread (`scripts/analyze_spread.py`)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analyze_spread.py"
_spec = importlib.util.spec_from_file_location("analyze_spread", SCRIPT)
az = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = az   # los dataclass lo necesitan al cargar el script
_spec.loader.exec_module(az)

CABECERA = "ts_utc,symbol,spread_pct,depth_bid_usd,depth_ask_usd,mid\n"


def csv_(tmp_path, filas):
    p = tmp_path / "m.csv"
    p.write_text(CABECERA + "".join(f"{f}\n" for f in filas), encoding="utf-8")
    return p


def test_las_franjas_cubren_el_dia_sin_solaparse():
    vistas = [az.franja(datetime(2026, 9, 22, h)) for h in range(24)]
    assert vistas[:8] == ["asia"] * 8
    assert vistas[8:13] == ["europa"] * 5
    assert vistas[13:21] == ["america"] * 8
    assert vistas[21:] == ["cierre"] * 3


def test_dos_rondas_en_el_mismo_minuto_no_se_mezclan(tmp_path):
    """El fallo que se evito: agrupando por minuto, el USDC de la ronda de las
    :00 se emparejaba con el USD de la de las :30."""
    p = csv_(tmp_path, [
        "2026-09-22T21:43:00+00:00,BTC/USDC,0.010,1e6,1e6,1",
        "2026-09-22T21:43:01+00:00,BTC/USD,0.020,1e6,1e6,1",
        "2026-09-22T21:43:30+00:00,BTC/USDC,0.030,1e6,1e6,1",
        "2026-09-22T21:43:31+00:00,BTC/USD,0.040,1e6,1e6,1",
    ])
    assert az.emparejar(az.leer(p), "BTC") == [(0.010, 0.020), (0.030, 0.040)]


def test_el_resumen_cuenta_lo_que_pasa_de_la_regla_16(tmp_path):
    p = csv_(tmp_path, [
        f"2026-09-22T0{h}:00:00+00:00,SOL/USDC,{s},5000,400,1"
        for h, s in enumerate([0.04, 0.05, 0.12, 0.03])
    ])
    r = az.resumir(az.leer(p))
    assert r.n == 4
    assert r.sobre_entrada_pct == 25.0
    assert r.profundidad_min == 400


def test_un_par_que_pasa_de_media_pero_no_en_asia_se_ve(tmp_path):
    filas = [f"2026-09-22T03:00:{i:02d}+00:00,SOL/USDC,0.09,1e6,1e6,1" for i in range(3)]
    filas += [f"2026-09-22T15:00:{i:02d}+00:00,SOL/USDC,0.01,1e6,1e6,1" for i in range(20)]
    t = az.por_simbolo_y_franja(az.leer(csv_(tmp_path, filas)))["SOL/USDC"]
    assert t["total"].medio < 0.05
    assert t["asia"].medio > 0.05
