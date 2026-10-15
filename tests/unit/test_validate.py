"""Validacion de datos de mercado (informe seccion 2.4).

Una vela mala que entra contamina todos los indicadores. Se descarta en la
puerta.
"""

from __future__ import annotations

import pytest

from data.store.repos import Candle
from data.validate import validate_candle, validate_orderbook

NOW = 1_790_000_400_000  # alineado a 1m, 5m, 15m, 1h y 4h


def candle(**kwargs) -> Candle:
    base = {
        "symbol": "BTC/USDC",
        "timeframe": "1m",
        "ts_open_ms": NOW - 120_000,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "closed": True,
        "source": "ws",
    }
    base.update(kwargs)
    return Candle(**base)


# --- el caso bueno ---


def test_vela_normal_es_valida():
    assert validate_candle(candle(), now_ms=NOW).ok


def test_vela_doji_con_todos_los_precios_iguales_es_valida():
    v = validate_candle(
        candle(open=100.0, high=100.0, low=100.0, close=100.0), now_ms=NOW
    )
    assert v.ok


def test_volumen_cero_es_valido():
    """Un minuto sin operaciones es raro pero legitimo."""
    assert validate_candle(candle(volume=0.0), now_ms=NOW).ok


# --- coherencia interna ---


def test_high_menor_que_low_se_descarta():
    v = validate_candle(candle(high=90.0, low=110.0), now_ms=NOW)
    assert not v.ok
    assert "high" in v.reason


def test_high_por_debajo_del_close_se_descarta():
    v = validate_candle(candle(high=100.0, close=105.0), now_ms=NOW)
    assert not v.ok
    assert "high" in v.reason


def test_low_por_encima_del_open_se_descarta():
    v = validate_candle(candle(low=105.0, open=100.0, high=110.0), now_ms=NOW)
    assert not v.ok
    assert "low" in v.reason


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_precio_cero_se_descarta(field):
    v = validate_candle(candle(**{field: 0.0}), now_ms=NOW)
    assert not v.ok


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_precio_negativo_se_descarta(field):
    v = validate_candle(candle(**{field: -1.0}), now_ms=NOW)
    assert not v.ok


def test_precio_nan_se_descarta():
    v = validate_candle(candle(close=float("nan")), now_ms=NOW)
    assert not v.ok
    assert "NaN" in v.reason


def test_volumen_negativo_se_descarta():
    v = validate_candle(candle(volume=-5.0), now_ms=NOW)
    assert not v.ok
    assert "volumen" in v.reason


# --- timestamps ---


def test_timestamp_en_el_futuro_se_descarta():
    v = validate_candle(candle(ts_open_ms=NOW + 600_000), now_ms=NOW)
    assert not v.ok
    assert "futuro" in v.reason


def test_vela_fresca_se_acepta_aunque_nuestro_reloj_vaya_atrasado():
    """El caso real del 22/09/2026: el reloj local iba 10 s atrasado.

    La vela que el exchange acaba de abrir nos llega con timestamp "del
    futuro". Si la rechazasemos, nos quedariamos sin datos frescos mientras
    dure el desfase. El desfase se detecta aparte (core.clock.SkewReading).
    """
    reloj_atrasado_10s = NOW - 10_000
    v = validate_candle(candle(ts_open_ms=NOW), now_ms=reloj_atrasado_10s)
    assert v.ok


def test_desfase_absurdo_si_se_descarta():
    """Tolerar 10 s de desfase no es tolerar 10 minutos."""
    reloj_atrasado_10min = NOW - 600_000
    v = validate_candle(candle(ts_open_ms=NOW), now_ms=reloj_atrasado_10min)
    assert not v.ok
    assert "futuro" in v.reason


def test_timestamp_desalineado_se_descarta():
    """Una vela de 5m tiene que abrir en un multiplo de 5 minutos."""
    v = validate_candle(
        candle(timeframe="5m", ts_open_ms=NOW - 120_000 + 37_000), now_ms=NOW
    )
    assert not v.ok
    assert "alineado" in v.reason


def test_timestamp_cero_se_descarta():
    v = validate_candle(candle(ts_open_ms=0), now_ms=NOW)
    assert not v.ok


def test_timeframe_desconocido_se_descarta():
    v = validate_candle(candle(timeframe="7m"), now_ms=NOW)
    assert not v.ok


# --- outliers ---


def test_precio_atipico_se_descarta():
    """Un x10 en una vela de 1 m es un dato corrupto, no un movimiento."""
    v = validate_candle(
        candle(open=1000.0, high=1000.0, low=1000.0, close=1000.0),
        now_ms=NOW,
        reference_price=100.0,
    )
    assert not v.ok
    assert "atipico" in v.reason


def test_movimiento_grande_pero_plausible_se_acepta():
    """Un 20 % en cripto es un martes cualquiera."""
    v = validate_candle(
        candle(open=100.0, high=120.0, low=100.0, close=120.0),
        now_ms=NOW,
        reference_price=100.0,
    )
    assert v.ok


def test_sin_referencia_no_se_comprueba_outlier():
    v = validate_candle(
        candle(open=1000.0, high=1000.0, low=1000.0, close=1000.0), now_ms=NOW
    )
    assert v.ok


# --- libro de ordenes ---


def test_libro_normal_es_valido():
    bids = [(99.0, 1.0), (98.0, 2.0)]
    asks = [(101.0, 1.0), (102.0, 2.0)]
    assert validate_orderbook(bids, asks).ok


def test_libro_cruzado_se_descarta():
    """bid >= ask significa datos corruptos o desincronizados."""
    v = validate_orderbook([(102.0, 1.0)], [(101.0, 1.0)])
    assert not v.ok
    assert "cruzado" in v.reason


def test_libro_con_bid_igual_a_ask_se_descarta():
    v = validate_orderbook([(100.0, 1.0)], [(100.0, 1.0)])
    assert not v.ok


def test_libro_vacio_se_descarta():
    assert not validate_orderbook([], [(100.0, 1.0)]).ok
    assert not validate_orderbook([(99.0, 1.0)], []).ok


def test_bids_desordenados_se_descartan():
    v = validate_orderbook([(98.0, 1.0), (99.0, 1.0)], [(101.0, 1.0)])
    assert not v.ok
    assert "bids" in v.reason


def test_asks_desordenados_se_descartan():
    v = validate_orderbook([(99.0, 1.0)], [(102.0, 1.0), (101.0, 1.0)])
    assert not v.ok
    assert "asks" in v.reason


def test_cantidad_negativa_se_descarta():
    v = validate_orderbook([(99.0, -1.0)], [(101.0, 1.0)])
    assert not v.ok
