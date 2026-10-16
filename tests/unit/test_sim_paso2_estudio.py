"""Los datos, el juez del liston y las guardias del estudio del paso 2 (plan, secciones 4 y 9; decisiones del 15/10).
Escritos ANTES del codigo. Sin datos reales: todo inventado."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import datos, juez  # noqa: E402

DIA = 86_400
T0 = 1_502_841_600       # 16/08/2017 00:00 UTC


def _escribir(ruta, n, hueco=None):
    velas = [[T0 + i * DIA, 1.0, 1.1, 0.9, 1.0 + i * 0.001, 5.0] for i in range(n) if i != hueco]
    ruta.write_text(json.dumps(velas), encoding="utf-8")


def test_los_datos_se_alinean_y_un_hueco_para_todo(tmp_path):
    _escribir(tmp_path / "bitstamp-btceur.json", 30)
    _escribir(tmp_path / "bitstamp-etheur.json", 30)
    s = datos.cargar(tmp_path)
    assert list(s) == ["BTC", "ETH"] and len(s["BTC"]["t"]) == 30 and s["BTC"]["t"] == s["ETH"]["t"]
    _escribir(tmp_path / "bitstamp-etheur.json", 30, hueco=10)
    with pytest.raises(ValueError, match="hueco"):
        datos.cargar(tmp_path)


def _metricas(anual, caida, alcista=0.5, bajista=-0.1, lateral=0.0, dias_lateral=365):
    """`alcista`, `bajista` y `lateral`: rendimiento TOTAL de los dias de cada tipo (decision del 16/10: sin anualizar)."""
    return {"anual": anual, "caida": caida,
            "tipos": {"alcista": {"total": alcista, "dias": 300}, "bajista": {"total": bajista, "dias": 300},
                      "lateral": {"total": lateral, "dias": dias_lateral}}}


BTC = _metricas(0.30, 0.75, alcista=1.0, bajista=-0.6, lateral=0.0)


def test_el_liston_gana_o_protege():
    assert juez.liston(_metricas(0.31, 0.70), BTC)["pasa"]                    # gana
    assert juez.liston(_metricas(0.26, 0.49), BTC)["pasa"]                    # protege: -4 puntos y 49 % <= 2/3 de 75 %
    assert not juez.liston(_metricas(0.24, 0.40), BTC)["pasa"]                # -6 puntos: no
    assert not juez.liston(_metricas(0.26, 0.51), BTC)["pasa"]                # caida > 50 % (2/3 de 75): no
    assert not juez.liston(_metricas(0.31, 0.80), BTC)["pasa"]                # gana pero cae mas que BTC: no


def test_los_tipos_de_mercado():
    ok = juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.3, lateral=-0.05), BTC)
    assert ok["pasa"]
    assert not juez.tipos(_metricas(0.3, 0.3, alcista=0.4, bajista=-0.3, lateral=0.0), BTC)["pasa"]   # < mitad
    assert not juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.7, lateral=0.0), BTC)["pasa"]   # pierde mas
    assert not juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.3, lateral=-0.11), BTC)["pasa"]  # lateral


def test_pocos_dias_laterales_no_se_inflan():
    """Decision del 16/10 (opcion a): 25 dias con -1,5 % no es -20 % al anyo; el limite es -10 % x 25/365 = -0,68 %."""
    assert not juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.3, lateral=-0.015, dias_lateral=25), BTC)["pasa"]
    assert juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.3, lateral=-0.006, dias_lateral=25), BTC)["pasa"]
    assert juez.tipos(_metricas(0.3, 0.3, alcista=0.6, bajista=-0.3, lateral=-0.019, dias_lateral=73), BTC)["pasa"]


def test_alcista_con_btc_negativo_no_peor_que_btc():
    btc = _metricas(0.0, 0.5, alcista=-0.05, bajista=-0.6)
    assert juez.tipos(_metricas(0.0, 0.3, alcista=-0.04, bajista=-0.3), btc)["pasa"]
    assert not juez.tipos(_metricas(0.0, 0.3, alcista=-0.06, bajista=-0.3), btc)["pasa"]


def test_la_caida_maxima_35():
    assert juez.caida(_metricas(0.3, 0.35))["pasa"] and not juez.caida(_metricas(0.3, 0.36))["pasa"]


def test_la_prueba_limpia_una_sola_vez_y_con_candidata(tmp_path):
    cerrojo = tmp_path / "prueba-limpia.json"
    with pytest.raises(PermissionError, match="candidata"):
        juez.abrir_prueba_limpia(None, cerrojo)
    juez.abrir_prueba_limpia("H1", cerrojo)
    with pytest.raises(PermissionError, match="una sola vez"):
        juez.abrir_prueba_limpia("H1", cerrojo)
