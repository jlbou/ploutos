"""Baseline sin IA.

Es la mitad de control del experimento que decide si la IA aporta algo, asi que
lo que hay que proteger aqui no es que acierte, sino que sea **simple,
reproducible y comparable**. Un baseline que se vuelve listo, o que depende del
orden en que llegan los candidatos, estropea la comparacion sin dar un solo
error.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from features.regime import Regime
from strategy.baseline import DECIDER, Choice, choose, rank
from strategy.candidates import Candidate, Generation

NOW = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)


def candidate(cid: str, rr: float, symbol: str = "ETH/USDC") -> Candidate:
    return Candidate(
        cid=cid,
        decision_id=cid,
        symbol=symbol,
        setup="pullback_trend",
        timeframe="4h",
        entry=100.0,
        stop=97.0,
        target=100.0 + 3.0 * rr,
        reward_risk=rr,
        cost_rt_pct=0.26,
        spread_pct=0.02,
        regime=Regime.TREND_UP,
        bar_ts_ms=1_756_000_000_000,
        created_at=NOW,
    )


def generation(*pairs: tuple[str, float]) -> Generation:
    return Generation(tuple(candidate(cid, rr) for cid, rr in pairs))


# --------------------------------------------------------------------------
# La regla
# --------------------------------------------------------------------------


def test_elige_el_de_mejor_reward_risk():
    g = generation(("d-a", 2.1), ("d-b", 4.7), ("d-c", 3.0))
    elegido = choose(g)
    assert elegido is not None
    assert elegido.candidate.cid == "d-b"
    assert "mejor R:R" in elegido.reason


def test_sin_candidatos_no_elige_nada():
    assert choose(Generation()) is None
    assert rank(Generation()) == []


def test_el_umbral_descarta():
    g = generation(("d-a", 1.2), ("d-b", 1.8))
    assert choose(g, min_reward_risk=2.0) is None
    assert choose(g, min_reward_risk=1.5).candidate.cid == "d-b"


def test_devuelve_la_lista_ordenada_entera():
    """Quien la recorre prueba el segundo si el primero lo veta el motor (por
    correlacion, por cooldown...). Con un solo candidato eso no se podria."""
    orden = [c.candidate.cid for c in rank(generation(("d-a", 2.0), ("d-b", 5.0), ("d-c", 3.5)))]
    assert orden == ["d-b", "d-c", "d-a"]


# --------------------------------------------------------------------------
# Lo que lo hace valido como control de un experimento
# --------------------------------------------------------------------------


def test_es_reproducible_con_empates():
    """Con dos R:R iguales, el orden NO puede depender de como llegaron.

    Sin desempate estable, dos ejecuciones sobre los mismos datos podrian
    elegir candidatos distintos, y entonces la comparacion de la fase 6 mediria
    tambien el azar.
    """
    a = rank(Generation((candidate("d-z", 3.0), candidate("d-a", 3.0))))
    b = rank(Generation((candidate("d-a", 3.0), candidate("d-z", 3.0))))
    assert [c.candidate.cid for c in a] == [c.candidate.cid for c in b] == ["d-a", "d-z"]


def test_nunca_reduce_el_tamanyo():
    """`size_multiplier` es la palanca de la IA (PRD seccion 6). Si el baseline
    la usara, dejaria de ser el mismo experimento con una sola variable."""
    for opcion in rank(generation(("d-a", 2.0), ("d-b", 9.0))):
        assert opcion.size_multiplier == 1.0


def test_no_declara_confianza():
    """La confianza calibrada es cosa de la IA. El baseline no opina."""
    assert choose(generation(("d-a", 3.0))).confidence is None


def test_queda_marcado_como_baseline():
    """Para poder separar sus operaciones de las de la IA en el journal."""
    assert choose(generation(("d-a", 3.0))).decider == DECIDER


def test_la_eleccion_arrastra_el_decision_id():
    """PRD seccion 13: candidato -> IA/baseline -> veredicto -> orden -> cierre."""
    elegido = choose(generation(("d-abc", 3.0)))
    assert elegido.decision_id == "d-abc" == elegido.candidate.decision_id


def test_la_eleccion_tiene_la_misma_forma_que_tendra_la_de_la_ia():
    """Lo que permite enchufar una u otra sin tocar el resto del bucle."""
    elegido = choose(generation(("d-a", 3.0)))
    assert isinstance(elegido, Choice)
    for campo in ("candidate", "size_multiplier", "confidence", "reason", "decider"):
        assert hasattr(elegido, campo)


def test_no_mira_la_cartera():
    """Ordenar candidatos no necesita saber que hay abierto. Quien decide si
    caben es `risk/engine.py`, y mezclarlo aqui duplicaria esa autoridad."""
    import inspect

    from strategy import baseline

    firma = inspect.signature(baseline.rank)
    assert set(firma.parameters) == {"generation", "min_reward_risk"}


@pytest.mark.parametrize("n", [1, 2, 5, 20])
def test_el_orden_es_siempre_decreciente(n: int):
    g = Generation(tuple(candidate(f"d-{i:02d}", 2.0 + i * 0.3) for i in range(n)))
    valores = [c.candidate.reward_risk for c in rank(g)]
    assert valores == sorted(valores, reverse=True)
