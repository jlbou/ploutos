"""Metricas de microestructura sobre libros sinteticos.

Con libros construidos a mano el resultado correcto se calcula a mano, asi que
estos tests detectan errores de formula, no solo excepciones.
"""

from __future__ import annotations

import pytest

from data.ingest.ws import _backoff, book_metrics


def test_spread_de_un_libro_conocido():
    """bid 99,95 / ask 100,05 -> mid 100, spread 0,10 %."""
    metrics = book_metrics([(99.95, 1.0)], [(100.05, 1.0)])
    assert metrics["mid"] == pytest.approx(100.0)
    assert metrics["spread_pct"] == pytest.approx(0.10)


def test_spread_cero_cuando_no_hay_hueco():
    metrics = book_metrics([(100.0, 1.0)], [(100.0, 1.0)])
    assert metrics["spread_pct"] == pytest.approx(0.0)


def test_libro_equilibrado_da_imbalance_cero():
    bids = [(99.0, 5.0)] * 10
    asks = [(101.0, 5.0)] * 10
    assert book_metrics(bids, asks)["imbalance"] == pytest.approx(0.0)


def test_solo_compradores_da_imbalance_uno():
    metrics = book_metrics([(99.0, 10.0)], [(101.0, 0.0)])
    assert metrics["imbalance"] == pytest.approx(1.0)


def test_solo_vendedores_da_imbalance_menos_uno():
    metrics = book_metrics([(99.0, 0.0)], [(101.0, 10.0)])
    assert metrics["imbalance"] == pytest.approx(-1.0)


def test_el_imbalance_solo_mira_el_top_10():
    """Un muro lejano no cuenta: no es liquidez accesible."""
    bids = [(100.0 - i * 0.01, 1.0) for i in range(10)] + [(90.0, 10_000.0)]
    asks = [(100.0 + i * 0.01 + 0.01, 1.0) for i in range(10)]
    assert book_metrics(bids, asks)["imbalance"] == pytest.approx(0.0)


def test_profundidad_hasta_0_5_por_ciento():
    """mid = 100, asi que la banda del bid es [99,5; 100]."""
    bids = [(99.9, 1.0), (99.6, 1.0), (99.0, 1.0)]  # el de 99,0 queda fuera
    asks = [(100.1, 1.0)]
    metrics = book_metrics(bids, asks)
    assert metrics["depth_bid_05pct"] == pytest.approx(99.9 + 99.6, rel=1e-3)


def test_la_profundidad_a_0_1_es_menor_que_a_0_5():
    bids = [(100.0 - i * 0.02, 1.0) for i in range(1, 30)]
    asks = [(100.0 + i * 0.02, 1.0) for i in range(1, 30)]
    metrics = book_metrics(bids, asks)
    assert metrics["depth_bid_01pct"] <= metrics["depth_bid_05pct"]
    assert metrics["depth_ask_01pct"] <= metrics["depth_ask_05pct"]


def test_la_profundidad_esta_en_dolares_no_en_unidades():
    """Se suma precio x cantidad, no la cantidad."""
    metrics = book_metrics([(100.0, 2.0)], [(100.2, 1.0)])
    assert metrics["depth_bid_05pct"] == pytest.approx(200.0, rel=1e-2)


def test_se_reportan_los_niveles():
    bids = [(99.0 - i, 1.0) for i in range(7)]
    asks = [(101.0 + i, 1.0) for i in range(12)]
    assert book_metrics(bids, asks)["levels"] == 7


# --- backoff de reconexion ---


def test_el_backoff_crece():
    assert _backoff(1) < _backoff(10)


def test_el_backoff_tiene_techo():
    """Sin techo, tras muchos fallos el bot tardaria horas en reintentar."""
    assert all(_backoff(50) <= 60.0 for _ in range(50))


def test_el_backoff_tiene_jitter():
    """Sin jitter, las 8 monedas reconectarian a la vez y volverian a caer."""
    delays = {_backoff(5) for _ in range(50)}
    assert len(delays) > 1


def test_el_backoff_nunca_es_cero():
    assert all(_backoff(i) > 0 for i in range(20))
