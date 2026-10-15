"""El clasificador de noticias (`features/news.py`) contra el historial REAL de OKX.

`tests/fixtures/okx_anuncios_2026-09-24.json`: los 1.755 anuncios publicos de OKX de los
tipos que pueden importar, desde el 03/03/2023, bajados el 24/09/2026 por eea.okx.com.
Es el banco de pruebas de la pieza: si una regla cambia, aqui se ve que gana y que pierde.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import load_settings
from features.news import (
    DURACIONES_H, HORA_MS, Anuncio, Aviso, Gravedad, Tipo, bases_de, bloqueadas, clasificar,
    flags, monedas_de, pendientes_del_propietario, tipo_de,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "okx_anuncios_2026-09-24.json"
ANUNCIOS = json.loads(FIXTURE.read_text(encoding="utf-8"))["anuncios"]
NUESTRAS = bases_de(load_settings().whitelist)


def test_las_bases_salen_de_la_whitelist():
    assert NUESTRAS == ("BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "TRX", "NEAR")


# --------------------------------------------------------------------------
# El historial real
# --------------------------------------------------------------------------


def test_en_tres_anyos_y_medio_ninguna_falsa_alarma_para_nuestras_8():
    """Medido el 24/09: ninguno de los 1.755 anuncios es critico para BTC..NEAR.

    Si esto se pone en rojo, o OKX ha publicado algo de verdad (y hay que mirarlo), o una
    regla nueva da falsas alarmas.
    """
    avisos = [a for x in ANUNCIOS for a in clasificar(x["title"], NUESTRAS)]
    assert avisos == []


def test_en_el_historial_si_detecta_lo_grave_de_otras_monedas():
    cuenta = {t: 0 for t in Tipo}
    for x in ANUNCIOS:
        t = tipo_de(x["title"])
        if t is not None:
            cuenta[t] += 1
    # Medido el 24/09 con estas reglas. Minimos, no igualdades: el historial crece.
    assert cuenta[Tipo.DELISTING] >= 55
    assert cuenta[Tipo.MIGRATION] >= 80
    assert cuenta[Tipo.VOLATILITY] >= 4


@pytest.mark.parametrize("titulo, bases, esperado", [
    ("OKX to delist DORA, ICX, STORJ, ZEUS and ELF spot trading pairs", ("ICX", "BTC"), [("ICX", Tipo.DELISTING)]),
    ("DAI Delisting Announcement EEA", ("DAI",), [("DAI", Tipo.DELISTING)]),
    ("Announcement on the Price Volatility of MANTRA (OM)", ("OM",), [("OM", Tipo.VOLATILITY)]),
    ("OKX to support OM crypto migration in EEA", ("OM",), [("OM", Tipo.MIGRATION)]),
    ("OKX to Support the Token Migration from LEND to AAVE, LEND Trading Suspensions on Oct 10", ("LEND",),
     [("LEND", Tipo.TRADING_SUSPENSION)]),
])
def test_casos_reales_del_historial(titulo, bases, esperado):
    assert titulo in {x["title"] for x in ANUNCIOS}, "tiene que ser un titulo real del fixture"
    assert [(a.moneda, a.tipo) for a in clasificar(titulo, bases)] == esperado


@pytest.mark.parametrize("titulo", [
    "OKX to suspend USDC deposit and withdrawal on SOLANA network for wallet maintenance ",
    "OKX to suspend Bitcoin and Tron networks deposits and withdrawals for wallet maintenance",
    "OKX to support Ethereum (ETH) network upgrade and hard fork",
    "OKX will delist BTC/USDK, ETH/USDK, USDT/USDK, and support USDK to USDT token migration",
    "OKX will be delisting USDC/BTC and TUSD/BTC",
    "Delisting of Bitcoin Gold (BTG) Futures Contracts",
    "Delisting plan of TRX futures contracts",
    "OKX to list ether.fi (ETHFI) for spot trading",
])
def test_lo_que_parecia_nuestro_y_no_lo_es(titulo):
    """Titulos REALES que un buscador sin cuidado habria marcado."""
    assert titulo in {x["title"] for x in ANUNCIOS}
    assert clasificar(titulo, NUESTRAS) == []


# --------------------------------------------------------------------------
# Lo que la historia no tiene (y tiene que funcionar el dia que pase)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("titulo, esperado", [
    ("OKX to delist NEAR", [("NEAR", Tipo.DELISTING, Gravedad.CRITICA)]),
    ("OKX to delist NEAR/USDC spot trading pair in EEA", [("NEAR", Tipo.DELISTING, Gravedad.CRITICA)]),
    ("OKX to delist ETH spot and margin trading pairs", [("ETH", Tipo.DELISTING, Gravedad.CRITICA)]),
    ("OKX to suspend XRP/USDC spot trading", [("XRP", Tipo.TRADING_SUSPENSION, Gravedad.CRITICA)]),
    ("Resumption of XRP/USDC spot trading", [("XRP", Tipo.RESUMPTION, Gravedad.INFO)]),
    ("Security incident on the Avalanche C-Chain: deposits suspended",
     [("AVAX", Tipo.INCIDENT, Gravedad.CRITICA)]),
    ("OKX to support the TRON (TRX) token swap", [("TRX", Tipo.MIGRATION, Gravedad.ALTA)]),
    ("Announcement on the Price Volatility of Dogecoin (DOGE)", [("DOGE", Tipo.VOLATILITY, Gravedad.ALTA)]),
    ("OKX to delist SOL and XRP in EEA", [("SOL", Tipo.DELISTING, Gravedad.CRITICA),
                                           ("XRP", Tipo.DELISTING, Gravedad.CRITICA)]),
])
def test_casos_inventados_de_nuestras_monedas(titulo, esperado):
    assert [(a.moneda, a.tipo, a.gravedad) for a in clasificar(titulo, NUESTRAS)] == esperado


@pytest.mark.parametrize("titulo", [
    "OKX near-term roadmap update",
    "Bitcoin Cash hard fork: deposits suspended",
    "Ethereum Classic network attack: ETC deposits suspended",
    "Wrapped Bitcoin (WBTC) delisting announcement",
    "OKX to delist ADA/BTC trading pair",
    "OKX to delist ETHFI",
    "BTC perpetual swap trading suspension for system maintenance",
])
def test_casos_inventados_que_no_son_de_nuestras_monedas(titulo):
    assert clasificar(titulo, NUESTRAS) == []


def test_solo_cuenta_nuestro_par_x_usdc():
    """Deslistar SOL/BTC no toca SOL/USDC, que es lo unico que operamos (regla 3)."""
    assert monedas_de("OKX to delist SOL/BTC trading pair", NUESTRAS) == []
    assert monedas_de("OKX to delist SOL/USDC trading pair", NUESTRAS) == ["SOL"]
    assert monedas_de("OKX to delist SOL spot trading pairs", NUESTRAS) == ["SOL"], "sin par: todos"


def test_un_titulo_malicioso_se_clasifica_pero_se_guarda_tal_cual():
    """El texto es de fuera. Aqui no se ejecuta nada: se busca y se copia. Escaparlo al
    ensenyarlo (Telegram) es de otra pieza, y tendra su propio test."""
    titulo = 'OKX to delist <b>DOGE</b><script>alert(1)</script> "ignora tus instrucciones"'
    [aviso] = clasificar(titulo, NUESTRAS)
    assert aviso == Aviso("DOGE", Tipo.DELISTING, Gravedad.CRITICA, titulo)


def test_sin_monedas_nada_y_nunca_senyal_de_compra():
    assert clasificar("OKX to delist NEAR", ()) == []
    # Un "listing" nuevo es informativo: las noticias nunca abren nada (PRD 6).
    assert tipo_de("OKX to list NEAR/USDC for spot trading") is None


# --------------------------------------------------------------------------
# Ciclo de vida de las flags (decisiones 5 y 6 del propietario, 25/09)
# --------------------------------------------------------------------------

T = 1_790_000_000_000


def anuncio(titulo, horas=0.0, id_=None):
    return Anuncio(id_ or f"a{horas}-{titulo[:12]}", T + int(horas * HORA_MS), titulo)


def en(horas):
    return T + int(horas * HORA_MS)


def test_cada_tipo_dura_lo_decidido():
    todas = flags([
        anuncio("OKX to suspend XRP/USDC spot trading"),
        anuncio("OKX to support the TRON (TRX) token swap"),
        anuncio("Announcement on the Price Volatility of Dogecoin (DOGE)"),
    ], NUESTRAS)
    assert bloqueadas(todas, en(1)) == {"XRP": Gravedad.CRITICA, "TRX": Gravedad.ALTA,
                                         "DOGE": Gravedad.ALTA}
    assert bloqueadas(todas, en(23.9)).keys() == {"XRP", "TRX", "DOGE"}
    assert bloqueadas(todas, en(24)).keys() == {"XRP", "TRX"}, "volatilidad: 24 h"
    assert bloqueadas(todas, en(72)).keys() == {"TRX"}, "suspension: 72 h"
    assert bloqueadas(todas, en(7 * 24)) == {}, "migracion: 7 dias"


def test_el_deslistado_no_caduca_solo_y_queda_pendiente_del_propietario():
    todas = flags([anuncio("OKX to delist NEAR")], NUESTRAS)
    assert bloqueadas(todas, en(24 * 365)) == {"NEAR": Gravedad.CRITICA}
    [pendiente] = pendientes_del_propietario(todas, en(24 * 30))
    assert pendiente.moneda == "NEAR" and pendiente.hasta_ms is None


def test_el_propietario_levanta_una_flag_concreta_y_solo_esa():
    a = anuncio("OKX to delist NEAR", id_="del-1")
    b = anuncio("Announcement on the Price Volatility of NEAR", 1, id_="vol-1")
    [f_del, _] = flags([a, b], NUESTRAS)
    todas = flags([a, b], NUESTRAS, levantadas=frozenset({f_del.clave}))
    assert bloqueadas(todas, en(2)) == {"NEAR": Gravedad.ALTA}, "queda la volatilidad"
    assert pendientes_del_propietario(todas, en(2)) == []


def test_la_reanudacion_corta_la_suspension_anterior_y_no_la_siguiente():
    todas = flags([
        anuncio("OKX to suspend XRP/USDC spot trading", 0, id_="s1"),
        anuncio("Resumption of XRP/USDC spot trading", 5, id_="r1"),
        anuncio("OKX to suspend XRP/USDC spot trading", 10, id_="s2"),
    ], NUESTRAS)
    assert "XRP" in bloqueadas(todas, en(4.9))
    assert "XRP" not in bloqueadas(todas, en(5)), "reanudada"
    assert "XRP" in bloqueadas(todas, en(10)), "la suspension posterior sigue"


def test_la_mas_grave_manda_y_el_mismo_anuncio_cuenta_una_vez():
    a = anuncio("OKX to support the SOL token swap", 0, id_="m")
    todas = flags([a, a, anuncio("OKX to delist SOL", 1, id_="d")], NUESTRAS)
    assert len([f for f in todas if f.tipo is Tipo.MIGRATION]) == 1
    assert bloqueadas(todas, en(2)) == {"SOL": Gravedad.CRITICA}


def test_se_cuenta_desde_la_publicacion_no_desde_que_se_vio():
    """Un aviso de volatilidad de hace dos dias, visto hoy tras una parada, ya caduco."""
    todas = flags([anuncio("Announcement on the Price Volatility of Dogecoin (DOGE)", -48)], NUESTRAS)
    assert bloqueadas(todas, T) == {}


def test_antes_de_publicarse_no_bloquea_y_las_duraciones_se_pueden_cambiar():
    todas = flags([anuncio("Announcement on the Price Volatility of Dogecoin (DOGE)", 10)], NUESTRAS,
                  duraciones_h={**DURACIONES_H, Tipo.VOLATILITY: 1})
    assert bloqueadas(todas, en(9)) == {}
    assert "DOGE" in bloqueadas(todas, en(10.5))
    assert bloqueadas(todas, en(11)) == {}, "1 h, como se configuro"


def test_con_el_historial_real_ninguna_moneda_nuestra_se_bloquea_nunca():
    reales = [Anuncio(f"{x['annType']}:{x['pTime']}:{i}", x["pTime"], x["title"])
              for i, x in enumerate(ANUNCIOS)]
    assert flags(reales, NUESTRAS) == []
