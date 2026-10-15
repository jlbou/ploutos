"""La revision diaria de los jueces (scripts/jueces_diarios.py): avisa SOLO si algo va mal.

Nada de esto lanza un juez de verdad ni manda un Telegram: los jueces son falsos y el mensaje se
mira como texto.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "jueces_diarios.py"
_spec = importlib.util.spec_from_file_location("jueces_diarios", SCRIPT)
jd = importlib.util.module_from_spec(_spec)
sys.modules["jueces_diarios"] = jd
_spec.loader.exec_module(jd)

AUN_NO = "RESULTADO: coherente, pero solo ~8 h de 72. Aun no."
FALLA = """  OK    una fila de equity por vela
  FALLA ninguna entrada en modo de solo cierre  [PRD 5]  (5 comprobados)
          - d-20260926T0400-btc-pb: se envio con el bot en modo de solo cierre
  OK    llamadas a Claude dentro del presupuesto
RESULTADO: hay incoherencias."""


def falsos(codigos):
    """Un juez falso por posicion: devuelve el codigo que toca y una salida acorde."""
    it = iter(codigos)

    def correr(_args):
        c = next(it)
        return c, {0: "RESULTADO: CUMPLIDO", 1: FALLA, 2: AUN_NO}.get(c, "Traceback ...\nValueError: roto")
    return correr


def test_estan_los_cuatro_jueces():
    """15/10: retiradas las carteras de la fase 6 y el demo, quedan cuatro (sin los suyos)."""
    nombres = [n for n, _a in jd.JUECES]
    assert len(nombres) == 4
    scripts = {a[0] for _n, a in jd.JUECES}
    assert scripts == {"scripts/check_news.py", "scripts/check_control.py", "scripts/check_papel_l.py",
                       "scripts/check_embudo.py"}
    for _n, args in jd.JUECES:
        assert (Path(__file__).resolve().parents[2] / args[0]).exists()


def test_si_todo_va_bien_o_aun_no_no_se_manda_nada():
    assert jd.mensaje(jd.juzgar(falsos([0, 2, 2, 2]))) is None
    assert jd.mensaje(jd.juzgar(falsos([2, 2, 2, 2]))) is None


def test_una_falla_se_avisa_con_lo_que_falla():
    texto = jd.mensaje(jd.juzgar(falsos([2, 2, 1, 2])))
    assert texto is not None
    assert "papel de L" in texto and "FALLA" in texto
    assert "d-20260926T0400-btc-pb" in texto
    assert "noticias" not in texto                    # solo lo que va mal


def test_un_juez_que_no_corre_tambien_se_avisa():
    texto = jd.mensaje(jd.juzgar(falsos([2, 3, 2, 2])))
    assert "comandos" in texto and "no se pudo ejecutar" in texto and "ValueError" in texto
    colgado = jd.mensaje([jd.Veredicto("noticias", None, "no termino en 600 s")])
    assert "no se pudo ejecutar" in colgado and "600 s" in colgado


def test_nunca_nombra_a_claude_y_escapa_el_html():
    texto = jd.mensaje([jd.Veredicto("x", 1, "  FALLA llamadas a Claude <por encima> & mas")])
    assert "claude" not in texto.lower()
    assert "&lt;por encima&gt; &amp; mas" in texto
