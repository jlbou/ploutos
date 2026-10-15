"""El servicio de comandos (`scripts/run_telegram.py`) con su base de verdad y Telegram falso.

Ningun test habla con Telegram: `getUpdates` y el envio son falsos, y el token es inventado.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.modes import Mode
from notify import control
from notify.comandos import Orden, reconstruir
from notify.telegram import TelegramError
from portfolio import store

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_telegram.py"
_spec = importlib.util.spec_from_file_location("run_telegram", SCRIPT)
run_telegram = importlib.util.module_from_spec(_spec)
sys.modules["run_telegram"] = run_telegram
_spec.loader.exec_module(run_telegram)

T0 = int(datetime(2026, 10, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
PROPIETARIO = 424242
TOKEN = "123:inventado-para-el-test"


class Secretos:
    telegram_chat_id = str(PROPIETARIO)

    def valor(self, nombre):
        return TOKEN if nombre == "telegram_bot_token" else None


class Telegram:
    """getUpdates falso: devuelve lo que se le pone y apunta con que offset se le pidio."""

    def __init__(self):
        self.cola, self.offsets, self.lanza = [], [], None

    def __call__(self, token, metodo, params, timeout):
        assert token == TOKEN and metodo == "getUpdates"
        if self.lanza:
            raise self.lanza
        self.offsets.append(params.get("offset"))
        desde = params.get("offset") or 0
        return [u for u in self.cola if u["update_id"] >= desde]


class Enviar:
    def __init__(self):
        self.textos = []

    def __call__(self, conn, token, chat, ahora_ms):
        filas = conn.execute("SELECT id, texto FROM paper_avisos WHERE enviado_ms IS NULL ORDER BY id").fetchall()
        for f in filas:
            self.textos.append(f["texto"])
            conn.execute("UPDATE paper_avisos SET enviado_ms = ? WHERE id = ?", (ahora_ms, f["id"]))
        conn.commit()
        return len(filas), None


class Latido:
    def __init__(self):
        self.veces = 0

    def enviar(self):
        self.veces += 1


class Reloj:
    def __init__(self):
        self.ms = T0

    def __call__(self):
        return self.ms


def mensaje(uid, texto, *, segundos=0, chat=PROPIETARIO):
    return {"update_id": uid, "message": {
        "message_id": uid, "date": T0 // 1000 + segundos, "text": texto,
        "chat": {"id": chat, "type": "private"}, "from": {"id": chat, "is_bot": False}}}


@pytest.fixture
def servicio(tmp_path):
    tg, enviar, latido, reloj = Telegram(), Enviar(), Latido(), Reloj()
    r = run_telegram.TelegramRunner(
        tmp_path / "control.db", carteras={"baseline": tmp_path / "paper.db", "ai": tmp_path / "paper-ai.db"},
        news_db=tmp_path / "news.db", secretos=Secretos(),
        _call=tg, _enviar=enviar, _latido=latido, _reloj=reloj)
    yield r, tg, enviar, latido, reloj
    r.conn.close()


def test_pause_se_guarda_se_contesta_y_late(servicio):
    r, tg, enviar, latido, reloj = servicio
    tg.cola = [mensaje(10, "/pause")]
    info = r.vuelta()
    assert info["ok"] and info["updates"] == 1 and latido.veces == 1
    assert Mode.CLOSE_ONLY_MANUAL in r.estado_manual().modos
    assert len(enviar.textos) == 1 and "Pausa" in enviar.textos[0]


def test_los_mensajes_tratados_no_se_vuelven_a_pedir(servicio):
    r, tg, _enviar, _latido, _reloj = servicio
    tg.cola = [mensaje(10, "/pause"), mensaje(11, "hola")]
    r.vuelta()
    r.vuelta()
    assert tg.offsets == [None, 12]
    assert len(control.comandos(r.conn)) == 1


def test_resume_con_si_quita_la_pausa(servicio):
    r, tg, enviar, _latido, reloj = servicio
    tg.cola = [mensaje(10, "/pause")]
    r.vuelta()
    reloj.ms = T0 + 5000
    tg.cola.append(mensaje(11, "/resume", segundos=5))
    r.vuelta()
    assert r.estado_manual().pausa_ms is not None
    reloj.ms = T0 + 20_000
    tg.cola.append(mensaje(12, "/si", segundos=20))
    r.vuelta()
    assert r.estado_manual().modos == {}
    assert "Pausa quitada" in enviar.textos[-1]


def test_un_extranyo_no_manda_ni_recibe_respuesta(servicio):
    r, tg, enviar, _latido, _reloj = servicio
    tg.cola = [mensaje(10, "/kill", chat=999)]
    r.vuelta()
    assert r.estado_manual().modos == {} and enviar.textos == []
    fila = r.conn.execute("SELECT * FROM control_ignorados").fetchone()
    assert (fila["update_id"], fila["motivo"]) == (10, "ajeno")
    assert "kill" not in " ".join(str(v) for v in dict(fila).values())     # nunca el texto


def test_un_comando_viejo_se_contesta_pero_no_se_ejecuta(servicio):
    r, tg, enviar, _latido, reloj = servicio
    reloj.ms = T0 + 3600_000
    tg.cola = [mensaje(10, "/pause")]
    r.vuelta()
    assert r.estado_manual().modos == {}
    assert "llegado tarde" in enviar.textos[0]


def test_si_telegram_falla_no_late_y_queda_apuntado(servicio):
    r, tg, _enviar, latido, _reloj = servicio
    tg.lanza = TelegramError(f"HTTP 409 en getUpdates: bot{TOKEN} conflict")
    info = r.vuelta()
    assert not info["ok"] and latido.veces == 0
    fila = r.conn.execute("SELECT * FROM control_lecturas").fetchone()
    assert fila["ok"] == 0 and "409" in fila["error"] and TOKEN not in fila["error"]


def test_sin_credenciales_no_hace_nada(tmp_path):
    class SinNada:
        telegram_chat_id = None

        def valor(self, _n):
            return None
    r = run_telegram.TelegramRunner(tmp_path / "c.db", carteras={}, news_db=tmp_path / "n.db",
                                    secretos=SinNada(), _call=Telegram(), _enviar=Enviar(), _latido=Latido())
    assert not r.vuelta()["ok"]


def test_status_con_las_carteras_de_verdad(servicio, tmp_path):
    r, tg, enviar, _latido, _reloj = servicio
    for nombre in ("paper.db", "paper-ai.db"):
        c = store.connect(tmp_path / nombre)
        store.migrate(c)
        with c:
            c.execute("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending)"
                      " VALUES (?,?,?,?)", (T0 - 4 * 3600_000, 50.42, 0, 0))
        c.close()
    tg.cola = [mensaje(10, "/status")]
    r.vuelta()
    [texto] = enviar.textos
    assert "Baseline" in texto and "IA" in texto and "50,42 $" in texto
    assert "sin datos" in texto                     # no hay base de noticias
    assert "claude" not in texto.lower()


def test_status_sin_carteras_contesta_igual(servicio):
    r, tg, enviar, _latido, _reloj = servicio
    tg.cola = [mensaje(10, "/status")]
    r.vuelta()
    assert "ninguna cartera tiene datos" in enviar.textos[0]


def test_el_kill_solo_se_levanta_en_el_vps_con_motivo(servicio):
    r, tg, enviar, _latido, reloj = servicio
    tg.cola = [mensaje(10, "/kill")]
    r.vuelta()
    with pytest.raises(ValueError):
        r.levantar_kill("   ")
    reloj.ms = T0 + 60_000
    r.levantar_kill("revisado, todo en orden")
    assert r.estado_manual().modos == {}
    [fila] = r.conn.execute("SELECT * FROM control_comandos WHERE origen = 'vps'").fetchall()
    assert (fila["orden"], fila["update_id"]) == (Orden.LEVANTAR_KILL.value, None)
    r.vuelta()
    assert "revisado, todo en orden" in enviar.textos[-1]
    with pytest.raises(ValueError):
        r.levantar_kill("otra vez")                  # ya no hay parada


def test_las_carteras_y_el_servicio_derivan_lo_mismo(servicio):
    """El estado que ve el servicio es el que reconstruye cualquiera de la base (como las carteras)."""
    r, tg, _enviar, _latido, _reloj = servicio
    tg.cola = [mensaje(10, "/kill"), mensaje(11, "/pause")]
    r.vuelta()
    assert reconstruir(control.comandos(r.conn)) == r.estado_manual()
    assert set(r.estado_manual().modos) == {Mode.HALTED, Mode.CLOSE_ONLY_MANUAL}
