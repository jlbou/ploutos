"""Bloqueos silenciosos: velas seguidas en que NINGUNA moneda pudo entrar por un motivo que no es el mercado.

POR QUE (01/10/2026). El 30/09 OKX retiro el par BTC/USD, la paridad de USDC quedo desconocida y la regla 17
dejo las dos carteras sin entradas durante 5 velas (20 h). El bot hacia lo correcto (sin dato, no se entra) y
por eso ningun juez lo vio: todos comprueban que se cumplan las reglas, y se cumplian. El aviso de la regla 17
cubre ESE caso; este juez cubre la familia: el proximo bloqueo puede venir de otro sitio.

QUE ES UN BLOQUEO. Una vela en que TODAS las monedas de la whitelist estan descartadas y cada una tiene al
menos un motivo de SISTEMA (datos, configuracion, una fuente que falta), no de mercado:

- de sistema: `paridad de usdc`, `frescura`, `coste conocido`, `whitelist` y "sin la vela de esta hora";
- de mercado o de cartera (NO cuentan): `hueco libre`, `atr`, `spread`, `profundidad`, `correlacion`,
  `cooldown`, `cupo diario`. Una cartera llena muchas velas es lo normal;
- fuera a proposito: `modo` (una pausa la pone el propietario, y los cambios de modo ya se avisan por Telegram) y
  `evento` (las flags de noticias las avisa su servicio).

Una moneda con candidato o "sin senyal" paso la criba: esa vela no esta bloqueada.

Puro: sin bases ni reloj. Las filas las trae `scripts/check_bloqueos.py`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

DE_SISTEMA = ("paridad de usdc", "frescura", "coste conocido", "whitelist")
SIN_VELA = "sin la vela de esta hora"


def motivos_de_sistema(detalle: str | None) -> list[str]:
    """Los motivos de sistema de una fila `filtered` ("nombre: detalle; nombre: detalle")."""
    out = []
    for parte in (detalle or "").split("; "):
        if parte.startswith(SIN_VELA):
            out.append("sin vela")
            continue
        nombre = parte.split(":", 1)[0].strip()
        if nombre in DE_SISTEMA:
            out.append(nombre)
    return out


@dataclass(frozen=True, slots=True)
class Tramo:
    """Velas seguidas bloqueadas. `motivos`: los de sistema que aparecieron, de mas a menos veces."""

    desde_ms: int
    hasta_ms: int
    velas: int
    motivos: tuple[str, ...]


def tramos_bloqueados(
    velas_ms: Sequence[int],
    filas: Iterable[tuple[int, str | None, str, str | None]],
    whitelist: Sequence[str],
) -> list[Tramo]:
    """`velas_ms`: las velas procesadas, en orden. `filas`: (ts_ms, simbolo, kind, detail) del journal."""
    # Solo las `filtered`: una moneda con candidato o "sin senyal" no tiene fila aqui y rompe el bloqueo.
    por_vela: dict[int, dict[str, list[str]]] = defaultdict(dict)
    for ts, simbolo, kind, detalle in filas:
        if simbolo is not None and kind == "filtered":
            por_vela[ts].setdefault(simbolo, []).extend(motivos_de_sistema(detalle))

    def bloqueada(ts: int) -> list[str] | None:
        motivos: list[str] = []
        for s in whitelist:
            m = por_vela[ts].get(s)
            if not m:
                return None
            motivos.extend(m)
        return motivos

    tramos: list[Tramo] = []
    actual: list[tuple[int, list[str]]] = []
    for ts in [*velas_ms, None]:
        m = bloqueada(ts) if ts is not None else None
        if m is not None:
            actual.append((ts, m))
            continue
        if actual:
            cuenta: dict[str, int] = defaultdict(int)
            for _ts, ms in actual:
                for x in set(ms):
                    cuenta[x] += 1
            orden = tuple(sorted(cuenta, key=lambda k: (-cuenta[k], k)))
            tramos.append(Tramo(actual[0][0], actual[-1][0], len(actual), orden))
            actual = []
    return tramos
