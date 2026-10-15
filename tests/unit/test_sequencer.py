"""Deteccion de velas cerradas a partir del flujo del WebSocket.

Contexto (bug real encontrado el 22/09/2026): `watch_ohlcv` de ccxt devuelve
SOLO la vela en curso. Con la primera version, basada en nuestro reloj, la
ingesta corrio 7 minutos y no guardo NI UNA vela del WebSocket.

Estos tests fijan el comportamiento correcto para que no vuelva a pasar.
"""

from __future__ import annotations

from data.ingest.sequencer import CandleSequencer

MIN = 60_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % MIN)


def row(ts: int, close: float = 100.0) -> list[float]:
    return [ts, 100.0, 101.0, 99.0, close, 10.0]


# --- el mecanismo principal ---


def test_la_primera_vela_no_cierra_nada():
    """Al arrancar solo hay una vela en curso: nada que cerrar todavia."""
    assert CandleSequencer("1m").feed([row(T0)]) == []


def test_actualizar_la_misma_vela_no_la_cierra():
    """El WebSocket manda la vela en curso muchas veces por minuto."""
    seq = CandleSequencer("1m")
    seq.feed([row(T0, 100.0)])
    assert seq.feed([row(T0, 101.0)]) == []
    assert seq.feed([row(T0, 102.0)]) == []
    assert seq.pending_ts == T0


def test_la_vela_siguiente_cierra_la_anterior():
    """LA REGLA: si el exchange pasa pagina, la anterior esta cerrada."""
    seq = CandleSequencer("1m")
    seq.feed([row(T0, 100.0)])
    closed = seq.feed([row(T0 + MIN, 105.0)])
    assert len(closed) == 1
    assert int(closed[0][0]) == T0
    assert seq.pending_ts == T0 + MIN


def test_se_cierra_con_el_ultimo_valor_visto():
    """La vela cerrada tiene que llevar su cierre final, no el primero."""
    seq = CandleSequencer("1m")
    seq.feed([row(T0, 100.0)])
    seq.feed([row(T0, 103.0)])
    seq.feed([row(T0, 107.5)])  # ultimo valor antes de cerrar
    closed = seq.feed([row(T0 + MIN)])
    assert closed[0][4] == 107.5


def test_varias_velas_seguidas_se_cierran_en_orden():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    for i in range(1, 5):
        closed = seq.feed([row(T0 + i * MIN)])
        assert len(closed) == 1
        assert int(closed[0][0]) == T0 + (i - 1) * MIN


def test_un_mensaje_con_varias_velas_cierra_todas_menos_la_ultima():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    closed = seq.feed([row(T0 + MIN), row(T0 + 2 * MIN), row(T0 + 3 * MIN)])
    assert [int(c[0]) for c in closed] == [T0, T0 + MIN, T0 + 2 * MIN]
    assert seq.pending_ts == T0 + 3 * MIN


def test_un_mensaje_desordenado_se_ordena():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    closed = seq.feed([row(T0 + 2 * MIN), row(T0 + MIN)])
    assert [int(c[0]) for c in closed] == [T0, T0 + MIN]


def test_una_vela_vieja_se_ignora():
    """Un mensaje retrasado no puede reabrir una vela ya pasada."""
    seq = CandleSequencer("1m")
    seq.feed([row(T0 + MIN)])
    assert seq.feed([row(T0)]) == []
    assert seq.pending_ts == T0 + MIN


def test_un_mensaje_vacio_no_hace_nada():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    assert seq.feed([]) == []
    assert seq.pending_ts == T0


# --- inmunidad al desfase de reloj ---


def test_funciona_con_el_reloj_completamente_roto():
    """El motivo de este disenyo: no se consulta el reloj en ningun momento.

    Con la version anterior, 10 s de desfase bastaban para perder todas las
    velas. Aqui el reloj no interviene.
    """
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    closed = seq.feed([row(T0 + MIN)])
    assert len(closed) == 1


# --- red de seguridad ---


def test_sin_vela_pendiente_no_hay_nada_que_vaciar():
    assert CandleSequencer("1m").flush_if_stale(T0 + 10 * MIN) is None


def test_una_vela_reciente_no_se_vacia():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    assert seq.flush_if_stale(T0 + MIN) is None
    assert seq.pending_ts == T0


def test_una_vela_colgada_demasiado_tiempo_se_vacia():
    """Si una moneda deja de emitir, su ultima vela no se queda ahi para siempre."""
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    stale = seq.flush_if_stale(T0 + 4 * MIN)
    assert stale is not None
    assert int(stale[0]) == T0
    assert seq.pending_ts is None


def test_vaciar_dos_veces_no_duplica():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    assert seq.flush_if_stale(T0 + 4 * MIN) is not None
    assert seq.flush_if_stale(T0 + 8 * MIN) is None


def test_la_red_de_seguridad_escala_con_el_timeframe():
    """Una vela de 4 h no esta colgada por llevar 4 minutos."""
    seq = CandleSequencer("4h")
    seq.feed([row(T0)])
    assert seq.flush_if_stale(T0 + 4 * MIN) is None
    assert seq.flush_if_stale(T0 + 13 * 3600 * 1000) is not None


def test_despues_de_vaciar_se_sigue_secuenciando():
    seq = CandleSequencer("1m")
    seq.feed([row(T0)])
    seq.flush_if_stale(T0 + 4 * MIN)
    seq.feed([row(T0 + 5 * MIN)])
    closed = seq.feed([row(T0 + 6 * MIN)])
    assert int(closed[0][0]) == T0 + 5 * MIN
