"""Las paradas conocidas (core/paradas.py): un hueco solo se justifica si cabe entero en una."""

from __future__ import annotations

from datetime import UTC, datetime

from core import paradas
from core.paradas import PARADAS_CONOCIDAS, Parada, justificada

MIN = 60_000
A = int(datetime(2026, 10, 19, 8, 0, tzinfo=UTC).timestamp() * 1000)
P = Parada(desde_ms=A, hasta_ms=A + 30 * MIN, motivo="prueba")


def test_un_hueco_dentro_de_la_parada_se_justifica():
    assert justificada(A + 5 * MIN, A + 25 * MIN, (P,)) is P


def test_los_bordes_cuentan_como_dentro():
    assert justificada(A, A + 30 * MIN, (P,)) is P


def test_un_hueco_que_empieza_dentro_y_acaba_fuera_no_se_justifica():
    assert justificada(A + 25 * MIN, A + 45 * MIN, (P,)) is None


def test_un_hueco_que_empieza_antes_de_la_parada_no_se_justifica():
    assert justificada(A - MIN, A + 20 * MIN, (P,)) is None


def test_sin_paradas_no_se_justifica_nada():
    assert justificada(A, A + MIN, ()) is None


def test_se_usa_la_lista_del_modulo_si_no_se_pasa_otra(monkeypatch):
    monkeypatch.setattr(paradas, "PARADAS_CONOCIDAS", (P,))
    assert justificada(A + MIN, A + 2 * MIN) is P


def test_la_parada_real_del_19_10_cubre_los_huecos_vistos_y_nada_mas():
    def ms(h, m, s=0):
        return int(datetime(2026, 10, 19, h, m, s, tzinfo=UTC).timestamp() * 1000)

    assert len(PARADAS_CONOCIDAS) == 1
    assert justificada(ms(8, 42, 49), ms(9, 14, 33)) is not None      # noticias
    assert justificada(ms(8, 42, 58), ms(9, 14, 58)) is not None      # comandos de Telegram
    assert justificada(ms(8, 42, 49), ms(9, 30)) is None              # un hueco mas largo, no
    assert justificada(ms(8, 0), ms(8, 50)) is None                   # otro dia/otra hora, no


def test_toda_parada_tiene_ventana_valida_y_motivo():
    for p in PARADAS_CONOCIDAS:
        assert p.desde_ms < p.hasta_ms
        assert p.motivo.strip()
        assert p.hasta_ms - p.desde_ms <= 6 * 3600_000       # ventana ajustada, nunca "ese dia"
