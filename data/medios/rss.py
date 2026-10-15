"""Los RSS de los medios de cripto (docs/diseno-medios-sombra.md, decision del propietario del 07/10/2026).

Gratuitos, sin clave. Las 24 fuentes respondieron el 07/10/2026. La calidad (A: redaccion propia; B: agregadores) se
puso ANTES de ver ningun dato, para poder mirarla despues solo como informacion.

TEXTO DE FUERA, NO CONFIABLE:
- se rechaza un documento con `<!DOCTYPE` o `<!ENTITY` (una bomba de entidades tumbaria la memoria del VPS: el
  `xml.etree` de Python no se defiende solo), de mas de `MAX_BYTES` o mal formado;
- los titulos se guardan como texto plano (sin etiquetas), recortados a `MAX_TITULO`; nunca se ejecutan, nunca van a
  la IA y en sombra no se ensenyan a nadie.

NUNCA LANZA: una fuente que falla se apunta y las demas siguen.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

log = logging.getLogger("ploutos.medios")

USER_AGENT = "Mozilla/5.0 (compatible; ploutos-medios/0.1)"
TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000
MAX_TITULO = 300
MAX_ENLACE = 500
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"


@dataclass(frozen=True, slots=True)
class Fuente:
    nombre: str
    url: str
    calidad: str      # A | B


FUENTES: tuple[Fuente, ...] = (
    Fuente("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss", "A"),
    Fuente("cointelegraph", "https://cointelegraph.com/rss", "A"),
    Fuente("theblock", "https://www.theblock.co/rss.xml", "A"),
    Fuente("decrypt", "https://decrypt.co/feed", "A"),
    Fuente("blockworks", "https://blockworks.co/feed", "A"),
    Fuente("dlnews", "https://www.dlnews.com/arc/outboundfeeds/rss/", "A"),
    Fuente("protos", "https://protos.com/feed/", "A"),
    Fuente("rekt", "https://rekt.news/rss/feed.xml", "A"),
    Fuente("thedefiant", "https://thedefiant.io/api/feed", "A"),
    Fuente("bitcoinmagazine", "https://bitcoinmagazine.com/.rss/full/", "A"),
    Fuente("cryptoslate", "https://cryptoslate.com/feed/", "A"),
    Fuente("sec", "https://www.sec.gov/news/pressreleases.rss", "A"),
    Fuente("newsbtc", "https://www.newsbtc.com/feed/", "B"),
    Fuente("bitcoinist", "https://bitcoinist.com/feed/", "B"),
    Fuente("cryptopotato", "https://cryptopotato.com/feed/", "B"),
    Fuente("utoday", "https://u.today/rss", "B"),
    Fuente("beincrypto", "https://beincrypto.com/feed/", "B"),
    Fuente("cryptobriefing", "https://cryptobriefing.com/feed/", "B"),
    Fuente("coinjournal", "https://coinjournal.net/feed/", "B"),
    Fuente("ambcrypto", "https://ambcrypto.com/feed/", "B"),
    Fuente("dailyhodl", "https://dailyhodl.com/feed/", "B"),
    Fuente("coingape", "https://coingape.com/feed/", "B"),
    Fuente("cryptonews", "https://cryptonews.com/news/feed/", "B"),
    Fuente("watcherguru", "https://watcher.guru/news/feed", "B"),
)


@dataclass(frozen=True, slots=True)
class Titular:
    fuente: str
    guid: str
    titulo: str
    enlace: str
    publicado_ms: int | None   # None = sin fecha legible (se usara la de cuando se vio)

    @property
    def id(self) -> str:
        return f"{self.fuente}:{self.guid}"


@dataclass
class LecturaFuente:
    fuente: str
    titulares: list[Titular] = field(default_factory=list)
    error: str | None = None


_ETIQUETAS = re.compile(r"<[^>]*>")
_ESPACIOS = re.compile(r"\s+")
_PELIGROSO = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


def texto_plano(valor: str | None, maximo: int) -> str:
    """Sin etiquetas, sin entidades, sin saltos; recortado. Es texto NO confiable: solo se guarda."""
    if not valor:
        return ""
    limpio = _ESPACIOS.sub(" ", html.unescape(_ETIQUETAS.sub(" ", valor))).strip()
    return limpio[:maximo]


def texto_de(nodo: ET.Element | None) -> str | None:
    """Todo el texto de un elemento, tambien el de sus hijos. `findtext` solo da el de ANTES del primer hijo: un
    <title>Solana <b>exploit</b> drains</title> se quedaba en "Solana " (revision del 15/10/2026)."""
    return None if nodo is None else "".join(nodo.itertext())


def fecha_ms(valor: str | None) -> int | None:
    """RFC 822 (RSS) o ISO 8601 (Atom). Sin zona horaria, UTC. Ilegible: None."""
    if not valor or not valor.strip():
        return None
    valor = valor.strip()
    try:
        dt = parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def interpretar(cuerpo: bytes, fuente: str) -> tuple[list[Titular], str | None]:
    """El documento de un feed -> titulares, o el error. Puro: sin red."""
    if len(cuerpo) > MAX_BYTES:
        return [], f"{fuente}: documento de {len(cuerpo)} bytes (maximo {MAX_BYTES})"
    if _PELIGROSO.search(cuerpo):
        return [], f"{fuente}: documento con DOCTYPE o ENTITY, rechazado"
    try:
        raiz = ET.fromstring(cuerpo)
    except ET.ParseError as exc:
        return [], f"{fuente}: XML mal formado ({exc})"
    out: list[Titular] = []
    for item in raiz.iter("item"):          # RSS 2.0
        titulo = texto_plano(texto_de(item.find("title")), MAX_TITULO)
        enlace = texto_plano(item.findtext("link"), MAX_ENLACE)
        guid = texto_plano(item.findtext("guid"), MAX_ENLACE) or enlace or titulo
        fecha = fecha_ms(item.findtext("pubDate") or item.findtext(f"{DC}date"))
        if titulo and guid:
            out.append(Titular(fuente, guid, titulo, enlace, fecha))
    for entrada in raiz.iter(f"{ATOM}entry"):   # Atom
        titulo = texto_plano(texto_de(entrada.find(f"{ATOM}title")), MAX_TITULO)
        nodo = entrada.find(f"{ATOM}link")
        enlace = texto_plano(nodo.get("href") if nodo is not None else None, MAX_ENLACE)
        guid = texto_plano(entrada.findtext(f"{ATOM}id"), MAX_ENLACE) or enlace or titulo
        fecha = fecha_ms(entrada.findtext(f"{ATOM}published") or entrada.findtext(f"{ATOM}updated"))
        if titulo and guid:
            out.append(Titular(fuente, guid, titulo, enlace, fecha))
    if not out:
        return [], f"{fuente}: ningun titular en el documento"
    return out, None


def leer_fuente(f: Fuente, *, _abrir: Callable = urlopen, timeout_s: float = TIMEOUT_S) -> LecturaFuente:
    try:
        with _abrir(Request(f.url, headers={"User-Agent": USER_AGENT}), timeout=timeout_s) as resp:
            cuerpo = resp.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - una fuente caida no para las demas
        return LecturaFuente(f.nombre, error=f"{f.nombre}: {type(exc).__name__}: {str(exc)[:200]}")
    titulares, error = interpretar(cuerpo, f.nombre)
    return LecturaFuente(f.nombre, titulares, error)


def leer(fuentes: tuple[Fuente, ...] = FUENTES, *, _abrir: Callable = urlopen,
         timeout_s: float = TIMEOUT_S) -> list[LecturaFuente]:
    """Una pasada por todas las fuentes, una detras de otra. Nunca lanza."""
    lecturas = [leer_fuente(f, _abrir=_abrir, timeout_s=timeout_s) for f in fuentes]
    for lec in lecturas:
        if lec.error:
            log.warning("medios: %s", lec.error)
    return lecturas
