"""Los comandos de Telegram (notify/comandos.py; decisiones del propietario del 25/09/2026).

Lo que no se puede romper:
- solo manda el chat privado del propietario; a nadie mas se le contesta;
- un comando viejo no se ejecuta;
- `/kill` NUNCA se levanta desde Telegram;
- la pausa solo se quita con `/resume` + `/si` en 60 s;
- ningun texto nombra a Claude.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from core.modes import Mode
from notify.comandos import (
    AYUDA,
    CONFIRMAR_MS,
    EDAD_MAX_MS,
    Comando,
    Estado,
    FotoCartera,
    Ignorado,
    Orden,
    aplicar,
    interpretar,
    reconstruir,
    texto_estado,
)

PROPIETARIO = 123456789
AHORA_MS = 1_790_000_000_000        # 2026-09-21 ~14:13 UTC
AHORA_S = AHORA_MS // 1000


def update(texto="/status", *, chat=PROPIETARIO, remitente=PROPIETARIO, tipo="private", date=AHORA_S, uid=7):
    return {"update_id": uid, "message": {
        "message_id": 1, "date": date, "text": texto,
        "chat": {"id": chat, "type": tipo}, "from": {"id": remitente, "is_bot": False},
    }}


def cmd(orden, ts_ms, texto=""):
    return Comando(0, ts_ms, orden, texto or f"/{orden.value}")


# --------------------------------------------------------------------------
# 1. interpretar
# --------------------------------------------------------------------------


def test_un_comando_del_propietario_se_ejecuta():
    r = interpretar(update("/pause"), PROPIETARIO, AHORA_MS)
    assert r == Comando(7, AHORA_S * 1000, Orden.PAUSE, "/pause")


def test_closeonly_es_la_pausa_y_se_aceptan_mayusculas_y_el_nombre_del_bot():
    for texto in ("/closeonly", "/PAUSE", "/pause@PloutosBot", "/pause porque si"):
        r = interpretar(update(texto), PROPIETARIO, AHORA_MS)
        assert isinstance(r, Comando) and r.orden is Orden.PAUSE, texto


def test_los_cinco_comandos():
    esperado = {"/status": Orden.STATUS, "/pause": Orden.PAUSE, "/kill": Orden.KILL,
                "/resume": Orden.RESUME, "/si": Orden.SI}
    for texto, orden in esperado.items():
        assert interpretar(update(texto), PROPIETARIO, AHORA_MS).orden is orden


def test_nadie_mas_manda_y_no_se_le_contesta():
    casos = [
        update("/kill", chat=999, remitente=999),           # otro usuario
        update("/kill", tipo="group"),                      # el propietario, pero en un grupo
        update("/kill", chat=PROPIETARIO, remitente=999),           # otro remitente
        update("/kill", tipo="channel"),
    ]
    for u in casos:
        r = interpretar(u, PROPIETARIO, AHORA_MS)
        assert r == Ignorado(7, "ajeno", None)


def test_ni_una_orden_de_levantar_el_kill_sale_de_telegram():
    for texto in ("/levantar_kill", "/levantar_kill motivo", "/LEVANTAR_KILL"):
        r = interpretar(update(texto), PROPIETARIO, AHORA_MS)
        assert isinstance(r, Ignorado) and r.motivo == "desconocido"


def test_texto_normal_y_comando_desconocido_reciben_la_ayuda():
    assert interpretar(update("hola"), PROPIETARIO, AHORA_MS) == Ignorado(7, "no_es_comando", AYUDA)
    assert interpretar(update("/start"), PROPIETARIO, AHORA_MS) == Ignorado(7, "desconocido", AYUDA)


def test_los_mensajes_viejos_que_no_son_comandos_no_se_contestan():
    """Al arrancar por primera vez llegan los de las ultimas 24 h: nada de ayuda a destiempo."""
    viejo = AHORA_S - 3600
    assert interpretar(update("hola", date=viejo), PROPIETARIO, AHORA_MS) == Ignorado(7, "no_es_comando", None)
    assert interpretar(update("/start", date=viejo), PROPIETARIO, AHORA_MS) == Ignorado(7, "desconocido", None)


def test_status_sin_la_base_de_noticias():
    assert "sin datos" in estado_texto(noticias=None)


def test_lo_que_no_es_un_mensaje_se_ignora_callado():
    assert interpretar({"update_id": 3, "edited_message": {}}, PROPIETARIO, AHORA_MS) == \
        Ignorado(3, "no_es_mensaje", None)
    for raro in ({"update_id": "x"}, {"update_id": 1, "message": {"chat": "a"}}, {}):
        r = interpretar(raro, PROPIETARIO, AHORA_MS)
        assert isinstance(r, Ignorado) and r.respuesta is None


def test_un_comando_viejo_no_se_ejecuta():
    justo = interpretar(update("/resume", date=AHORA_S - EDAD_MAX_MS // 1000), PROPIETARIO, AHORA_MS)
    assert isinstance(justo, Comando)
    tarde = interpretar(update("/resume", date=AHORA_S - EDAD_MAX_MS // 1000 - 1), PROPIETARIO, AHORA_MS)
    assert isinstance(tarde, Ignorado) and tarde.motivo == "tarde"
    assert "no se ejecuta" in tarde.respuesta


@settings(max_examples=300)
@given(
    chat=st.one_of(st.just(PROPIETARIO), st.integers()),
    remitente=st.one_of(st.just(PROPIETARIO), st.integers()),
    tipo=st.sampled_from(["private", "group", "supergroup", "channel"]),
    texto=st.one_of(st.text(), st.sampled_from(["/kill", "/pause", "/resume", "/si"])),
    edad_s=st.integers(-100, 10_000),
)
def test_propiedad_solo_el_propietario_y_a_tiempo(chat, remitente, tipo, texto, edad_s):
    r = interpretar(update(texto, chat=chat, remitente=remitente, tipo=tipo,
                           date=AHORA_S - edad_s), PROPIETARIO, AHORA_MS)
    if isinstance(r, Comando):
        assert chat == PROPIETARIO and remitente == PROPIETARIO and tipo == "private"
        assert edad_s * 1000 <= EDAD_MAX_MS
        assert r.orden is not Orden.LEVANTAR_KILL
    elif not (chat == PROPIETARIO and remitente == PROPIETARIO and tipo == "private"):
        assert r.respuesta is None


# --------------------------------------------------------------------------
# 2. el estado manual
# --------------------------------------------------------------------------


def test_pausa_y_su_modo():
    e, texto = aplicar(Estado(), cmd(Orden.PAUSE, AHORA_MS))
    assert e.pausa_ms == AHORA_MS
    assert set(e.modos) == {Mode.CLOSE_ONLY_MANUAL}
    assert "/resume" in texto


def test_resume_necesita_el_si_a_tiempo():
    e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.RESUME, AHORA_MS + 1000)])
    assert e.pausa_ms is not None and e.resume_ms is not None      # aun en pausa

    a_tiempo = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.RESUME, AHORA_MS + 1000),
                            cmd(Orden.SI, AHORA_MS + 1000 + CONFIRMAR_MS)])
    assert a_tiempo == Estado()

    tarde_e, texto = aplicar(e, cmd(Orden.SI, AHORA_MS + 1000 + CONFIRMAR_MS + 1000))
    assert tarde_e.pausa_ms == AHORA_MS and tarde_e.resume_ms is None
    assert "nada que confirmar" in texto


def test_un_si_suelto_no_hace_nada():
    e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.SI, AHORA_MS + 1000)])
    assert e.pausa_ms == AHORA_MS


def test_una_pausa_o_un_kill_entre_medias_anulan_el_resume():
    for orden in (Orden.PAUSE, Orden.KILL):
        e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.RESUME, AHORA_MS + 1000),
                         cmd(orden, AHORA_MS + 2000), cmd(Orden.SI, AHORA_MS + 3000)])
        assert e.pausa_ms == AHORA_MS, orden


def test_status_no_cambia_nada_ni_anula_el_resume():
    e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.RESUME, AHORA_MS + 1000)])
    e2, texto = aplicar(e, cmd(Orden.STATUS, AHORA_MS + 2000))
    assert e2 == e and texto is None
    assert reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.RESUME, AHORA_MS + 1000),
                        cmd(Orden.STATUS, AHORA_MS + 2000),
                        cmd(Orden.SI, AHORA_MS + 3000)]).pausa_ms is None


def test_resume_sin_pausa():
    e, texto = aplicar(Estado(), cmd(Orden.RESUME, AHORA_MS))
    assert e == Estado() and "ninguna pausa" in texto
    e, texto = aplicar(Estado(kill_ms=AHORA_MS), cmd(Orden.RESUME, AHORA_MS))
    assert e.kill_ms == AHORA_MS and "VPS" in texto


def test_el_kill_no_se_levanta_desde_telegram():
    e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.KILL, AHORA_MS + 1000),
                     cmd(Orden.RESUME, AHORA_MS + 2000), cmd(Orden.SI, AHORA_MS + 3000)])
    assert e.pausa_ms is None                   # la pausa si se quita
    assert e.kill_ms == AHORA_MS + 1000         # la parada no
    assert set(e.modos) == {Mode.HALTED}


def test_el_kill_se_levanta_en_el_vps_con_motivo():
    e, texto = aplicar(Estado(kill_ms=AHORA_MS),
                       cmd(Orden.LEVANTAR_KILL, AHORA_MS + 1000, "revisado <todo>"))
    assert e.kill_ms is None and e.modos == {}
    assert "revisado &lt;todo&gt;" in texto


def test_una_segunda_pausa_no_mueve_la_hora():
    e = reconstruir([cmd(Orden.PAUSE, AHORA_MS), cmd(Orden.PAUSE, AHORA_MS + 5000)])
    assert e.pausa_ms == AHORA_MS


ORDENES_TELEGRAM = [Orden.STATUS, Orden.PAUSE, Orden.KILL, Orden.RESUME, Orden.SI]


@settings(max_examples=400)
@given(st.lists(st.tuples(st.sampled_from(ORDENES_TELEGRAM), st.integers(0, 90_000)),
                max_size=25))
def test_propiedad_lo_que_telegram_no_puede_hacer(pasos):
    ts, comandos = AHORA_MS, []
    for orden, salto in pasos:
        ts += salto
        comandos.append(cmd(orden, ts))
    e = reconstruir(comandos)
    ordenes = [c.orden for c in comandos]

    # Una vez hay /kill, desde Telegram no se va nunca.
    if Orden.KILL in ordenes:
        assert Mode.HALTED in e.modos
    # Si hubo pausa y ya no esta, fue con un /si a 60 s o menos de su /resume, sin
    # ninguna pausa ni kill entre los dos.
    if Orden.PAUSE in ordenes and e.pausa_ms is None:
        ok = False
        for i, c in enumerate(comandos):
            if c.orden is not Orden.SI:
                continue
            previos = [p for p in comandos[:i] if p.orden is not Orden.STATUS]
            if previos and previos[-1].orden is Orden.RESUME \
                    and c.ts_ms - previos[-1].ts_ms <= CONFIRMAR_MS:
                ok = True
        assert ok
    # Nada de lo que responde nombra a Claude.
    estado = Estado()
    for c in comandos:
        estado, texto = aplicar(estado, c)
        assert texto is None or "claude" not in texto.lower()


# --------------------------------------------------------------------------
# 3. /status
# --------------------------------------------------------------------------


def foto(nombre, **kw):
    base = dict(nombre=nombre, modo=Mode.NORMAL, equity_usd=50.42, cambio_hoy_usd=0.42,
                cerradas_hoy=1, posiciones=2, ultima_vela_ms=AHORA_MS - 3_600_000)
    return FotoCartera(**(base | kw))


def estado_texto(**kw):
    args = dict(ahora_ms=AHORA_MS, max_posiciones=3, max_llamadas=40,
                manual=Estado(), noticias={})
    return texto_estado([foto("baseline"),
                         foto("ai", modo=Mode.CLOSE_ONLY_QUOTA, equity_usd=49.87,
                              cambio_hoy_usd=-0.13, llamadas_ia=3)], **(args | kw))


def test_status_ensenya_las_dos_carteras():
    t = estado_texto()
    for trozo in ("Baseline", "IA", "NORMAL", "QUOTA", "50,42 $", "49,87 $", "+0,42 $",
                  "-0,13 $", "Cerradas hoy", "2/3", "3/40", "Noticias: sin avisos activos"):
        assert trozo in t, trozo
    assert "claude" not in t.lower()
    assert "pausa" not in t.lower()


def test_status_alineado():
    t = estado_texto()
    tabla = t.split("<pre>", 1)[1].split("</pre>", 1)[0]
    assert len({len(linea) for linea in tabla.splitlines()}) == 1


def test_status_con_pausa_parada_y_noticias():
    t = estado_texto(manual=Estado(pausa_ms=AHORA_MS, kill_ms=AHORA_MS),
                     noticias={"NEAR/USDC": ("delisting (critica)",), "A<B": ("x&y",)})
    assert "En pausa" in t and "Parada" in t
    assert "NEAR/USDC: delisting (critica)" in t
    assert "A&lt;B: x&amp;y" in t


def test_status_sin_datos_todavia():
    t = texto_estado([foto("baseline", equity_usd=None, ultima_vela_ms=None)],
                     ahora_ms=AHORA_MS, max_posiciones=3, max_llamadas=40,
                     manual=Estado(), noticias={})
    assert "-" in t.split("<pre>", 1)[1]
