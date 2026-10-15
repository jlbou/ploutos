"""CLOSE_ONLY_DEGRADED (`core/salud.py`): entrar al momento, salir solo tras X min sano."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from core.salud import ENTRAR, SALIR, Salud, Senyales, Umbrales, evaluar

MIN = 60_000
U = Umbrales()


def pasar(salud, **k):
    return evaluar(salud, Senyales(**k))


def test_datos_obsoletos_entra_al_momento():
    salud, cambio, motivo = pasar(Salud(), ahora_ms=0, datos_obsoletos=True)
    assert cambio == ENTRAR and salud.degradado and "datos obsoletos" in motivo


def test_hacen_falta_tres_errores_seguidos_y_uno_bueno_los_borra():
    s = Salud()
    for t in range(2):
        s, cambio, _ = pasar(s, ahora_ms=t, error_exchange=True)
        assert cambio is None
    s, cambio, _ = pasar(s, ahora_ms=2, error_exchange=False)
    assert s.errores_seguidos == 0
    for t in range(3):
        s, cambio, motivo = pasar(s, ahora_ms=10 + t, error_exchange=True)
    assert cambio == ENTRAR and "3 errores seguidos" in motivo


def test_una_pasada_sin_peticion_no_borra_los_errores():
    s, _, _ = pasar(Salud(), ahora_ms=0, error_exchange=True)
    s, _, _ = pasar(s, ahora_ms=1, error_exchange=None)
    assert s.errores_seguidos == 1


def test_reloj_desfasado_en_cualquier_sentido():
    for desfase in (2_500, -2_500):                     # por encima de los 2 s (el propietario, 26/09)
        _, cambio, motivo = pasar(Salud(), ahora_ms=0, desfase_reloj_ms=desfase)
        assert cambio == ENTRAR and "reloj" in motivo
    assert pasar(Salud(), ahora_ms=0, desfase_reloj_ms=1_500)[1] is None
    assert pasar(Salud(), ahora_ms=0, desfase_reloj_ms=-407)[1] is None    # el peor medido en el VPS


def test_solo_sale_tras_diez_minutos_seguidos_sano():
    s, _, _ = pasar(Salud(), ahora_ms=0, datos_obsoletos=True)
    s, cambio, _ = pasar(s, ahora_ms=1 * MIN)           # sano desde el minuto 1
    assert cambio is None and s.degradado
    s, cambio, _ = pasar(s, ahora_ms=10 * MIN)
    assert cambio is None, "9 min sano: todavia no"
    s, cambio, motivo = pasar(s, ahora_ms=11 * MIN)
    assert cambio == SALIR and not s.degradado and "10 min" in motivo


def test_una_recaida_vuelve_a_empezar_la_cuenta():
    s, _, _ = pasar(Salud(), ahora_ms=0, datos_obsoletos=True)
    s, _, _ = pasar(s, ahora_ms=1 * MIN)
    s, cambio, _ = pasar(s, ahora_ms=8 * MIN, datos_obsoletos=True)   # recae
    assert cambio is None and s.sano_desde_ms is None
    s, _, _ = pasar(s, ahora_ms=9 * MIN)
    s, cambio, _ = pasar(s, ahora_ms=18 * MIN)
    assert cambio is None, "sano desde el 9: a los 18 son 9 min"
    assert pasar(s, ahora_ms=19 * MIN)[1] == SALIR


def test_estando_degradado_no_se_vuelve_a_entrar():
    s, _, _ = pasar(Salud(), ahora_ms=0, datos_obsoletos=True)
    s, cambio, _ = pasar(s, ahora_ms=MIN, datos_obsoletos=True)
    assert cambio is None and s.degradado


@given(st.lists(st.tuples(st.booleans(), st.sampled_from([None, True, False]),
                          st.one_of(st.none(), st.integers(-20_000, 20_000))), max_size=60))
def test_nunca_sale_mientras_haya_una_causa(pasadas):
    """Propiedad: SALIR solo en una pasada sin ninguna causa, y tras 10 min seguidos sin ellas."""
    s, ultima_con_causa = Salud(), None
    for i, (obsoletos, error, desfase) in enumerate(pasadas):
        t = i * MIN
        s, cambio, _ = evaluar(s, Senyales(t, obsoletos, error, desfase), U)
        if s.causas:
            ultima_con_causa = t
        if cambio == SALIR:
            assert not s.causas
            assert ultima_con_causa is None or t - ultima_con_causa >= U.sano_para_salir_ms


def test_el_limite_del_reloj_es_el_mismo_que_el_de_la_ingesta():
    """Decision del propietario del 26/09: UN numero para el desfase del reloj (2 s), no dos."""
    from core.config import load_settings
    from core.salud import UMBRALES
    assert UMBRALES.desfase_reloj_ms == load_settings().data.clock_skew_max_seconds * 1000
