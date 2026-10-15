"""La frase corta de por que una moneda que paso los filtros no dio candidato (panel, el propietario 29/09)."""

from __future__ import annotations

from features.regime import Regime
from strategy.candidates import Rejection
from types import SimpleNamespace

from strategy.filters import Screening
from strategy.pipeline import PipelineResult, filas_sin_senyal, motivo_sin_senyal


class Lectura:
    def __init__(self, regime):
        self.regime = regime


def rechazos(*pares):
    return [Rejection("BTC/USDC", s, g, "detalle largo que no se ensenya") for s, g in pares]


def test_ningun_setup_opera_en_ese_regimen():
    r = rechazos(("mean_reversion", "regimen"), ("pullback_trend", "regimen"), ("range_breakout", "regimen"))
    assert motivo_sin_senyal(Lectura(Regime.HIGH_VOL), r) == "muy volátil: ningún setup opera así"
    assert motivo_sin_senyal(Lectura(Regime.TREND_DOWN), r) == "tendencia bajista: ningún setup opera así"


def test_el_setup_que_opera_no_ve_su_patron():
    r = rechazos(("mean_reversion", "senyal"), ("pullback_trend", "regimen"), ("range_breakout", "regimen"))
    assert motivo_sin_senyal(Lectura(Regime.RANGE), r) == "mercado de lado: precio lejos del suelo del rango"
    r = rechazos(("mean_reversion", "regimen"), ("pullback_trend", "senyal"), ("range_breakout", "senyal"))
    assert motivo_sin_senyal(Lectura(Regime.TREND_UP), r) == "tendencia alcista: sin retroceso a la media"


def test_otra_puerta_y_sin_regimen():
    r = rechazos(("range_breakout", "R:R"))
    assert motivo_sin_senyal(Lectura(Regime.TRANSITION), r) == "cambiando de tendencia: ruptura no pasa (R:R)"
    assert motivo_sin_senyal(None, []) == "sin régimen: ningún setup opera así"


def test_es_corta():
    for regimen in Regime:
        for setup in ("pullback_trend", "range_breakout", "mean_reversion"):
            for puerta in ("regimen", "senyal", "R:R"):
                assert len(motivo_sin_senyal(Lectura(regimen), rechazos((setup, puerta)))) <= 60


def test_solo_las_que_pasan_los_filtros_y_no_dan_candidato():
    no_pasa = SimpleNamespace(passed=False, name="spread", detail="x")
    r = PipelineResult(
        candidates=(SimpleNamespace(symbol="ETH/USDC"),),
        screenings=(Screening("BTC/USDC", ()), Screening("ETH/USDC", ()), Screening("SOL/USDC", (no_pasa,))),
        rejections=tuple(rechazos(("mean_reversion", "senyal"))),
        regimes={"BTC/USDC": Lectura(Regime.RANGE), "ETH/USDC": Lectura(Regime.TREND_UP)},
    )
    assert filas_sin_senyal(r) == [("BTC/USDC", "mercado de lado: precio lejos del suelo del rango")]
