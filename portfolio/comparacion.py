"""La comparacion de la fase 6: ¿elige mejor la IA que el baseline? (docs/archivo/protocolo-fase-6.md)

LA IDEA. Con operaciones cerradas no hay muestra (5-10 por cartera en semanas), y las
dos carteras dejan de ver los mismos candidatos en cuanto divergen. Asi que se mide
CADA candidato que vio la IA: que habria pasado si se hubiera abierto, contra las
velas reales. Y sobre la MISMA lista se calcula que habria abierto el baseline, que es
una regla fija (mejor R:R). Asi se comparan dos decisiones sobre lo mismo.

Todo aqui es PURO: no lee bases ni importa `ai/` (regla de arquitectura). Lo que viene
de las bases lo prepara `scripts/check_fase6.py`.

LAS REGLAS, FIJADAS ANTES DE VER DATOS (decisiones del propietario del 24/09/2026):
- Resolucion con las MISMAS suposiciones que el simulador y el juez de papel
  (`audit.expected_outcome`): entrada a su precio y nunca en la vela que la crea,
  caduca a las 2 velas (se puede llenar en las 3 siguientes a la que la crea), el stop gana los empates y sufre los huecos.
- Horizonte de 42 velas (7 dias en 4 h). Lo que siga abierto se valora al cierre de
  la vela 42, saliendo como taker. Sin el horizonte cumplido, el candidato no se juzga.
- R NETA: (salida - entrada - comisiones) / (entrada - stop). Entrada maker; salida
  por objetivo maker, por stop o por horizonte taker (igual que `paper.py`). Una
  entrada que caduca sin llenarse vale 0 R.
- M1 por vela = sum(multiplicador x R) de lo que abrio la IA - sum(R) de lo que habria
  abierto el baseline. Saltar todo vale 0: si los candidatos eran malos, no abrir
  nada es acertar, y esa decision tiene que contar.
- Cada uno abre como mucho `cupo` = min(huecos libres, operaciones que quedan hoy),
  en su orden (la IA, el del modelo; el baseline, de mejor a peor R:R). Es lo que
  hace el bucle: prueba en orden hasta que el motor veta por falta de hueco.
- Intervalo del 90 % remuestreando DIAS enteros (las velas de un dia se parecen).
- Veredicto: PERJUDICA si el intervalo entero esta por debajo de 0; APORTA si esta
  entero por encima y hay al menos 30 velas en que discrepan; si no, NO CONCLUYENTE.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import fmean

from portfolio.audit import expected_outcome
from portfolio.paper import Bar

HORIZONTE_VELAS = 42
NIVEL = 0.90
MIN_DISCREPANCIAS = 30
MIN_DIAS = 21          # PRD seccion 12: la fase 6 dura al menos 3 semanas
MAX_DIAS = 56          # informe 1.9: como mucho 8 semanas
REMUESTREOS = 10_000
SEMILLA = 6            # fija: el mismo juez sobre los mismos datos da siempre lo mismo
DIA_MS = 86_400_000

APORTA = "APORTA"
PERJUDICA = "PERJUDICA"
NO_CONCLUYENTE = "NO CONCLUYENTE"


@dataclass(frozen=True, slots=True)
class Cand:
    """Un candidato tal como lo vio la IA (del `prompt` guardado en el journal)."""

    cid: str
    symbol: str
    entry: float
    stop: float
    target: float
    regime: str = ""

    @property
    def rr(self) -> float:
        """El R:R recalculado de los precios, no el redondeado a 2 decimales del prompt:
        con el redondeado, dos candidatos casi empatados podian salir en otro orden que
        el que uso el baseline de verdad."""
        riesgo = self.entry - self.stop
        return (self.target - self.entry) / riesgo if riesgo > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Decision:
    """Una vela en que la IA DECIDIO (o fallo y, por tanto, no abrio nada)."""

    ts_ms: int
    candidatos: tuple[Cand, ...]
    abiertos: tuple[tuple[str, float], ...]   # (cid, multiplicador), en el orden del modelo
    cupo: int


@dataclass(frozen=True, slots=True)
class Resultado:
    estado: str            # objetivo | stop | horizonte | caducada | pendiente
    r: float | None = None


def seleccion_baseline(candidatos: tuple[Cand, ...], cupo: int) -> list[str]:
    """Lo que habria abierto el baseline: `strategy.baseline.rank` y los `cupo` primeros.

    Misma clave de orden que alli (R:R descendente, desempate por id). Un test compara
    las dos para que no se separen sin que nadie lo vea.
    """
    ordenados = sorted(candidatos, key=lambda c: (-c.rr, c.cid))
    return [c.cid for c in ordenados[:max(0, cupo)]]


def seleccion_ia(decision: Decision) -> list[tuple[str, float]]:
    validos = {c.cid for c in decision.candidatos}
    return [(cid, m) for cid, m in decision.abiertos if cid in validos][:max(0, decision.cupo)]


def resolver(
    c: Cand, ts_ms: int, bars: list[Bar], *, tf_ms: int, maker: float, taker: float,
    horizonte: int = HORIZONTE_VELAS,
) -> Resultado:
    """Que habria pasado si se hubiera abierto `c` en la vela `ts_ms`."""
    cursor = ts_ms + horizonte * tf_ms
    orden = {"decision_id": c.cid, "limit_price": c.entry, "stop_price": c.stop,
             "target_price": c.target, "created_ts_ms": ts_ms}
    out = expected_outcome(orden, bars, cursor)
    riesgo = c.entry - c.stop
    if riesgo <= 0:
        return Resultado("pendiente")
    if out.state == "expired":
        return Resultado("caducada", 0.0)
    if out.state == "filled" and out.reason is not None:
        fee = maker if out.reason == "target" else taker
        return Resultado(out.reason, _r(c, out.exit_price, fee, maker))
    # Sigue abierta (o sin llenar) en el cursor: solo se juzga si las velas LLEGAN a el.
    en_horizonte = [b for b in bars if b.ts_open_ms == cursor]
    if out.state == "filled" and en_horizonte:
        return Resultado("horizonte", _r(c, en_horizonte[0].close, taker, maker))
    return Resultado("pendiente")


def _r(c: Cand, salida: float, fee_salida: float, maker: float) -> float:
    neto = (salida - c.entry) - c.entry * maker - salida * fee_salida
    return neto / (c.entry - c.stop)


@dataclass(frozen=True, slots=True)
class Vela:
    ts_ms: int
    m1: float
    discrepa: bool
    regimen: str
    r_abiertos: tuple[float, ...]       # R de lo que abrio la IA
    r_saltados: tuple[float, ...]       # R de lo que salto (M2)
    r_ponderado: float                  # sum(mult x R) de lo que abrio (M3)
    r_sin_ponderar: float               # sum(R) de lo mismo


def evaluar(decisiones: list[Decision], resultados: dict[tuple[int, str], Resultado]) -> tuple[list[Vela], int]:
    """Las velas juzgables y cuantas quedan pendientes (sin el horizonte cumplido).

    Una vela se juzga ENTERA o no se juzga: si falta el resultado de un solo candidato,
    esperar. Juzgar solo los que ya se resolvieron sesgaria hacia los que se resuelven
    antes (los que tocan el stop pronto, por ejemplo).
    """
    velas: list[Vela] = []
    pendientes = 0
    for d in decisiones:
        res = {c.cid: resultados.get((d.ts_ms, c.cid)) for c in d.candidatos}
        if any(r is None or r.r is None for r in res.values()):
            pendientes += 1
            continue
        r = {cid: x.r for cid, x in res.items()}
        ia = seleccion_ia(d)
        base = seleccion_baseline(d.candidatos, d.cupo)
        ia_ids = [cid for cid, _ in ia]
        ponderado = sum(m * r[cid] for cid, m in ia)
        sin_ponderar = sum(r[cid] for cid in ia_ids)
        m1 = ponderado - sum(r[cid] for cid in base)
        discrepa = set(ia_ids) != set(base) or any(m != 1.0 for _, m in ia)
        velas.append(Vela(
            ts_ms=d.ts_ms, m1=m1, discrepa=discrepa, regimen=_regimen(d),
            r_abiertos=tuple(r[cid] for cid in ia_ids),
            r_saltados=tuple(r[c.cid] for c in d.candidatos if c.cid not in ia_ids),
            r_ponderado=ponderado, r_sin_ponderar=sin_ponderar,
        ))
    return velas, pendientes


def _regimen(d: Decision) -> str:
    cuenta = Counter(c.regime for c in d.candidatos).most_common()
    if not cuenta:
        return "?"
    if len(cuenta) > 1 and cuenta[0][1] == cuenta[1][1]:
        return "mixto"
    return cuenta[0][0] or "?"


@dataclass(frozen=True, slots=True)
class Intervalo:
    media: float
    lo: float
    hi: float
    velas: int
    dias: int


def bootstrap_por_dias(
    valores: list[tuple[int, float]], *, remuestreos: int = REMUESTREOS, nivel: float = NIVEL,
    semilla: int = SEMILLA,
) -> Intervalo | None:
    """Media e intervalo remuestreando DIAS enteros (bootstrap por bloques).

    `valores` = (ts_ms, valor). Con velas sueltas el intervalo saldria mas estrecho de lo
    que es: las velas de un mismo dia comparten mercado.
    """
    if not valores:
        return None
    por_dia: dict[int, list[float]] = defaultdict(list)
    for ts, v in valores:
        por_dia[ts // DIA_MS].append(v)
    dias = list(por_dia.values())
    rng = random.Random(semilla)
    medias = []
    for _ in range(remuestreos):
        muestra = [v for _ in dias for v in rng.choice(dias)]
        medias.append(fmean(muestra))
    medias.sort()
    cola = (1 - nivel) / 2
    lo = medias[int(cola * (remuestreos - 1))]
    hi = medias[int((1 - cola) * (remuestreos - 1))]
    return Intervalo(fmean(v for _, v in valores), lo, hi, len(valores), len(dias))


def veredicto(intervalo: Intervalo | None, discrepancias: int,
              *, minimo: int = MIN_DISCREPANCIAS) -> str:
    if intervalo is None:
        return NO_CONCLUYENTE
    if intervalo.hi < 0:
        return PERJUDICA
    if intervalo.lo > 0 and discrepancias >= minimo:
        return APORTA
    return NO_CONCLUYENTE


@dataclass(frozen=True, slots=True)
class Calendario:
    """Cuando se puede ENSENYAR el veredicto (decision 2 del propietario: sin mirar a mitad).

    Minimo 3 semanas y 30 discrepancias; con 8 semanas, se ensenya pase lo que pase.
    """

    inicio_ms: int

    @property
    def minimo_ms(self) -> int:
        return self.inicio_ms + MIN_DIAS * DIA_MS

    @property
    def tope_ms(self) -> int:
        return self.inicio_ms + MAX_DIAS * DIA_MS

    def abierto(self, ahora_ms: int, discrepancias: int) -> bool:
        if ahora_ms >= self.tope_ms:
            return True
        return ahora_ms >= self.minimo_ms and discrepancias >= MIN_DISCREPANCIAS


def m2(velas: list[Vela]) -> tuple[float | None, int, float | None, int]:
    """R media de lo que abrio la IA y de lo que salto, con cuantos de cada."""
    ab = [r for v in velas for r in v.r_abiertos]
    sa = [r for v in velas for r in v.r_saltados]
    return (fmean(ab) if ab else None, len(ab), fmean(sa) if sa else None, len(sa))


def m3(velas: list[Vela]) -> tuple[float, float]:
    """R total de lo que abrio la IA, con su multiplicador y sin el."""
    return sum(v.r_ponderado for v in velas), sum(v.r_sin_ponderar for v in velas)
