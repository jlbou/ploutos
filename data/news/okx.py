"""Los anuncios oficiales de OKX (docs/diseno-noticias.md, pieza 2).

API PUBLICA, sin claves: `GET /api/v5/support/announcements?annType=<tipo>&page=<n>`, por
`eea.okx.com` (el host de la cuenta; los datos publicos son los mismos). Verificado el
24-25/09/2026 con respuestas reales (tests/fixtures):
- bien: `{"code": "0", "msg": "", "data": [{"details": [...], "totalPage": "2"}]}`, cada
  anuncio con `annType`, `title`, `url`, `pTime` (ms, en TEXTO) y `businessPTime`;
- mal: `code` distinto de "0" y `data` vacio (p. ej. 51000 con un tipo que no existe).
- Sin User-Agent de navegador, OKX devuelve 403 (hallazgo de la fase 0).

POR QUE ESTOS CUATRO TIPOS: en el historial, lo grave no siempre esta en su tipo ("DAI
Delisting" y la volatilidad de MANTRA estan en `others`). Los listados nuevos no se piden:
una noticia nunca abre nada (PRD 6).

NUNCA LANZA. Si la fuente cae, se avisa pero no se bloquea (decision del propietario del 22/09): esto
devuelve lo que pudo leer y la lista de errores, y quien lo llame decide avisar. Solo se pide
la primera pagina de cada tipo: con una pasada cada 5 min, lo nuevo siempre esta ahi.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.request import Request, urlopen

from features.news import Anuncio

HOST = "https://eea.okx.com"
RUTA = "/api/v5/support/announcements"
TIPOS = (
    "announcements-delistings",
    "announcements-deposit-withdrawal-suspension-resumption",
    "announcements-trading-updates",
    "announcements-others",
)
USER_AGENT = "Mozilla/5.0 (compatible; ploutos-news)"
TIMEOUT_S = 10.0

log = logging.getLogger("ploutos.news.okx")


@dataclass
class Lectura:
    anuncios: list[Anuncio] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    @property
    def fuente_caida(self) -> bool:
        """Todos los tipos fallaron: no sabemos nada (no es "no hay noticias")."""
        return not self.anuncios and bool(self.errores)


def interpretar(cuerpo: bytes | str, tipo: str) -> tuple[list[Anuncio], str | None]:
    """La respuesta de la API -> anuncios, o el error. El id es la URL: unica por anuncio."""
    try:
        d = json.loads(cuerpo)
    except ValueError:
        return [], f"{tipo}: respuesta que no es JSON"
    if not isinstance(d, dict) or str(d.get("code")) != "0":
        codigo = d.get("code") if isinstance(d, dict) else "?"
        msg = d.get("msg") if isinstance(d, dict) else ""
        return [], f"{tipo}: OKX responde {codigo} {msg!r}"
    anuncios = []
    for bloque in d.get("data") or []:
        for a in (bloque or {}).get("details") or []:
            try:
                anuncios.append(Anuncio(
                    id=str(a.get("url") or f"{a['annType']}:{a['pTime']}:{a['title']}"),
                    publicado_ms=int(a["pTime"]),
                    titulo=str(a["title"]),
                ))
            except (KeyError, TypeError, ValueError):
                continue   # un anuncio mal formado no tumba los demas
    return anuncios, None


def leer(
    tipos: tuple[str, ...] = TIPOS, *, ya_vistos: frozenset[str] = frozenset(),
    _abrir: Callable = urlopen, timeout_s: float = TIMEOUT_S,
) -> Lectura:
    """Una pasada: la primera pagina de cada tipo, sin los ya vistos, por orden de publicacion."""
    r = Lectura()
    nuevos: dict[str, Anuncio] = {}
    for tipo in tipos:
        peticion = Request(f"{HOST}{RUTA}?annType={tipo}&page=1", headers={"User-Agent": USER_AGENT})
        try:
            with _abrir(peticion, timeout=timeout_s) as resp:
                cuerpo = resp.read()
        except (URLError, TimeoutError, OSError) as exc:
            r.errores.append(f"{tipo}: {type(exc).__name__}: {exc}")
            continue
        anuncios, error = interpretar(cuerpo, tipo)
        if error:
            r.errores.append(error)
        for a in anuncios:
            if a.id not in ya_vistos:
                nuevos.setdefault(a.id, a)
    r.anuncios = sorted(nuevos.values(), key=lambda a: (a.publicado_ms, a.id))
    for e in r.errores:
        log.warning("anuncios de OKX: %s", e)
    return r
