"""Clasificacion de anuncios en flags de riesgo por moneda (docs/diseno-noticias.md, pieza 1).

PURO: un titulo entra, flags salen. Ni red, ni base, ni reloj; las duraciones y la
aplicacion (filtro y salida a mercado) son de otras piezas.

Lo que pide el PRD: las noticias son SOLO un filtro de riesgo, nunca una senyal de compra
(seccion 6), y ante una flag critica de hackeo o deslistado se sale a mercado (seccion 5).
Los titulos son TEXTO NO CONFIABLE: aqui solo se buscan palabras en ellos; nunca se
ejecutan y quien los ensenye (Telegram) los escapa. No van a la IA, con UNA excepcion (el propietario,
11/10/2026): el paso 3 del embudo de noticias de L (`ai/clasificador.py`), en sombra.

LO MEDIDO ANTES DE ESCRIBIR ESTO (historial publico de OKX, 1.755 anuncios desde el
03/03/2023, en tests/fixtures): OKX no dice a que moneda afecta un anuncio (hay que
leerla del titulo); el tipo del anuncio no basta ("DAI Delisting" y la volatilidad de
MANTRA estan en `announcements-others`); y buscar la moneda sin cuidado confunde
Bitcoin Cash con BTC, Ethereum Classic con ETH o "BTC/USDK" (otro par) con el nuestro.

Decisiones del propietario (25/09/2026): solo anuncios de OKX al principio; flag critica con
posicion = vender a mercado; el deslistado no caduca solo (avisa y el propietario decide).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Tipo(StrEnum):
    DELISTING = "delisting"                     # deja de cotizar
    TRADING_SUSPENSION = "trading_suspension"   # cotizacion suspendida
    INCIDENT = "incident"                       # hackeo, exploit, ataque
    MIGRATION = "migration"                     # cambio de token o de red
    VOLATILITY = "volatility"                   # aviso de volatilidad anomala (MANTRA)
    RESUMPTION = "resumption"                   # se reanuda la cotizacion: levanta la suspension


class Gravedad(StrEnum):
    CRITICA = "critica"     # no entrar + salir a mercado
    ALTA = "alta"           # no entrar
    INFO = "info"           # nada que bloquear (la reanudacion)


GRAVEDAD = {
    Tipo.DELISTING: Gravedad.CRITICA,
    Tipo.TRADING_SUSPENSION: Gravedad.CRITICA,
    Tipo.INCIDENT: Gravedad.CRITICA,
    Tipo.MIGRATION: Gravedad.ALTA,
    Tipo.VOLATILITY: Gravedad.ALTA,
    Tipo.RESUMPTION: Gravedad.INFO,
}

# Por orden: si un titulo encaja en varias, gana la primera (la mas grave).
_REGLAS: tuple[tuple[Tipo, re.Pattern[str]], ...] = (
    (Tipo.DELISTING, re.compile(r"\bdelist", re.I)),
    (Tipo.RESUMPTION, re.compile(r"\bresum\w*\b.*\btrading\b|\btrading\b.*\bresum", re.I)),
    (Tipo.TRADING_SUSPENSION, re.compile(
        # "suspend XRP/USDC spot trading": el par va en medio. Hasta 40 caracteres, sin punto.
        r"\bsuspen\w*\b[^.]{0,40}?\btrading\b|\btrading\s+(?:suspen|halt)|\bhalt\w*\b[^.]{0,40}?\btrading\b",
        re.I)),
    (Tipo.INCIDENT, re.compile(
        r"\bhack|\bexploit|security\s+(?:incident|breach)|\battack|\bcompromis|\bstolen\b|\bdrain",
        re.I)),
    (Tipo.MIGRATION, re.compile(r"\bmigrat|\bredenominat|\btoken\s+swap|\brebrand|\bticker\s+change", re.I)),
    (Tipo.VOLATILITY, re.compile(r"\bvolatility\b|\babnormal\b", re.I)),
)

# Lo que NO afecta al spot: derivados, Earn, campanyas. Salvo que el titulo diga "spot":
# "delist X spot and margin trading pairs" SI nos afecta aunque diga "margin".
_RUIDO = re.compile(
    r"futures|perpetual|swap\s+contract|\bmargin\b|\bearn\b|staking|dual\s+investment|airdrop|"
    r"campaign|\bP2P\b|\bindex(?:es)?\b|\boptions\b|leverage|learn|giveaway|cashback",
    re.I,
)
_SPOT = re.compile(r"\bspot\b", re.I)

# Nombres de las monedas, ademas del ticker. Sin "Ether": "ether.fi (ETHFI)" es otra moneda
# y "OKX to delist ether.fi" habria marcado ETH.
NOMBRES: dict[str, tuple[str, ...]] = {
    "BTC": ("Bitcoin",), "ETH": ("Ethereum",), "SOL": ("Solana",), "XRP": ("Ripple",),
    "DOGE": ("Dogecoin",), "AVAX": ("Avalanche",), "TRX": ("TRON",), "NEAR": (),
}
# Otros activos que llevan el nombre dentro: "Bitcoin Cash" no es BTC.
_OTRO_DESPUES = r"(?!\s+(?:Cash|SV|Gold|Classic|Name\s+Service|Fog|Diamond)\b)"
_OTRO_ANTES = r"(?<!Wrapped\s)(?<!Beacon\s)"
QUOTE = "USDC"


@dataclass(frozen=True, slots=True)
class Aviso:
    moneda: str         # base de la whitelist ("NEAR"), no el par
    tipo: Tipo
    gravedad: Gravedad
    titulo: str         # tal cual: texto NO confiable


def tipo_de(titulo: str) -> Tipo | None:
    """Que dice el titulo, sin mirar a que moneda. None = informativo o ruido."""
    if _RUIDO.search(titulo) and not _SPOT.search(titulo):
        return None
    return next((t for t, r in _REGLAS if r.search(titulo)), None)


def monedas_de(titulo: str, bases: list[str] | tuple[str, ...]) -> list[str]:
    """Las monedas de `bases` a las que se refiere el titulo, en el orden de `bases`.

    - Ticker: en MAYUSCULAS y como palabra entera ("NEAR" si, "near-term" no; "ETH" no
      casa con "ETHFI"). Si va en un par con otra moneda de cotizacion ("BTC/USDK",
      "ADA/BTC"), NO es nuestro par X/USDC y no cuenta.
    - Nombre: sin distinguir mayusculas, salvo los que son otro activo ("Bitcoin Cash").
    """
    halladas = []
    for base in bases:
        ticker = re.compile(
            rf"(?<![A-Za-z0-9/]){re.escape(base)}(?![A-Za-z0-9])(?!/(?!{QUOTE}\b)[A-Z0-9]+)")
        if ticker.search(titulo):
            halladas.append(base)
            continue
        for nombre in NOMBRES.get(base, ()):
            if re.search(rf"{_OTRO_ANTES}\b{re.escape(nombre)}\b{_OTRO_DESPUES}", titulo, re.I):
                halladas.append(base)
                break
    return halladas


def clasificar(titulo: str, bases: list[str] | tuple[str, ...]) -> list[Aviso]:
    """Un aviso por cada moneda de `bases` a la que afecta el titulo; [] si ninguna."""
    tipo = tipo_de(titulo)
    if tipo is None:
        return []
    return [Aviso(m, tipo, GRAVEDAD[tipo], titulo) for m in monedas_de(titulo, bases)]


def bases_de(whitelist: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """"NEAR/USDC" -> "NEAR". La whitelist de settings.yaml son pares."""
    return tuple(par.split("/", 1)[0] for par in whitelist)


# --------------------------------------------------------------------------
# Ciclo de vida: que monedas estan bloqueadas en cada instante (pieza 3 del disenyo)
# --------------------------------------------------------------------------

HORA_MS = 3_600_000
# Decision 6 del propietario (25/09): de sentido comun, no medidas (hay pocos casos reales). El
# servicio las leera de settings.yaml; esto es el valor por defecto y lo que prueban los
# tests. None = no caduca sola: el deslistado lo levanta el propietario (decision 5). Un incidente
# critico dura 72 h, como la suspension.
DURACIONES_H: dict[Tipo, float | None] = {
    Tipo.DELISTING: None,
    Tipo.TRADING_SUSPENSION: 72,
    Tipo.INCIDENT: 72,
    Tipo.MIGRATION: 7 * 24,
    Tipo.VOLATILITY: 24,
}


@dataclass(frozen=True, slots=True)
class Anuncio:
    """Un anuncio ya visto: el id de la fuente y CUANDO se publico (no cuando se vio).

    Se cuenta desde la publicacion: si el servicio estuvo parado y ve ahora un aviso de
    volatilidad de hace dos dias, ese aviso ya caduco; bloquear ahora seria tarde y mal.
    """

    id: str
    publicado_ms: int
    titulo: str


@dataclass(frozen=True, slots=True)
class Flag:
    moneda: str
    tipo: Tipo
    gravedad: Gravedad
    desde_ms: int
    hasta_ms: int | None     # None = hasta que el propietario la levante
    anuncio: str             # id del anuncio que la puso
    titulo: str

    @property
    def clave(self) -> str:
        """Lo que se levanta a mano: una flag concreta, no una moneda entera."""
        return f"{self.anuncio}:{self.moneda}:{self.tipo}"

    def activa(self, ahora_ms: int) -> bool:
        return self.desde_ms <= ahora_ms and (self.hasta_ms is None or ahora_ms < self.hasta_ms)


def flags(
    anuncios: list[Anuncio], bases: list[str] | tuple[str, ...], *,
    levantadas: frozenset[str] = frozenset(),
    duraciones_h: dict[Tipo, float | None] | None = None,
) -> list[Flag]:
    """Todas las flags que salen de los anuncios, con su ventana, por orden de publicacion.

    - Un anuncio da como mucho una flag por moneda (el mismo anuncio visto dos veces, una).
    - Una REANUDACION de la cotizacion corta las suspensiones ANTERIORES de esa moneda.
    - `levantadas`: las claves que el propietario quito a mano (un deslistado ya decidido, una falsa
      alarma). Se quita esa flag, no la moneda entera.
    """
    dur = DURACIONES_H if duraciones_h is None else duraciones_h
    vistas: dict[str, Flag] = {}
    reanudaciones: dict[str, list[int]] = {}
    for a in sorted(anuncios, key=lambda x: (x.publicado_ms, x.id)):
        for aviso in clasificar(a.titulo, bases):
            if aviso.tipo is Tipo.RESUMPTION:
                reanudaciones.setdefault(aviso.moneda, []).append(a.publicado_ms)
                continue
            horas = dur[aviso.tipo]
            f = Flag(aviso.moneda, aviso.tipo, aviso.gravedad, a.publicado_ms,
                     None if horas is None else a.publicado_ms + int(horas * HORA_MS),
                     a.id, a.titulo)
            vistas.setdefault(f.clave, f)
    out = []
    for f in vistas.values():
        if f.clave in levantadas:
            continue
        if f.tipo is Tipo.TRADING_SUSPENSION:
            cortes = [t for t in reanudaciones.get(f.moneda, []) if t > f.desde_ms]
            if cortes:
                fin = min(cortes)
                f = Flag(f.moneda, f.tipo, f.gravedad, f.desde_ms,
                         fin if f.hasta_ms is None else min(f.hasta_ms, fin), f.anuncio, f.titulo)
        out.append(f)
    return sorted(out, key=lambda f: (f.desde_ms, f.moneda, f.tipo))


_PESO = {Gravedad.CRITICA: 2, Gravedad.ALTA: 1, Gravedad.INFO: 0}


def bloqueadas(todas: list[Flag], ahora_ms: int) -> dict[str, Gravedad]:
    """Monedas con alguna flag activa AHORA, con la gravedad mas alta.

    CRITICA = no entrar, y salir a mercado si hay posicion (PRD 5, decision 2 del propietario);
    ALTA = no entrar. Lo que no esta aqui se opera con normalidad.
    """
    out: dict[str, Gravedad] = {}
    for f in todas:
        if f.activa(ahora_ms) and (f.moneda not in out or _PESO[f.gravedad] > _PESO[out[f.moneda]]):
            out[f.moneda] = f.gravedad
    return out


def pendientes_del_propietario(todas: list[Flag], ahora_ms: int) -> list[Flag]:
    """Las que no caducan solas y siguen puestas: el resumen diario las recuerda (decision 5)."""
    return [f for f in todas if f.hasta_ms is None and f.activa(ahora_ms)]


# --------------------------------------------------------------------------
# El puente al filtro que ya existe (pieza 5 del disenyo)
# --------------------------------------------------------------------------
#
# `strategy.filters.filter_event` existe desde la fase 2: mira `RiskState.event_flags`
# ({par: (etiquetas,)}) y rechaza el simbolo si hay alguna. Nadie lo llenaba, porque no
# habia fuente de noticias. Esto es lo que lo llenara. El filtro va ANTES del baseline y de
# la IA (`strategy/pipeline.py`), asi que los dos reciben la misma lista (decision del propietario del
# 22/09) y la comparacion de la fase 6 no se toca.


def event_flags(
    todas: list[Flag], ahora_ms: int, whitelist: list[str] | tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    """{par de la whitelist: ("delisting (critica)", ...)} con las flags activas AHORA.

    Clave por PAR ("NEAR/USDC"), que es lo que mira el filtro; las flags van por moneda base.
    Etiquetas legibles: salen tal cual en el journal ("por que NEAR lleva un dia sin nada").
    """
    por_base: dict[str, list[str]] = {}
    for f in todas:
        if f.activa(ahora_ms):
            por_base.setdefault(f.moneda, []).append(f"{f.tipo} ({f.gravedad})")
    return {par: tuple(sorted(set(por_base[par.split("/", 1)[0]])))
            for par in whitelist if par.split("/", 1)[0] in por_base}


def pares_criticos(
    todas: list[Flag], ahora_ms: int, whitelist: list[str] | tuple[str, ...],
) -> frozenset[str]:
    """Pares con una flag CRITICA activa: si hay posicion, se sale a mercado (pieza 6)."""
    criticas = {m for m, g in bloqueadas(todas, ahora_ms).items() if g is Gravedad.CRITICA}
    return frozenset(par for par in whitelist if par.split("/", 1)[0] in criticas)
