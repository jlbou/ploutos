"""Los avisos de Telegram: el cliente, los textos y el resumen diario.

Lo que mas importa, por orden: que el token no salga NUNCA en un error, que
enviar no lance nunca (un aviso que falla no puede tumbar al que avisa) y que
cada aviso lleve lo que pide el PRD seccion 9.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from datetime import date
from pathlib import Path

import pytest

from core.config import DrawdownTier, load_settings
from core.modes import Mode, ModeChange
from notify import messages as m
from notify.resumen import resumen_desde_base
from notify.telegram import MAX_LEN, recortar, send_message
from portfolio import store
from portfolio.paper import ExitReason, PaperTrade

TOKEN = "8123456789:AAH-token-de-mentira-que-no-puede-salir"
CHAT = "123456"
T0 = 1_790_035_200_000          # 22/09/2026 00:00 UTC
HORA = 3_600_000


# --------------------------------------------------------------------------
# El cliente
# --------------------------------------------------------------------------


class Opener:
    """Hace de `urllib.request.urlopen`: apunta la peticion y responde lo que toque."""

    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta if respuesta is not None else {"ok": True, "result": {}}
        self.error = error
        self.peticiones = []

    def __call__(self, request, timeout):
        self.peticiones.append(request)
        if self.error is not None:
            raise self.error
        return io.BytesIO(json.dumps(self.respuesta).encode())


def test_envia_con_formato_html_al_chat_configurado():
    """HTML y no Markdown: con Markdown, el _ de pullback_trend rompe el mensaje."""
    abrir = Opener()
    envio = send_message(TOKEN, CHAT, "<b>hola</b> pullback_trend", _open=abrir)
    assert envio.ok
    [peticion] = abrir.peticiones
    cuerpo = urllib.parse.parse_qs(peticion.data.decode())
    assert cuerpo["chat_id"] == ["123456"]
    assert cuerpo["parse_mode"] == ["HTML"]


class OpenerQueRechazaHtml(Opener):
    """La primera peticion falla como si el HTML estuviera mal; la segunda va bien."""

    def __call__(self, request, timeout):
        self.peticiones.append(request)
        if len(self.peticiones) == 1:
            cuerpo = json.dumps({"ok": False, "description": "Bad Request: can't parse entities"})
            raise urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(cuerpo.encode()))
        return io.BytesIO(json.dumps({"ok": True, "result": {}}).encode())


def test_si_telegram_rechaza_el_html_se_reenvia_en_texto_plano():
    """Un aviso feo es mejor que un aviso que no llega."""
    abrir = OpenerQueRechazaHtml()
    envio = send_message(TOKEN, CHAT, "<b>Equity</b> 44,80 $ &amp; algo", _open=abrir)
    assert envio.ok and "texto plano" in envio.detalle
    segundo = urllib.parse.parse_qs(abrir.peticiones[1].data.decode())
    assert "parse_mode" not in segundo
    assert segundo["text"] == ["Equity 44,80 $ & algo"]


def test_un_error_http_no_ensenya_el_token():
    cuerpo = json.dumps({"ok": False, "description": f"Unauthorized for /bot{TOKEN}/sendMessage"})
    error = urllib.error.HTTPError(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage", 401, "Unauthorized", {},
        io.BytesIO(cuerpo.encode()),
    )
    envio = send_message(TOKEN, CHAT, "x", _open=Opener(error=error))
    assert not envio.ok
    assert TOKEN not in envio.detalle
    assert "401" in envio.detalle


def test_un_error_de_red_no_ensenya_el_token_ni_lanza():
    error = urllib.error.URLError(f"timeout conectando a https://api.telegram.org/bot{TOKEN}/x")
    envio = send_message(TOKEN, CHAT, "x", _open=Opener(error=error))
    assert not envio.ok
    assert TOKEN not in envio.detalle


def test_una_respuesta_con_ok_false_no_lanza():
    envio = send_message(TOKEN, CHAT, "x", _open=Opener(respuesta={"ok": False, "description": "chat not found"}))
    assert not envio.ok and "chat not found" in envio.detalle


def test_sin_credenciales_no_llama_y_lo_dice():
    abrir = Opener()
    assert not send_message(None, CHAT, "x", _open=abrir).ok
    assert not send_message(TOKEN, "", "x", _open=abrir).ok
    assert abrir.peticiones == []


def test_un_texto_demasiado_largo_se_recorta_no_se_pierde():
    texto = "a" * (MAX_LEN + 500)
    recortado = recortar(texto)
    assert len(recortado) == MAX_LEN
    assert recortado.endswith("recortado]")
    assert recortar("corto") == "corto"


# --------------------------------------------------------------------------
# Los textos
# --------------------------------------------------------------------------


def operacion(reason=ExitReason.TARGET, salida=106.0):
    return PaperTrade(
        decision_id="d-20260922T0000-eth-pb", symbol="ETH/USDC", setup="pullback_trend",
        qty=0.15, entry_price=100.0, exit_price=salida, stop_price=97.0, target_price=106.0,
        opened_ts_ms=T0, closed_ts_ms=T0 + 28 * HORA, reason=reason,
        entry_fee_usd=0.015, exit_fee_usd=0.0159, exit_was_maker=True, mae_pct=-1.0, mfe_pct=6.0,
    )


def test_la_operacion_cerrada_lleva_lo_que_pide_el_prd():
    """PRD seccion 9: par, resultado en $ y en R, motivo, duracion."""
    texto = m.operacion_cerrada(operacion(), "baseline")
    assert texto.startswith("🟢") and "Baseline" in texto
    assert "ETH/USDC" in texto
    assert "+0,87 $" in texto               # 0,9 bruto - 0,0309 de comisiones
    assert "+1,93 R" in texto               # 0,869 / 0,45 de riesgo planificado
    assert "objetivo" in texto
    assert "1 d 4 h" in texto
    assert "d-20260922T0000-eth-pb" in texto, "la trazabilidad: el decision_id"


def test_llenada_y_cerrada_en_la_misma_vela_no_inventa_una_duracion():
    """Caso real del 23/09 (ETH, stop): se lleno y salto en la misma vela de 4 h.
    Las marcas son aperturas de vela: no se sabe si tardo 5 minutos o 3 horas."""
    trade = operacion(ExitReason.STOP, salida=97.0)
    campos = {f: getattr(trade, f) for f in PaperTrade.__dataclass_fields__}
    misma = PaperTrade(**{**campos, "closed_ts_ms": trade.opened_ts_ms})
    texto = m.operacion_cerrada(misma, "baseline")
    assert "dentro de la misma vela" in texto
    assert "menos de 1 h" not in texto


def test_un_stop_se_dice_stop_y_con_signo_negativo():
    texto = m.operacion_cerrada(operacion(ExitReason.STOP, salida=97.0), "ai")
    assert texto.startswith("🔴") and "🤖 IA" in texto
    assert "stop" in texto and "-0,48 $" in texto


def cambio(modo, activado, antes=Mode.NORMAL, despues=None):
    return ModeChange(
        ts=None, mode=modo, activated=activado, reason="motivo de prueba",
        effective_before=antes, effective_after=despues or (modo if activado else Mode.NORMAL),
    )


def test_capital_avisa_de_que_es_enclavado_y_como_se_sale():
    texto = m.cambio_de_modo(cambio(Mode.CLOSE_ONLY_CAPITAL, True), "baseline", canceladas=2)
    assert "Entra en CLOSE_ONLY_CAPITAL" in texto and texto.startswith("🚨")
    assert "ENCLAVADO" in texto and "--reset-capital" in texto
    assert "Entradas pendientes canceladas: 2" in texto
    assert "Sin entradas nuevas" in texto


def test_salir_a_normal_no_dice_sin_entradas():
    texto = m.cambio_de_modo(
        cambio(Mode.CLOSE_ONLY_QUOTA, False, antes=Mode.CLOSE_ONLY_QUOTA), "ai",
    )
    assert "Sale de CLOSE_ONLY_QUOTA" in texto and texto.startswith("✅")
    assert "→ <code>NORMAL</code>" in texto
    assert "Sin entradas nuevas" not in texto


ESCALONES = (
    DrawdownTier(equity_below_usd=45.0, risk_multiplier=0.5),
    DrawdownTier(equity_below_usd=40.0, risk_multiplier=0.5, max_positions=2),
    DrawdownTier(equity_below_usd=35.0, risk_multiplier=0.5, max_positions=1),
)


@pytest.mark.parametrize(
    ("antes", "ahora", "esperado"),
    [
        (46.0, 44.9, (45.0, True)),
        (44.9, 46.0, (45.0, False)),
        (46.0, 39.0, (40.0, True)),     # dos de golpe: el mas grave
        (39.0, 46.0, (40.0, False)),    # dos de golpe hacia arriba: el que deja atras
        (44.0, 43.0, None),             # dentro del mismo escalon: no se repite
        (None, 30.0, None),             # arranque: no hay cruce
    ],
)
def test_solo_se_avisa_al_cruzar_un_escalon(antes, ahora, esperado):
    cruce = m.escalon_cruzado(antes, ahora, ESCALONES)
    if esperado is None:
        assert cruce is None
    else:
        escalon, bajando = cruce
        assert (escalon.equity_below_usd, bajando) == esperado


def test_el_aviso_de_escalon_dice_que_cambia():
    texto = m.aviso_escalon("baseline", 39.5, ESCALONES[1], bajando=True)
    assert "39,50 $" in texto and "40,00 $" in texto
    assert "×0,5" in texto and "máximo 2" in texto
    assert "regla 9" in texto


@pytest.mark.parametrize(
    ("hoy", "contiene"),
    [
        (date(2027, 9, 1), None),
        (date(2027, 9, 8), "14 día"),
        (date(2027, 9, 22), "0 día"),
        (date(2027, 9, 23), "CADUCÓ"),
    ],
)
def test_el_token_se_avisa_14_dias_antes(hoy, contiene):
    texto = m.token_por_caducar(date(2027, 9, 22), hoy)
    if contiene is None:
        assert texto is None
    else:
        assert contiene in texto and "22/09/2027" in texto


def test_el_error_de_autenticacion_no_pide_el_token_por_el_chat():
    texto = m.error_autenticacion("la IA", "Not logged in")
    assert "nunca por el chat" in texto


# --------------------------------------------------------------------------
# El resumen diario, desde una base de papel
# --------------------------------------------------------------------------


@pytest.fixture
def base(tmp_path: Path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    with c:
        # Ayer termino en 50,20; hoy 50,20 -> 49,80 -> 49,37.
        c.executemany(
            "INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
            [(T0 - 4 * HORA, 50.20, 0, 0), (T0 + 4 * HORA, 49.80, 2, 0), (T0 + 8 * HORA, 49.37, 3, 0)],
        )
        c.execute(
            "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("d-x", "XRP/USDC", "pullback_trend", "baseline", 10.0, 1.0, 0.97, 0.97, 1.1,
             T0 + HORA, T0 + 6 * HORA, "stop", 0.01, 0.0194, 0, -3.0, 1.0, -0.33, -1.1),
        )
    yield c
    c.close()


def test_el_resumen_sale_de_lo_guardado(base):
    r = resumen_desde_base(base, "baseline", date(2026, 9, 22), load_settings())
    assert r.equity_usd == pytest.approx(49.37)
    assert r.cambio_dia_usd == pytest.approx(49.37 - 50.20)
    assert r.drawdown_max_pct == pytest.approx((50.20 - 49.37) / 50.20 * 100)
    assert (r.cerradas_hoy, r.resultado_hoy_usd) == (1, pytest.approx(-0.33))
    assert (r.posiciones, r.max_posiciones, r.modo) == (3, 3, "NORMAL")
    assert r.llamadas_claude is None, "el baseline no tiene presupuesto de Claude"


def test_el_resumen_de_la_ia_cuenta_las_llamadas_hechas(base):
    """El fallo cuenta (gasto cuota); lo que no se llamo, no. La tabla es de
    005_ai.sql (rama de la fase 3): si esta base no la tiene, se crea la minima."""
    with base:
        base.execute(
            "CREATE TABLE IF NOT EXISTS ai_calls (id INTEGER PRIMARY KEY, ts_ms INTEGER,"
            " called_ms INTEGER, kind TEXT, outcome TEXT, valid INTEGER, reason TEXT,"
            " n_candidates INTEGER)"
        )
        base.executemany(
            "INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates)"
            " VALUES (?,?,?,?,?,?,?)",
            [(T0, T0 + HORA, "decision", "ok", 1, "ok", 2),
             (T0, T0 + 2 * HORA, "decision", "timeout", 0, "x", 2),
             (T0, T0 + 3 * HORA, "decision", "skipped_budget", 0, "x", 2),
             (T0, T0 + 4 * HORA, "decision", "skipped_stale", 0, "x", 2),
             (T0, T0 + 30 * HORA, "decision", "ok", 1, "ok", 2)],     # otro dia
        )
    r = resumen_desde_base(base, "ai", date(2026, 9, 22), load_settings())
    assert (r.llamadas_claude, r.presupuesto_claude) == (2, 40)


def test_una_base_sin_tabla_de_la_ia_son_cero_llamadas(base):
    with base:
        base.execute("DROP TABLE IF EXISTS ai_decisions")
        base.execute("DROP TABLE IF EXISTS ai_calls")
    assert resumen_desde_base(base, "ai", date(2026, 9, 22), load_settings()).llamadas_claude == 0


def test_el_texto_del_resumen():
    r = m.ResumenCartera(
        cartera="ai", equity_usd=50.1, cambio_dia_usd=0.1, drawdown_max_pct=0.4,
        cerradas_hoy=0, resultado_hoy_usd=0.0, posiciones=1, max_posiciones=3,
        modo="NORMAL", ultima_vela_ms=T0 + 16 * HORA, llamadas_claude=3, presupuesto_claude=40,
    )
    texto = m.resumen_diario(date(2026, 9, 22), [r], extra=["token: ok"])
    assert "Resumen del 22/09/2026" in texto
    assert "🤖 IA" in texto and "50,10 $  (+0,10 $ hoy)" in texto
    assert "3/40 llamadas" in texto
    assert "22/09 16:00 UTC" in texto
    assert texto.endswith("token: ok")


# --------------------------------------------------------------------------
# Que Telegram entienda el HTML de TODOS los avisos
# --------------------------------------------------------------------------


class Etiquetas(HTMLParser):
    """Comprueba el subconjunto de HTML de Telegram que usamos: b, i, code, pre,
    bien cerradas. Telegram rechaza el mensaje entero con una etiqueta mal."""

    PERMITIDAS = {"b", "i", "code", "pre", "a"}   # <a href> lo admite el HTML de Telegram

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pila, self.errores = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.PERMITIDAS:
            self.errores.append(f"etiqueta no permitida: {tag}")
        self.pila.append(tag)

    def handle_endtag(self, tag):
        if not self.pila or self.pila.pop() != tag:
            self.errores.append(f"cierre desparejado: {tag}")


def _todos_los_avisos():
    r = m.ResumenCartera("ai", 50.1, 0.1, 0.4, 0, 0.0, 1, 3, "NORMAL", T0, 3, 40)
    return {
        "operacion": m.operacion_cerrada(operacion(), "baseline"),
        "stop": m.operacion_cerrada(operacion(ExitReason.STOP, salida=97.0), "ai"),
        "capital": m.cambio_de_modo(cambio(Mode.CLOSE_ONLY_CAPITAL, True), "baseline", 2),
        "sale": m.cambio_de_modo(cambio(Mode.CLOSE_ONLY_QUOTA, False, antes=Mode.CLOSE_ONLY_QUOTA), "ai"),
        "baja": m.aviso_escalon("baseline", 39.5, ESCALONES[1], True),
        "sube": m.aviso_escalon("baseline", 46.0, ESCALONES[0], False),
        "token": m.token_por_caducar(date(2027, 9, 22), date(2027, 9, 10)),
        "caducado": m.token_por_caducar(date(2027, 9, 22), date(2027, 9, 30)),
        "auth": m.error_autenticacion("la IA", "Not logged in <x>"),
        "parado": m.bot_parado("ploutos-paper", "SIGTERM & reinicio"),
        "resumen": m.resumen_diario(date(2026, 9, 22), [r]),
        "deslistado": m.aviso_noticia("NEAR/USDC", "delisting", "critica", "OKX to delist NEAR",
                                      url="https://my.okx.com/en-eu/help/x", vendidas=("baseline", "ai")),
        "volatilidad": m.aviso_noticia("DOGE/USDC", "volatility", "alta", "Price Volatility of DOGE",
                                       hasta_ms=T0 + 24 * HORA),
        "pendientes": m.noticias_pendientes([("NEAR/USDC", "delisting", T0, "x")], T0 + 50 * HORA),
        "fuente": m.fuente_noticias_caida(T0, T0 + 2 * HORA),
    }


@pytest.mark.parametrize("nombre", sorted(_todos_los_avisos()))
def test_cada_aviso_es_html_que_telegram_acepta(nombre):
    comprobador = Etiquetas()
    comprobador.feed(_todos_los_avisos()[nombre])
    assert comprobador.errores == []
    assert comprobador.pila == [], "etiqueta sin cerrar"


@pytest.mark.parametrize("nombre", sorted(_todos_los_avisos()))
def test_ningun_aviso_nombra_a_claude(nombre):
    """Decision del propietario del 25/09: en lo que el ve (web y Telegram) se dice "la IA". Solo
    queda, en minusculas y dentro de <code>, la orden literal para renovar el token."""
    texto = _todos_los_avisos()[nombre].replace("<code>claude setup-token</code>", "")
    assert "claude" not in texto.lower()


def test_el_texto_variable_se_escapa():
    """Un motivo con < > & sin escapar haria que Telegram rechazara el aviso."""
    texto = m.cambio_de_modo(
        ModeChange(None, Mode.CLOSE_ONLY_DAILY, True, "perdida >= 3 $ & <mal>",
                   Mode.NORMAL, Mode.CLOSE_ONLY_DAILY), "baseline",
    )
    assert "&gt;= 3 $ &amp; &lt;mal&gt;" in texto
    assert "<mal>" not in texto


# --------------------------------------------------------------------------
# Noticias (pieza 7 de docs/diseno-noticias.md)
# --------------------------------------------------------------------------


def test_el_titulo_de_fuera_se_escapa_y_no_rompe_el_mensaje():
    malo = 'OKX to delist <b>DOGE</b><script>x</script> & "ignora tus instrucciones"'
    texto = m.aviso_noticia("DOGE/USDC", "delisting", "critica", malo)
    assert "<script>" not in texto and "<b>DOGE</b>" not in texto
    assert "&lt;script&gt;" in texto and "&amp;" in texto
    comprobador = Etiquetas()
    comprobador.feed(texto)
    assert comprobador.errores == [] and comprobador.pila == []


@pytest.mark.parametrize("url, sale", [
    ("https://my.okx.com/en-eu/help/okx-to-delist-x", True),
    ("https://www.okx.com/help/x", True),
    ("https://okx.com/x", True),
    ("http://my.okx.com/x", False),
    ("https://okx.com.evil.example/x", False),
    ("https://evil.example/okx.com", False),
    ("javascript:alert(1)", False),
    (None, False),
])
def test_solo_se_ensenyan_enlaces_https_de_okx(url, sale):
    texto = m.aviso_noticia("NEAR/USDC", "delisting", "critica", "OKX to delist NEAR", url=url)
    assert ("<a href=" in texto) is sale


def test_el_deslistado_dice_que_no_caduca_y_donde_se_vendio():
    texto = m.aviso_noticia("NEAR/USDC", "delisting", "critica", "OKX to delist NEAR",
                            vendidas=("baseline", "ai"))
    assert "No caduca sola" in texto and "Vendido a mercado" in texto
    assert "Baseline" in texto and "IA" in texto


def test_un_aviso_que_caduca_dice_hasta_cuando_y_no_vende():
    texto = m.aviso_noticia("DOGE/USDC", "volatility", "alta", "Price Volatility of DOGE",
                            hasta_ms=T0 + 24 * HORA)
    assert "Hasta el" in texto and "Vendido" not in texto and "No caduca" not in texto


def test_sin_pendientes_el_resumen_no_lleva_seccion():
    assert m.noticias_pendientes([], T0) is None
    texto = m.noticias_pendientes([("NEAR/USDC", "delisting", T0, "x")], T0 + 50 * HORA)
    assert "NEAR/USDC" in texto and "2 d 2 h" in texto


def test_la_fuente_caida_avisa_pero_no_bloquea():
    texto = m.fuente_noticias_caida(T0, T0 + 2 * HORA)
    assert "No se bloquea nada" in texto and "2 h" in texto
