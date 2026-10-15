"""Los avisos enchufados al bucle: que se generan, que se guardan una vez y que
se mandan sin poder tumbar nada (`notify/outbox.py`, 24/09/2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.config import DrawdownTier, load_settings
from core.modes import Mode, ModeChange
from core.secrets import Secrets
from notify import outbox
from notify.telegram import Envio
from portfolio import store
from portfolio.paper import ExitReason, PaperTrade

T0 = 1_790_035_200_000          # 22/09/2026 00:00 UTC
HORA = 3_600_000
ESCALONES = (DrawdownTier(equity_below_usd=45.0, risk_multiplier=0.5),)


def test_ningun_test_ve_las_credenciales_de_telegram():
    """La guarda de tests/conftest.py: sin ella, pasar los tests mandaria mensajes
    de verdad al movil del propietario."""
    s = Secrets()
    assert not s.has_telegram and not s.has_telegram_chat


@pytest.fixture
def base(tmp_path: Path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def pausas(monkeypatch):
    """Las pausas entre mensajes se apuntan en vez de esperarse."""
    apuntadas = []
    monkeypatch.setattr(outbox.time, "sleep", apuntadas.append)
    return apuntadas


def con_historia(base, desde=T0):
    """Una vela guardada: la cartera ya existia ese dia."""
    with base:
        base.execute("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                     (desde, 50.0, 0, 0))


def operacion():
    return PaperTrade(
        decision_id="d-20260922T0000-eth-pb", symbol="ETH/USDC", setup="pullback_trend",
        qty=0.15, entry_price=100.0, exit_price=97.0, stop_price=97.0, target_price=106.0,
        opened_ts_ms=T0, closed_ts_ms=T0 + 8 * HORA, reason=ExitReason.STOP,
        entry_fee_usd=0.015, exit_fee_usd=0.02, exit_was_maker=False, mae_pct=-3.0, mfe_pct=1.0,
    )


def avisos(**kw):
    base = dict(ts_ms=T0, cartera="baseline", cerradas=(), cambios=(), canceladas=0,
                equity_anterior=50.0, equity=50.0, escalones=ESCALONES)
    base.update(kw)
    return outbox.avisos_de_la_vela(**base)


# --------------------------------------------------------------------------
# Que avisos produce una vela
# --------------------------------------------------------------------------


def test_una_vela_tranquila_no_avisa():
    assert avisos() == []


def test_cada_cosa_que_pasa_da_su_aviso():
    cambio = ModeChange(None, Mode.CLOSE_ONLY_DAILY, True, "regla 10", Mode.NORMAL, Mode.CLOSE_ONLY_DAILY)
    journal = [({"outcome": "auth", "called_ms": T0 + 60_000, "reason": "Not logged in"}, [])]
    lista = avisos(cerradas=[operacion()], cambios=[cambio], canceladas=2,
                   equity_anterior=45.3, equity=44.8, journal=journal, cartera="ai")
    tipos = [t for t, _c, _x in lista]
    assert tipos == ["operacion", "modo", "escalon", "auth"]
    claves = [c for _t, c, _x in lista]
    assert len(set(claves)) == 4 and all(c.startswith("ai:") for c in claves)
    assert "canceladas: 2" in lista[1][2]


def test_un_aviso_no_entra_dos_veces(base):
    aviso = avisos(cerradas=[operacion()])
    store.encolar_avisos(base, T0, aviso)
    store.encolar_avisos(base, T0, aviso)
    assert base.execute("SELECT COUNT(*) FROM paper_avisos").fetchone()[0] == 1


# --------------------------------------------------------------------------
# Mandarlos
# --------------------------------------------------------------------------


class Telegram:
    def __init__(self, fallar_en=None):
        self.fallar_en, self.mandados = fallar_en, []

    def __call__(self, token, chat_id, texto, timeout):
        assert timeout <= 10, "timeout corto: el bucle no puede quedarse esperando"
        if self.fallar_en is not None and len(self.mandados) == self.fallar_en:
            return Envio(False, "HTTP 502")
        self.mandados.append(texto)
        return Envio(True, "enviado")


def encolar(base, n, ts=T0):
    store.encolar_avisos(base, ts, [("operacion", f"k{i}", f"aviso {i}") for i in range(n)])


def test_sin_credenciales_no_se_intenta(base):
    encolar(base, 2)
    tg = Telegram()
    assert outbox.enviar_pendientes(base, None, "1", T0, _send=tg)[1] == "sin credenciales de Telegram"
    assert tg.mandados == []


def test_manda_en_orden_y_los_marca(base, pausas):
    encolar(base, 3)
    tg = Telegram()
    assert outbox.enviar_pendientes(base, "t", "1", T0 + HORA, _send=tg) == (3, None)
    assert pausas == [outbox.PAUSA_S] * 2, "uno por segundo: Telegram corta las rafagas"
    assert tg.mandados == ["aviso 0", "aviso 1", "aviso 2"]
    assert outbox.enviar_pendientes(base, "t", "1", T0 + HORA, _send=tg) == (0, None), "no se repiten"


def test_para_en_el_primer_fallo_y_reintenta_despues(base):
    encolar(base, 3)
    enviados, error = outbox.enviar_pendientes(base, "t", "1", T0 + HORA, _send=Telegram(fallar_en=1))
    assert (enviados, error) == (1, "HTTP 502")
    fila = base.execute("SELECT intentos, ultimo_error FROM paper_avisos WHERE clave = 'k1'").fetchone()
    assert tuple(fila) == (1, "HTTP 502")
    tg = Telegram()
    assert outbox.enviar_pendientes(base, "t", "1", T0 + HORA, _send=tg) == (2, None)
    assert tg.mandados == ["aviso 1", "aviso 2"]


def test_como_mucho_unos_pocos_por_vuelta(base):
    encolar(base, outbox.MAX_POR_VUELTA + 3)
    assert outbox.enviar_pendientes(base, "t", "1", T0 + HORA, _send=Telegram())[0] == outbox.MAX_POR_VUELTA


def test_los_viejos_se_descartan_en_vez_de_mandarse(base):
    """Telegram caido 13 h, o credenciales puestas tarde: no llegan como si fueran de ahora."""
    encolar(base, 2, ts=T0)
    tg = Telegram()
    outbox.enviar_pendientes(base, "t", "1", T0 + 13 * HORA, _send=tg)
    assert tg.mandados == []
    assert base.execute("SELECT SUM(descartado) FROM paper_avisos").fetchone()[0] == 2


# --------------------------------------------------------------------------
# El resumen diario
# --------------------------------------------------------------------------


def test_el_resumen_de_ayer_sale_una_vez_y_a_su_hora(base):
    con_historia(base)
    settings = load_settings()
    manana = int(datetime(2026, 9, 23, tzinfo=UTC).timestamp() * 1000)
    assert outbox.resumen_si_toca(base, "baseline", manana + 5 * 60_000, settings) is None, "aun no"
    aviso = outbox.resumen_si_toca(base, "baseline", manana + 15 * 60_000, settings)
    assert aviso is not None and aviso[1] == "baseline:resumen:2026-09-22"
    store.encolar_avisos(base, manana, [aviso])
    assert outbox.resumen_si_toca(base, "baseline", manana + 20 * 60_000, settings) is None


def _con_token(caduca):
    s = load_settings()
    return s.model_copy(update={"claude": s.claude.model_copy(update={"token_expires_on": caduca})})


def test_el_token_por_caducar_va_en_el_resumen_de_la_ia(base):
    from datetime import date
    con_historia(base)
    dia = int(datetime(2027, 9, 10, tzinfo=UTC).timestamp() * 1000) + 15 * 60_000
    aviso = outbox.resumen_si_toca(base, "ai", dia, _con_token(date(2027, 9, 22)))
    assert "caduca el 22/09/2027" in aviso[2] and "12 día" in aviso[2]
    base_aviso = outbox.resumen_si_toca(base, "baseline", dia, _con_token(date(2027, 9, 22)))
    assert "caduca" not in base_aviso[2], "solo en el de la IA: no por duplicado"


def test_lejos_de_caducar_no_se_dice(base):
    from datetime import date
    con_historia(base)
    dia = int(datetime(2027, 3, 1, tzinfo=UTC).timestamp() * 1000) + 15 * 60_000
    assert "caduca" not in outbox.resumen_si_toca(base, "ai", dia, _con_token(date(2027, 9, 22)))[2]


def test_la_configuracion_real_tiene_la_fecha():
    from datetime import date
    assert load_settings().claude.token_expires_on == date(2027, 9, 22)


def test_sin_historia_de_ayer_no_hay_resumen_inventado(base):
    """Revision del 24/09: arrancar a las 17:00 y "resumir" el dia anterior, que no existio."""
    settings = load_settings()
    hoy_17 = T0 + 17 * HORA                      # 22/09 17:00
    con_historia(base, desde=T0 + 16 * HORA)     # primera vela: hoy a las 16:00
    assert outbox.resumen_si_toca(base, "baseline", hoy_17, settings) is None
    manana = T0 + 24 * HORA + 15 * 60_000        # 23/09 00:15: el 22 si existio
    assert outbox.resumen_si_toca(base, "baseline", manana, settings) is not None


def test_sin_nada_pendiente_no_escribe(base):
    """Lo normal, cada minuto: ni descarta ni escribe."""
    assert outbox.enviar_pendientes(base, "t", "1", T0, _send=Telegram()) == (0, None)


# --------------------------------------------------------------------------
# Regla 17: avisar cuando la paridad empieza o deja de bloquear (01/10/2026)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("antes", "ahora", "sale"), [
    (False, True, True),    # empieza a bloquear
    (True, False, True),    # se recupera
    (True, True, False),    # sigue bloqueada: no se repite cada 4 h
    (False, False, False),  # todo normal
    (None, True, True),     # primera vela de la cartera ya bloqueada: se dice
    (None, False, False),   # primera vela, normal: nada
])
def test_la_paridad_avisa_solo_al_cambiar(antes, ahora, sale):
    lista = avisos(paridad=(antes, ahora, "faltan precios: USDT/USD", 1.5))
    assert [t for t, _c, _x in lista] == (["paridad"] if sale else [])
    if sale:
        texto = lista[0][2]
        assert ("sin entradas" in texto) if ahora else ("recuperada" in texto)
        assert "USDT/USD" in texto


def test_sin_lectura_de_paridad_no_avisa():
    assert avisos(paridad=None) == []
