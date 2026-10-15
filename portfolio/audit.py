"""Auditoria del bucle de papel: el juez del criterio de avance de la fase 2.

El criterio que fijo el propietario pide "operaciones de papel COHERENTES durante >= 72 h".
Esto convierte "coherente" en comprobaciones con respuesta si/no, sobre lo que
esta GUARDADO, que es lo unico que sobrevive y lo unico que se puede auditar.

LA REGLA DE ORO DE ESTE MODULO: NO REUTILIZA EL CODIGO QUE AUDITA. No llama al
simulador (`portfolio/paper.py`), ni al motor de riesgo (`risk/engine.py`), ni a
las reglas (`risk/rules.py`). Lo recalcula todo por su cuenta a partir de las
velas reales. Si usara el mismo codigo, cualquier fallo de ese codigo le pasaria
inadvertido: le daria la razon a su propio error.

Lo que SI importa:
- `risk.limits.Limits`, para saber que limites regian a cada equity (escalones
  de la regla 9 y slider). Son los numeros contra los que se compara, no la
  logica que se audita.
- `ENTRY_BARS_TO_LIVE` y el formato del `decision_id`: son parte del contrato.

Las reglas 16 (spread y coste) y 15 (mitad de correlacion) se comprueban con
el contexto que el bucle guarda desde el 22/09/2026 (`002_context.sql`): el
spread y las correlaciones CON LAS QUE decidio. Las ordenes anteriores no lo
tienen y se cuentan aparte como "sin datos", nunca como cumplidas.

La regla 17 (paridad de USDC) se comprueba con la lectura que el bucle guarda
desde el 22/09/2026 (`003_usdc.sql`): una orden no puede entrar con la paridad
desconocida ni desviada mas del tope.

El analista (fase 3, pieza 10) se audita con su journal (`005_ai.sql`), sin
importar `ai/` (ni `portfolio/` puede, ni el juez debe: seria juzgar el parser
con el parser). La entrada que vio se lee del JSON guardado tal cual se envio.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from collections.abc import Callable
from typing import Any

from core.config import Settings
from features.news import Flag, Gravedad
from notify.comandos import Comando, Estado, cerrar_todo_en, reconstruir
from portfolio.paper import ENTRY_BARS_TO_LIVE, Bar
from risk.limits import Limits
from risk.types import Instrument
from strategy.candidates import make_decision_id

EPS = 1e-6
# Cuantos ejemplos se ensenyan por comprobacion. El resto se cuenta.
MAX_EJEMPLOS = 5

# El analista solo puede REDUCIR el tamanyo (PRD seccion 6). Escrito aqui y no
# importado de `ai/contract.py`: si el contrato se aflojara, el juez no le daria
# la razon.
MULTIPLICADOR_MIN, MULTIPLICADOR_MAX = 0.5, 1.0
VENTANA_5H_MS = 5 * 3600 * 1000
# Filas del journal de una decision que NO llamo a Claude (no gastan presupuesto).
NO_LLAMO = ("skipped_budget", "skipped_quota", "skipped_stale")
TIPOS_CANDIDATO = ("open", "skip")
QUOTA = "CLOSE_ONLY_QUOTA"


@dataclass(slots=True)
class Check:
    """Una comprobacion. Sin fallos = cumplida."""

    nombre: str
    regla: str
    fallos: list[str] = field(default_factory=list)
    comprobados: int = 0
    # Casos que NO se pudieron comprobar por falta de datos guardados. Se
    # cuentan aparte: ni son fallos ni se pueden dar por buenos.
    sin_datos: int = 0
    # Avisos que no son fallos pero que alguien tiene que leer.
    notas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.fallos

    def falla(self, texto: str) -> None:
        self.fallos.append(texto)


@dataclass(slots=True)
class PaperRecord:
    """Todo lo que la base de papel guarda, tal cual, en filas."""

    orders: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    equity: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    cursor: int | None
    market: list[dict[str, Any]] = field(default_factory=list)
    correlations: list[dict[str, Any]] = field(default_factory=list)
    usdc: list[dict[str, Any]] = field(default_factory=list)
    mode_changes: list[dict[str, Any]] = field(default_factory=list)
    ai_calls: list[dict[str, Any]] = field(default_factory=list)
    ai_decisions: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, timeframe: str) -> PaperRecord:
        conn.row_factory = sqlite3.Row

        def filas(sql: str, *params: Any) -> list[dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, params)]

        def opcional(sql: str) -> list[dict[str, Any]]:
            # Tablas de 002_context.sql: una base que el bucle aun no ha
            # migrado no las tiene, y eso es "sin datos", no un error.
            try:
                return filas(sql)
            except sqlite3.OperationalError:
                return []

        cursor = conn.execute(
            "SELECT last_ts_ms FROM paper_cursor WHERE timeframe = ?", (timeframe,)
        ).fetchone()
        return cls(
            orders=filas("SELECT * FROM paper_orders ORDER BY created_ts_ms"),
            positions=filas("SELECT * FROM paper_positions"),
            trades=filas("SELECT * FROM paper_trades ORDER BY closed_ts_ms"),
            equity=filas("SELECT * FROM paper_equity ORDER BY ts_ms"),
            decisions=filas("SELECT * FROM paper_decisions ORDER BY id"),
            cursor=int(cursor[0]) if cursor else None,
            market=opcional("SELECT * FROM paper_market"),
            correlations=opcional("SELECT * FROM paper_correlations"),
            usdc=opcional("SELECT * FROM paper_usdc"),
            mode_changes=opcional("SELECT * FROM paper_mode_changes ORDER BY id"),
            ai_calls=opcional("SELECT * FROM ai_calls ORDER BY id"),
            ai_decisions=opcional("SELECT * FROM ai_decisions"),
        )


# --------------------------------------------------------------------------
# Re-simulacion independiente
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """Lo que DEBERIA haber pasado con una orden, segun las velas."""

    decision_id: str
    state: str                    # pending | filled | expired
    bars_waited: int
    opened_ts_ms: int | None = None
    closed_ts_ms: int | None = None
    reason: str | None = None     # stop | target | news | manual
    exit_price: float | None = None


def _bars_after(bars: list[Bar], after_ms: int, until_ms: int, inclusive: bool) -> list[Bar]:
    if inclusive:
        return [b for b in bars if after_ms <= b.ts_open_ms <= until_ms]
    return [b for b in bars if after_ms < b.ts_open_ms <= until_ms]


def expected_outcome(
    order: dict[str, Any], bars: list[Bar], cursor: int,
    critica: Callable[[int], bool] | None = None,
    manual: Callable[[int], bool] | None = None,
) -> Outcome:
    """Re-simula una orden contra las velas con las suposiciones del simulador.

    Escrito aparte a proposito (ver cabecera). Las suposiciones son las del
    simulador, documentadas en CLAUDE.md: entrada a SU precio, nunca en la vela
    que la crea; el stop gana los empates y sufre los huecos; el objetivo no se
    beneficia de ellos; se puede llenar y saltar en la misma vela; y en la vela que llena,
    el objetivo no cuenta (suposicion 7, revision del 15/10/2026).
    """
    limit = order["limit_price"]
    stop, target = order["stop_price"], order["target_price"]
    waited = 0
    opened: int | None = None
    for b in _bars_after(bars, order["created_ts_ms"], cursor, inclusive=False):
        if b.low <= limit:
            opened = b.ts_open_ms
            break
        waited += 1
        if waited > ENTRY_BARS_TO_LIVE:
            return Outcome(order["decision_id"], "expired", waited)
    if opened is None:
        return Outcome(order["decision_id"], "pending", waited)

    # `critica(ts_apertura)`: si al CIERRE de esa vela habia una flag critica de noticias para la
    # moneda. Va despues del stop y el objetivo de la misma vela, como en el bucle (pieza 4d).
    for b in _bars_after(bars, opened, cursor, inclusive=True):
        if b.low <= stop:
            return Outcome(
                order["decision_id"], "filled", waited, opened, b.ts_open_ms,
                "stop", min(stop, b.open),
            )
        if b.high >= target and b.ts_open_ms != opened:
            return Outcome(
                order["decision_id"], "filled", waited, opened, b.ts_open_ms,
                "target", target,
            )
        if critica is not None and critica(b.ts_open_ms):
            return Outcome(
                order["decision_id"], "filled", waited, opened, b.ts_open_ms,
                "news", b.close,
            )
        # "Cerrar todo" desde el panel durante esa vela: a mercado al cierre (el propietario, 26/09).
        if manual is not None and manual(b.ts_open_ms):
            return Outcome(
                order["decision_id"], "filled", waited, opened, b.ts_open_ms,
                "manual", b.close,
            )
    return Outcome(order["decision_id"], "filled", waited, opened)


# --------------------------------------------------------------------------
# La auditoria
# --------------------------------------------------------------------------


@dataclass
class Audit:
    record: PaperRecord
    bars: dict[str, list[Bar]]              # por simbolo, ordenadas
    instruments: dict[str, Instrument]
    settings: Settings
    timeframe_ms: int
    slider_level: int = 3
    starting_usd: float = 50.0
    # De quien es esta cartera: 'baseline' (el grupo de control, sin IA) o 'ai'
    # (la del analista, decision C de la fase 3). Lo dice quien lanza el juez.
    decider: str = "baseline"
    # Las flags de noticias (de `var/ploutos-news.db`, pieza 4d): con ellas el juez sabe que
    # entradas tenian que cancelarse y que posiciones venderse a mercado. None = sin noticias.
    noticias: list[Flag] | None = None
    # Los comandos de Telegram (de `var/ploutos-control.db`): con ellos el juez sabe cuando habia
    # una pausa (/pause) o una parada (/kill). None = sin base de control, nada que exigir.
    # La pausa y la parada se derivan con la MISMA funcion que usan las carteras
    # (`notify.comandos.reconstruir`, con sus propios tests de propiedades); lo que se juzga aqui
    # es que el bucle las APLICO: ni una entrada, pendientes canceladas, ni una venta en HALTED.
    comandos: list[Comando] | None = None

    def _manual_en(self, decision_ms: int) -> Estado:
        return reconstruir([c for c in self.comandos or () if c.ts_ms <= decision_ms])

    def _flag_en(self, symbol: str, decision_ms: int, solo_criticas: bool) -> bool:
        base = symbol.split("/", 1)[0]
        return any(f.moneda == base and f.activa(decision_ms)
                   and (not solo_criticas or f.gravedad is Gravedad.CRITICA)
                   for f in self.noticias or ())

    def _manual(self) -> Callable[[int], bool] | None:
        if not self.comandos:
            return None
        return lambda ts_apertura: cerrar_todo_en(self.comandos, ts_apertura + self.timeframe_ms,
                                                  self.timeframe_ms)

    def _critica(self, symbol: str) -> Callable[[int], bool] | None:
        if not self.noticias:
            return None
        # En HALTED el bot no vende ni por una noticia (el bucle, paso 1b).
        return lambda ts_apertura: (
            self._flag_en(symbol, ts_apertura + self.timeframe_ms, True)
            and self._manual_en(ts_apertura + self.timeframe_ms).kill_ms is None
        )

    def __post_init__(self) -> None:
        if self.decider not in ("baseline", "ai"):
            raise ValueError(f"cartera desconocida: {self.decider}")
        self.bar_at = {
            (s, b.ts_open_ms): b for s, lista in self.bars.items() for b in lista
        }
        cursor = self.record.cursor or 0
        self.outcomes = {
            o["decision_id"]: expected_outcome(o, self.bars.get(o["symbol"], []), cursor,
                                               self._critica(o["symbol"]), self._manual())
            for o in self.record.orders
        }
        self.equity_at = {int(e["ts_ms"]): float(e["equity_usd"]) for e in self.record.equity}
        self.spread_at = {
            (int(m["ts_ms"]), m["symbol"]): float(m["spread_pct"]) for m in self.record.market
        }
        self.usdc_at = {int(u["ts_ms"]): u for u in self.record.usdc}
        self.cuota_al_empezar, self.cuota_al_terminar = self._cuota_por_vela()
        self.solo_cierre = self._modos_deducidos()
        self.cancel_at = self._cancelaciones_esperadas(cursor)
        self.corr_at: dict[int, dict[tuple[str, str], float]] = defaultdict(dict)
        for c in self.record.correlations:
            a, b = sorted((c["a"], c["b"]))
            self.corr_at[int(c["ts_ms"])][(a, b)] = float(c["corr"])
        # Orden en que se enviaron las ordenes de una misma vela: el `id` del
        # journal. La regla 15 mira lo que ya estaba EN EL MOMENTO de evaluar.
        self.submit_seq = {
            d["decision_id"]: d["id"] for d in self.record.decisions
            if d["kind"] == "submitted"
        }

    # --- reconstruccion del estado al cierre de cada vela ---

    def _occupants(self, ts: int) -> list[tuple[str, str, dict[str, Any], Outcome]]:
        """Lo que ocupa hueco AL CIERRE de la vela `ts`, despues de decidir.

        Una entrada ocupa desde que se crea hasta que se llena o caduca; una
        posicion, desde que se llena hasta la vela en que se cierra (esa vela
        ya no la cuenta: se cierra ANTES de decidir).
        """
        out = []
        for o in self.record.orders:
            oc = self.outcomes[o["decision_id"]]
            if o["created_ts_ms"] > ts:
                continue
            # Cancelada al entrar en solo cierre: ocupa hasta esa vela y ya.
            # Va PRIMERO: sin la cancelacion quiza se habria llenado despues.
            cancelada = self.cancel_at.get(o["decision_id"])
            if cancelada is not None:
                if ts < cancelada:
                    out.append(("pendiente", o["symbol"], o, oc))
                continue
            if oc.state == "filled":
                if oc.opened_ts_ms > ts:
                    out.append(("pendiente", o["symbol"], o, oc))
                elif oc.closed_ts_ms is None or oc.closed_ts_ms > ts:
                    out.append(("posicion", o["symbol"], o, oc))
            elif oc.state == "expired":
                caduca = o["created_ts_ms"] + oc.bars_waited * self.timeframe_ms
                if ts < self._expiry_ts(o, oc, caduca):
                    out.append(("pendiente", o["symbol"], o, oc))
            else:
                out.append(("pendiente", o["symbol"], o, oc))
        return out

    def _expiry_ts(self, order: dict[str, Any], oc: Outcome, fallback: int) -> int:
        """La vela en la que caduco: la ENTRY_BARS_TO_LIVE+1 con datos."""
        velas = _bars_after(
            self.bars.get(order["symbol"], []), order["created_ts_ms"],
            self.record.cursor or 0, inclusive=False,
        )
        return velas[oc.bars_waited - 1].ts_open_ms if len(velas) >= oc.bars_waited else fallback

    def _mark(self, symbol: str, ts: int, entry: float) -> float:
        bar = self.bar_at.get((symbol, ts))
        return bar.close if bar else entry

    def _closed_until(self, ts: int) -> list[dict[str, Any]]:
        return [t for t in self.record.trades if t["closed_ts_ms"] <= ts]

    @staticmethod
    def _day(ts: int) -> datetime:
        return datetime.fromtimestamp(ts / 1000, tz=UTC)

    # --- comprobaciones ---

    def run(self) -> list[Check]:
        checks = [
            self.continuidad(),
            self.sin_reprocesar(),
            self.trazabilidad(),
            self.resimulacion(),
            self.contabilidad(),
            self.equity(),
            self.whitelist_y_setups(),
            self.huecos(),
            self.tamanyo(),
            self.exposicion(),
            self.preventiva(),
            self.limites_diarios(),
            self.cooldowns(),
            self.spread_y_coste(),
            self.correlacion(),
            self.paridad_usdc(),
            self.modos(),
            self.propone_y_dispone(),
        ]
        if self.decider == "ai":
            checks += [
                self.analista_presupuesto(),
                self.analista_referencias(),
                self.analista_multiplicador(),
            ]
        return checks

    def continuidad(self) -> Check:
        c = Check("una fila de equity por vela, sin saltos", "72 h")
        ts = [int(e["ts_ms"]) for e in self.record.equity]
        c.comprobados = len(ts)
        if not ts:
            c.falla("no hay ni una vela procesada")
            return c
        for a, b in zip(ts, ts[1:]):
            if b - a != self.timeframe_ms:
                c.falla(f"salto entre {self._fmt(a)} y {self._fmt(b)}")
        if self.record.cursor != ts[-1]:
            c.falla(
                f"el cursor ({self._fmt(self.record.cursor)}) no es la ultima "
                f"vela con equity ({self._fmt(ts[-1])})"
            )
        return c

    def sin_reprocesar(self) -> Check:
        c = Check("ninguna decision apuntada dos veces", "reinicios")
        claves = Counter(
            (d["ts_ms"], d["decision_id"], d["symbol"], d["kind"], d["detail"])
            for d in self.record.decisions
        )
        c.comprobados = len(self.record.decisions)
        for (ts, did, sym, kind, _det), n in claves.items():
            if n > 1:
                c.falla(f"{self._fmt(ts)} {kind} {did or sym} apuntada {n} veces")
        return c

    def trazabilidad(self) -> Check:
        c = Check("cadena candidato -> orden -> llenado -> cierre", "PRD 13")
        enviadas = {
            d["decision_id"]: d for d in self.record.decisions if d["kind"] == "submitted"
        }
        candidatos = {
            d["decision_id"] for d in self.record.decisions if d["kind"] == "candidate"
        }
        ordenes = {o["decision_id"]: o for o in self.record.orders}
        c.comprobados = len(ordenes)

        for did, o in ordenes.items():
            if did not in enviadas:
                c.falla(f"{did}: orden sin su 'submitted' en el journal")
            elif enviadas[did]["ts_ms"] != o["created_ts_ms"]:
                c.falla(f"{did}: el journal y la orden no son de la misma vela")
            if did not in candidatos:
                c.falla(f"{did}: orden sin su candidato en el journal")
            esperado = make_decision_id(o["symbol"], o["setup"], o["created_ts_ms"])
            if did != esperado:
                c.falla(f"{did}: no corresponde a su simbolo/setup/vela ({esperado})")
        for did in enviadas:
            if did not in ordenes:
                c.falla(f"{did}: 'submitted' en el journal pero sin orden")

        llenadas = {did for did, o in ordenes.items() if o["state"] == "filled"}
        cerradas = {t["decision_id"] for t in self.record.trades}
        abiertas = {p["decision_id"] for p in self.record.positions}
        for did in cerradas | abiertas:
            if did not in llenadas:
                c.falla(f"{did}: operacion o posicion sin orden llenada detras")
        for did in llenadas - cerradas - abiertas:
            c.falla(f"{did}: orden llenada que no acabo en posicion ni operacion")
        for did in cerradas & abiertas:
            c.falla(f"{did}: esta a la vez abierta y cerrada")
        return c

    def resimulacion(self) -> Check:
        c = Check("lo guardado coincide con re-simular contra las velas", "simulador")
        trades = {t["decision_id"]: t for t in self.record.trades}
        positions = {p["decision_id"]: p for p in self.record.positions}
        c.comprobados = len(self.record.orders)
        for o in self.record.orders:
            did = o["decision_id"]
            oc = self.outcomes[did]
            if did in self.cancel_at:
                if o["state"] != "cancelled":
                    c.falla(
                        f"{did}: seguia pendiente y tenia que cancelarse "
                        f"{self.cancel_motivo.get(did, 'al entrar en solo cierre')} "
                        f"({self._fmt(self.cancel_at[did])}) (PRD 5)"
                    )
                continue
            if o["state"] == "cancelled":
                c.falla(f"{did}: cancelada sin modo de solo cierre ni noticia que lo pidiera")
                continue
            if o["state"] != oc.state:
                c.falla(
                    f"{did}: guardada como '{o['state']}', las velas dicen '{oc.state}'"
                    " (si es 'filled' vs otra cosa, puede ser una vela que llego tarde)"
                )
                continue
            if oc.state in ("pending", "expired") and o["bars_waited"] != oc.bars_waited:
                c.falla(f"{did}: {o['bars_waited']} velas esperando, deberian ser {oc.bars_waited}")
            if oc.state != "filled":
                continue
            if oc.closed_ts_ms is None:
                p = positions.get(did)
                if p is None:
                    c.falla(f"{did}: deberia seguir abierta y no esta")
                elif p["opened_ts_ms"] != oc.opened_ts_ms:
                    c.falla(f"{did}: abierta en {self._fmt(p['opened_ts_ms'])}, deberia {self._fmt(oc.opened_ts_ms)}")
                continue
            t = trades.get(did)
            if t is None:
                c.falla(f"{did}: deberia estar cerrada ({oc.reason}) y no lo esta")
                continue
            if (t["opened_ts_ms"], t["closed_ts_ms"], t["reason"]) != (
                oc.opened_ts_ms, oc.closed_ts_ms, oc.reason
            ):
                c.falla(
                    f"{did}: guardada {self._fmt(t['opened_ts_ms'])}->{self._fmt(t['closed_ts_ms'])} "
                    f"[{t['reason']}], deberia {self._fmt(oc.opened_ts_ms)}->"
                    f"{self._fmt(oc.closed_ts_ms)} [{oc.reason}]"
                )
            if abs(t["exit_price"] - oc.exit_price) > EPS * max(1.0, oc.exit_price):
                c.falla(f"{did}: salida a {t['exit_price']}, deberia {oc.exit_price}")
            if abs(t["entry_price"] - o["limit_price"]) > EPS * o["limit_price"]:
                c.falla(f"{did}: entrada a {t['entry_price']}, no a su limite {o['limit_price']}")
            for campo in ("qty", "stop_price", "target_price"):
                if abs(t[campo] - o[campo]) > EPS * max(1.0, abs(o[campo])):
                    c.falla(f"{did}: {campo} de la operacion no es el de la orden")
        return c

    def contabilidad(self) -> Check:
        c = Check("comisiones, P&L y R de cada operacion", "costes")
        c.comprobados = len(self.record.trades)
        for t in self.record.trades:
            ins = self.instruments.get(t["symbol"])
            if ins is None:
                c.falla(f"{t['decision_id']}: instrumento desconocido")
                continue
            qty, entrada, salida = t["qty"], t["entry_price"], t["exit_price"]
            fee_in = qty * entrada * ins.maker_fee
            maker_out = t["reason"] == "target"
            fee_out = qty * salida * (ins.maker_fee if maker_out else ins.taker_fee)
            neto = (salida - entrada) * qty - fee_in - fee_out
            riesgo = (entrada - t["stop_price"]) * qty
            r = neto / riesgo if riesgo > 0 else 0.0
            for nombre, guardado, calculado in (
                ("comision de entrada", t["entry_fee_usd"], fee_in),
                ("comision de salida", t["exit_fee_usd"], fee_out),
                ("P&L neto", t["net_pnl_usd"], neto),
                ("resultado en R", t["r_multiple"], r),
            ):
                if abs(guardado - calculado) > EPS:
                    c.falla(f"{t['decision_id']}: {nombre} {guardado:.6f}, deberia {calculado:.6f}")
            if bool(t["exit_was_maker"]) != maker_out:
                c.falla(f"{t['decision_id']}: salida maker/taker mal apuntada")
        return c

    def equity(self) -> Check:
        """Regla 6 en papel, recalculada vela a vela."""
        c = Check("equity y contadores de cada vela", "regla 6")
        c.comprobados = len(self.record.equity)
        for fila in self.record.equity:
            ts = int(fila["ts_ms"])
            total = self.starting_usd + sum(t["net_pnl_usd"] for t in self._closed_until(ts))
            ocupan = self._occupants(ts)
            posiciones = [x for x in ocupan if x[0] == "posicion"]
            for _k, sym, o, _oc in posiciones:
                ins = self.instruments.get(sym)
                if ins is None:
                    c.falla(f"{self._fmt(ts)}: posicion en {sym}, instrumento desconocido")
                    continue
                mark = self._mark(sym, ts, o["limit_price"])
                qty = o["qty"]
                total += qty * (mark - o["limit_price"])
                total -= qty * o["limit_price"] * ins.maker_fee
                total -= qty * mark * ins.taker_fee
            if abs(fila["equity_usd"] - total) > EPS:
                c.falla(f"{self._fmt(ts)}: equity {fila['equity_usd']:.6f}, deberia {total:.6f}")
            pendientes = len(ocupan) - len(posiciones)
            if (fila["positions"], fila["pending"]) != (len(posiciones), pendientes):
                c.falla(
                    f"{self._fmt(ts)}: {fila['positions']} pos./{fila['pending']} pend. "
                    f"apuntadas, deberian ser {len(posiciones)}/{pendientes}"
                )
        return c

    # --- reglas duras, en cada instante en que se envio algo ---

    def _envios(self) -> dict[int, list[dict[str, Any]]]:
        por_vela: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for o in self.record.orders:
            por_vela[o["created_ts_ms"]].append(o)
        return dict(sorted(por_vela.items()))

    def _limits(self, c: Check, ts: int) -> Limits | None:
        equity = self.equity_at.get(ts)
        if equity is None:
            c.falla(f"{self._fmt(ts)}: se envio una orden en una vela sin equity apuntado")
            return None
        return Limits.for_state(self.settings, equity, self.slider_level)

    def whitelist_y_setups(self) -> Check:
        c = Check("solo pares de la whitelist y setups del slider", "reglas 3 y slider")
        whitelist = set(self.settings.whitelist)
        c.comprobados = len(self.record.orders)
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            for o in ordenes:
                if o["symbol"] not in whitelist:
                    c.falla(f"{o['decision_id']}: {o['symbol']} no esta en la whitelist")
                if lim and o["setup"] not in lim.allowed_setups:
                    c.falla(f"{o['decision_id']}: setup {o['setup']} no permitido en el slider")
        return c

    def huecos(self) -> Check:
        c = Check("nunca mas huecos ocupados de los permitidos", "reglas 4 y 9")
        for ts in self._envios():
            c.comprobados += 1
            lim = self._limits(c, ts)
            if lim is None:
                continue
            ocupan = self._occupants(ts)
            if len(ocupan) > lim.max_positions:
                c.falla(f"{self._fmt(ts)}: {len(ocupan)} ocupados, tope {lim.max_positions}")
            por_simbolo = Counter(sym for _k, sym, _o, _oc in ocupan)
            for sym, n in por_simbolo.items():
                if n > lim.max_positions_per_symbol:
                    c.falla(f"{self._fmt(ts)}: {n} cosas vivas en {sym}")
        return c

    def tamanyo(self) -> Check:
        c = Check("riesgo, nocional y minimos de cada orden", "reglas 12 y 9")
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            if lim is None:
                continue
            for o in ordenes:
                c.comprobados += 1
                did, qty, limite = o["decision_id"], o["qty"], o["limit_price"]
                ins = self.instruments.get(o["symbol"])
                if ins is None:
                    c.falla(f"{did}: instrumento desconocido {o['symbol']}")
                    continue
                if not (o["stop_price"] < limite < o["target_price"]):
                    c.falla(f"{did}: precios fuera de orden stop < entrada < objetivo")
                riesgo = qty * (limite - o["stop_price"])
                if riesgo > lim.risk_per_trade_usd + EPS:
                    c.falla(f"{did}: riesgo {riesgo:.4f} $ > permitido {lim.risk_per_trade_usd:.4f} $")
                nocional = qty * limite
                if nocional > lim.max_notional_usd + EPS:
                    c.falla(f"{did}: nocional {nocional:.2f} $ > tope {lim.max_notional_usd:.2f} $")
                if nocional < ins.min_notional_usd(limite) - EPS:
                    c.falla(f"{did}: nocional {nocional:.4f} $ por debajo del minimo del par")
                lotes = qty / ins.lot_size
                if abs(lotes - round(lotes)) > 1e-6:
                    c.falla(f"{did}: cantidad {qty} no es multiplo del lote {ins.lot_size}")
        return c

    def exposicion(self) -> Check:
        c = Check("exposicion nunca por encima del tope al entrar", "regla 15")
        for ts in self._envios():
            c.comprobados += 1
            lim = self._limits(c, ts)
            if lim is None:
                continue
            total = 0.0
            for kind, sym, o, _oc in self._occupants(ts):
                precio = self._mark(sym, ts, o["limit_price"]) if kind == "posicion" else o["limit_price"]
                total += o["qty"] * precio
            if total > lim.max_exposure_usd + EPS:
                c.falla(f"{self._fmt(ts)}: exposicion {total:.2f} $ > tope {lim.max_exposure_usd:.2f} $")
        return c

    def preventiva(self) -> Check:
        """Regla 8, sin comisiones: mas laxa que el motor, asi que si esto
        falla, el motor seguro que tambien deberia haber vetado."""
        c = Check("todo al stop deja el equity sobre suelo + colchon", "regla 8")
        for ts in self._envios():
            c.comprobados += 1
            lim = self._limits(c, ts)
            if lim is None:
                continue
            perdida = 0.0
            for kind, sym, o, _oc in self._occupants(ts):
                desde = self._mark(sym, ts, o["limit_price"]) if kind == "posicion" else o["limit_price"]
                perdida += max(0.0, desde - o["stop_price"]) * o["qty"]
            queda = self.equity_at[ts] - perdida
            if queda < lim.min_equity_after_stops_usd - EPS:
                c.falla(f"{self._fmt(ts)}: todo al stop dejaria {queda:.2f} $ < {lim.min_equity_after_stops_usd:.2f} $")
        return c

    def limites_diarios(self) -> Check:
        c = Check("perdida y operaciones del dia", "reglas 10 y 11")
        for ts in self._envios():
            c.comprobados += 1
            lim = self._limits(c, ts)
            if lim is None:
                continue
            dia = self._day(ts).date()
            hoy = [t for t in self._closed_until(ts) if self._day(t["closed_ts_ms"]).date() == dia]
            perdida = -sum(t["net_pnl_usd"] for t in hoy)
            if perdida >= lim.daily_loss_limit_usd - EPS:
                c.falla(f"{self._fmt(ts)}: se entro con {perdida:.2f} $ perdidos hoy (tope {lim.daily_loss_limit_usd})")
            usadas = len(hoy) + len(self._occupants(ts))
            if usadas > lim.max_trades_per_day:
                c.falla(f"{self._fmt(ts)}: {usadas} operaciones hoy, tope {lim.max_trades_per_day}")
        return c

    def cooldowns(self) -> Check:
        c = Check("cooldown tras stop y pausa tras perdidas seguidas", "regla 14")
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            if lim is None:
                continue
            ahora = self._day(ts)
            cerradas = self._closed_until(ts)
            for o in ordenes:
                c.comprobados += 1
                stops = [
                    t for t in cerradas
                    if t["symbol"] == o["symbol"] and t["reason"] == "stop"
                ]
                if stops:
                    hasta = self._day(max(t["closed_ts_ms"] for t in stops)) + timedelta(
                        hours=lim.cooldown_after_stop_hours
                    )
                    if ahora < hasta:
                        c.falla(f"{o['decision_id']}: entrada en {o['symbol']} en cooldown hasta {hasta:%d/%m %H:%M}")
            racha = 0
            for t in sorted(cerradas, key=lambda t: t["closed_ts_ms"], reverse=True):
                if t["net_pnl_usd"] < 0:
                    racha += 1
                else:
                    break
            if racha >= lim.consecutive_losses_for_pause:
                ultima = max(t["closed_ts_ms"] for t in cerradas if t["net_pnl_usd"] < 0)
                hasta = self._day(ultima) + timedelta(hours=lim.pause_after_losses_hours)
                if ahora < hasta:
                    c.falla(f"{self._fmt(ts)}: entrada durante la pausa por {racha} perdidas seguidas")
        return c

    def spread_y_coste(self) -> Check:
        """Regla 16, con el spread que vio el bucle y la formula escrita aparte:
        entrada maker, salida TAKER sobre el nocional de salida, medio spread."""
        c = Check("spread y objetivo >= 3x el coste al entrar", "regla 16")
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            if lim is None:
                continue
            for o in ordenes:
                spread = self.spread_at.get((ts, o["symbol"]))
                ins = self.instruments.get(o["symbol"])
                if spread is None or ins is None:
                    c.sin_datos += 1
                    continue
                c.comprobados += 1
                did = o["decision_id"]
                if spread > lim.max_entry_spread_pct + EPS:
                    c.falla(f"{did}: entro con spread {spread:.4f} % > {lim.max_entry_spread_pct} %")
                objetivo = (o["target_price"] - o["limit_price"]) / o["limit_price"] * 100
                coste = (
                    ins.maker_fee * 100
                    + ins.taker_fee * 100 * (1 + objetivo / 100)
                    + spread / 2
                )
                if objetivo / coste < lim.min_target_cost_ratio - EPS:
                    c.falla(
                        f"{did}: objetivo {objetivo:.3f} % = {objetivo / coste:.2f}x el coste "
                        f"({coste:.3f} %), hace falta {lim.min_target_cost_ratio}x"
                    )
        return c

    def correlacion(self) -> Check:
        """Regla 15, mitad de correlacion: al evaluar cada orden, cuantas de las
        que YA estaban vivas correlacionan con ella por encima del umbral."""
        c = Check("nunca demasiadas posiciones correlacionadas", "regla 15")
        sin_medir: set[int] = set()
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            if lim is None:
                continue
            if ts in self.corr_at:
                corr = self.corr_at[ts]
            elif any(t == ts for t, _s in self.spread_at):
                # Hay contexto guardado pero NINGUNA correlacion: no habia
                # historial de 1 h suficiente. Todas las parejas estan sin
                # medir, y sin medir cuenta como correlacionada.
                corr = {}
                sin_medir.add(ts)
            else:
                c.sin_datos += len(ordenes)
                continue
            ocupan = self._occupants(ts)
            for o in ordenes:
                c.comprobados += 1
                mio = self.submit_seq.get(o["decision_id"], 0)
                antes = {
                    sym for _k, sym, x, _oc in ocupan
                    if x["decision_id"] != o["decision_id"]
                    and (x["created_ts_ms"] < ts
                         or self.submit_seq.get(x["decision_id"], 0) < mio)
                }
                # Decision del propietario del 22/09/2026: sin medir = correlacionada.
                correladas = sorted(
                    s for s in antes
                    if s != o["symbol"]
                    and corr.get(tuple(sorted((s, o["symbol"]))), 1.0) > lim.correlation_threshold
                )
                if len(correladas) >= lim.max_correlated_positions:
                    c.falla(
                        f"{o['decision_id']}: entro correlacionada > {lim.correlation_threshold}"
                        f" con {correladas} (tope {lim.max_correlated_positions})"
                    )
        if sin_medir:
            c.notas.append(
                f"{len(sin_medir)} vela(s) con ordenes y SIN ninguna correlacion medida "
                f"(historial de 1 h insuficiente): auditadas como correlacionadas, "
                f"que es como decide el motor desde el 22/09/2026."
            )
        return c

    # --- modos (PRD seccion 5), deducidos por su cuenta ---

    def _modos_deducidos(self) -> dict[int, bool]:
        """Vela -> esta en solo cierre al terminarla, deducido de lo guardado.

        CLOSE_ONLY_CAPITAL (regla 7): dos lecturas seguidas en o bajo el suelo,
        y enclavado hasta un reset manual (lo unico que se lee del journal de
        modos, porque no se puede deducir: lo hace una persona).
        CLOSE_ONLY_DAILY (regla 10): la perdida realizada del dia UTC llega al
        limite.
        CLOSE_ONLY_QUOTA (fase 3): NO se puede deducir de la cartera (depende de
        lo que conteste Claude), asi que se lee del journal de modos, como el
        reset manual. Ver `_cuota_por_vela`.
        """
        suelo = self.settings.capital.floor_usd
        limite = self.settings.risk.daily_loss_limit_usd
        resets = sorted(
            int(m["ts_ms"]) for m in self.record.mode_changes
            if m["mode"] == "CLOSE_ONLY_CAPITAL" and not m["activated"]
            and str(m["reason"]).startswith("RESET MANUAL")
        )
        out: dict[int, bool] = {}
        enclavado = False
        previo: tuple[int, float] | None = None
        for fila in self.record.equity:
            ts, eq = int(fila["ts_ms"]), float(fila["equity_usd"])
            if previo is not None and any(previo[0] < r <= ts for r in resets):
                enclavado = False
            if previo is not None and previo[1] <= suelo and eq <= suelo:
                enclavado = True
            dia = self._day(ts).date()
            perdida = -sum(
                t["net_pnl_usd"] for t in self._closed_until(ts)
                if self._day(t["closed_ts_ms"]).date() == dia
            )
            manual = bool(self._manual_en(ts + self.timeframe_ms).modos)    # /pause o /kill
            out[ts] = (enclavado or perdida >= limite - EPS or self.cuota_al_terminar.get(ts, False)
                       or manual)
            previo = (ts, eq)
        return out

    def _cuota_por_vela(self) -> tuple[dict[int, bool], dict[int, bool]]:
        """Vela -> CLOSE_ONLY_QUOTA puesto al EMPEZAR a procesarla y al TERMINAR.

        Un cambio guardado con la marca de una vela se hizo mientras se
        procesaba esa vela (la llamada de decision que choco con la cuota o con
        el presupuesto): cuenta al terminarla, no al empezarla. Uno guardado
        entre velas (la salida por sonda) cuenta desde la primera vela que se
        proceso despues, y una vela se procesa al cerrar: `ts + timeframe`.
        """
        velas = sorted(self.equity_at)
        es_vela = set(velas)
        cambios = [
            (int(m["ts_ms"]), bool(m["activated"]))
            for m in self.record.mode_changes if m["mode"] == QUOTA
        ]
        empezar: dict[int, bool] = {}
        terminar: dict[int, bool] = {}
        for ts in velas:
            antes = despues = False
            for t, activo in cambios:       # en el orden en que se guardaron
                if t in es_vela:
                    if t < ts:
                        antes = activo
                    if t <= ts:
                        despues = activo
                elif t < ts + self.timeframe_ms:
                    antes = despues = activo
            empezar[ts], terminar[ts] = antes, despues
        return empezar, terminar

    def _cancelaciones_esperadas(self, cursor: int) -> dict[str, int]:
        """decision_id -> vela en la que TENIA que cancelarse.

        Al pasar de NORMAL a solo cierre en la vela T, se cancela toda entrada
        que siga pendiente despues de procesar la vela T (la vela primero llena
        o caduca, y luego se miran los modos).
        """
        entradas = []
        anterior = False
        for ts in sorted(self.solo_cierre):
            if self.solo_cierre[ts] and not anterior:
                entradas.append(ts)
            anterior = self.solo_cierre[ts]
        out: dict[str, int] = {}
        self.cancel_motivo: dict[str, str] = {}
        for o in self.record.orders:
            for t in entradas:
                if t <= o["created_ts_ms"]:
                    continue
                hasta_t = expected_outcome(o, self.bars.get(o["symbol"], []), t)
                if hasta_t.state == "pending":
                    out[o["decision_id"]] = t
                    self.cancel_motivo[o["decision_id"]] = "al entrar en solo cierre"
                break
        # Noticias (pieza 4d): con CUALQUIER flag activa al cierre de una vela, la entrada que siga
        # pendiente despues de esa vela se cancela. Gana la primera de las dos cancelaciones.
        for o in self.record.orders if self.noticias else ():
            for b in self.bars.get(o["symbol"], []):
                t = b.ts_open_ms
                if t <= o["created_ts_ms"] or t > cursor:
                    continue
                if o["decision_id"] in out and out[o["decision_id"]] <= t:
                    break
                if not self._flag_en(o["symbol"], t + self.timeframe_ms, False):
                    continue
                if expected_outcome(o, self.bars.get(o["symbol"], []), t).state == "pending":
                    out[o["decision_id"]] = t
                    self.cancel_motivo[o["decision_id"]] = "por una noticia"
                break
        return out

    def modos(self) -> Check:
        c = Check("ninguna entrada en modo de solo cierre, y pendientes canceladas",
                  "PRD 5, reglas 7, 10 y 18, comandos")
        for ts, ordenes in self._envios().items():
            c.comprobados += len(ordenes)
            if self.solo_cierre.get(ts):
                for o in ordenes:
                    c.falla(f"{o['decision_id']}: se envio con el bot en modo de solo cierre")
        for did, t in self.cancel_at.items():
            c.comprobados += 1
            estado = next(o["state"] for o in self.record.orders if o["decision_id"] == did)
            if estado != "cancelled":
                c.falla(f"{did}: no se cancelo {self.cancel_motivo.get(did, 'al entrar en solo cierre')}"
                        f" ({self._fmt(t)})")
        entradas = sum(
            1 for a, b in zip([False, *self.solo_cierre.values()], self.solo_cierre.values())
            if b and not a
        )
        if entradas:
            c.notas.append(f"{entradas} entrada(s) en modo de solo cierre en el periodo")
        return c

    def paridad_usdc(self) -> Check:
        """Regla 17: ninguna entrada con la paridad desconocida o desviada."""
        c = Check("USDC en paridad al entrar", "regla 17")
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            if lim is None:
                continue
            lectura = self.usdc_at.get(ts)
            if lectura is None:
                c.sin_datos += len(ordenes)
                continue
            for o in ordenes:
                c.comprobados += 1
                dev = lectura["deviation_pct"]
                if dev is None:
                    c.falla(f"{o['decision_id']}: entro con la paridad DESCONOCIDA ({lectura['detail']})")
                elif abs(dev) > lim.usdc_depeg_pct + EPS:
                    c.falla(f"{o['decision_id']}: entro con USDC desviado {dev:+.2f} %")
        return c

    # --- el analista (fase 3, pieza 10): la IA propone, el motor dispone ---

    def _opens_del_analista(self) -> dict[tuple[int, str], float | None]:
        """(vela, ref) -> multiplicador, de cada `open` de una llamada VALIDA."""
        validas = {
            int(x["id"]): int(x["ts_ms"]) for x in self.record.ai_calls
            if x["kind"] == "decision" and x["valid"]
        }
        return {
            (validas[int(d["call_id"])], d["ref"]): d["size_multiplier"]
            for d in self.record.ai_decisions
            if d["type"] == "open" and int(d["call_id"]) in validas
        }

    def propone_y_dispone(self) -> Check:
        """Vale para las dos carteras.

        - Ninguna orden de algo que el motor veto (la IA no se salta el motor).
        - Cada operacion cerrada es de ESTA cartera.
        - Baseline: ni una llamada a Claude. Es el grupo de control: si la IA se
          colara aqui, la comparacion de la fase 6 no mediria nada.
        - IA: cada orden es un `open` del analista EN ESA VELA, y con el
          multiplicador aplicado (el riesgo no pasa de riesgo x multiplicador).
        - IA: ninguna orden de un candidato EN SOMBRA (decision 5 de la fase 6, 02/10): la sombra no abre
          nunca nada. Un `open` en sombra no autoriza ninguna orden (`_opens_del_analista` solo mira las de
          verdad), y aqui se comprueba ademas por el id.
        """
        c = Check("la IA propone y el motor dispone", "PRD 6")
        vetadas = {d["decision_id"] for d in self.record.decisions if d["kind"] == "vetoed"}
        for o in self.record.orders:
            c.comprobados += 1
            if o["decision_id"] in vetadas:
                c.falla(f"{o['decision_id']}: se envio una orden que el motor habia vetado")
        for t in self.record.trades:
            if t["decider"] != self.decider:
                c.falla(f"{t['decision_id']}: operacion de '{t['decider']}' en la cartera de '{self.decider}'")
        if self.decider == "baseline":
            if self.record.ai_calls:
                c.falla(f"la cartera del baseline tiene {len(self.record.ai_calls)} fila(s) "
                        f"del journal del analista: el grupo de control va SIN IA")
            return c
        en_sombra: set[str] = set()
        for x in self.record.ai_calls:
            if x["kind"] == "sombra" and x["prompt"]:
                try:
                    entrada = json.loads(str(x["prompt"]).split("\n", 1)[0])
                    en_sombra |= {k["cid"] for k in entrada["candidates"]}
                except (ValueError, KeyError, TypeError):
                    c.falla(f"llamada en sombra {x['id']}: la entrada no se puede leer")
        for o in self.record.orders:
            if o["decision_id"] in en_sombra:
                c.falla(f"{o['decision_id']}: orden de un candidato EN SOMBRA (la sombra no abre nada)")
        opens = self._opens_del_analista()
        for ts, ordenes in self._envios().items():
            lim = self._limits(c, ts)
            for o in ordenes:
                did = o["decision_id"]
                if (ts, did) not in opens:
                    c.falla(f"{did}: orden que el analista no eligio en esa vela")
                    continue
                m = opens[(ts, did)]
                if lim is None or m is None:
                    continue    # sin multiplicador lo canta `analista_multiplicador`
                riesgo = o["qty"] * (o["limit_price"] - o["stop_price"])
                if riesgo > lim.risk_per_trade_usd * m + EPS:
                    c.falla(f"{did}: riesgo {riesgo:.4f} $ > {lim.risk_per_trade_usd:.4f} $ x {m:g}: "
                            f"no se aplico el multiplicador del analista")
        return c

    def analista_presupuesto(self) -> Check:
        """Regla 18, contando por su cuenta en el journal, y el modo QUOTA.

        Cuenta las llamadas HECHAS (tambien las que fallaron: gastan cuota), por
        el reloj real al llamar. Las sondas cuentan igual que las decisiones.
        """
        c = Check("el analista nunca por encima del presupuesto", "regla 18")
        por_dia = self.settings.claude.max_calls_per_day
        por_ventana = self.settings.claude.max_calls_per_5h_window
        hechas = sorted(int(x["called_ms"]) for x in self.record.ai_calls if x["outcome"] not in NO_LLAMO)
        for i, t in enumerate(hechas):
            c.comprobados += 1
            hasta_aqui = hechas[: i + 1]
            hoy = sum(1 for x in hasta_aqui if self._day(x).date() == self._day(t).date())
            ventana = sum(1 for x in hasta_aqui if x > t - VENTANA_5H_MS)
            if hoy > por_dia:
                c.falla(f"{self._fmt(t)}: llamada n.o {hoy} del dia, tope {por_dia}")
            if ventana > por_ventana:
                c.falla(f"{self._fmt(t)}: {ventana} llamadas en 5 h, tope {por_ventana}")
        for x in self.record.ai_calls:
            if x["kind"] != "decision":
                continue
            c.comprobados += 1
            ts = int(x["ts_ms"])
            if x["outcome"] not in NO_LLAMO and self.cuota_al_empezar.get(ts):
                c.falla(f"{self._fmt(ts)}: se llamo al analista para decidir en {QUOTA} (solo sondas)")
            if x["outcome"] == "skipped_quota" and not self.cuota_al_empezar.get(ts):
                c.falla(f"{self._fmt(ts)}: no se llamo 'por cuota' sin estar en {QUOTA}")
            # Decision del propietario del 23/09/2026: presupuesto agotado = QUOTA.
            if x["outcome"] == "skipped_budget" and not self.cuota_al_terminar.get(ts):
                c.falla(f"{self._fmt(ts)}: presupuesto agotado sin entrar en {QUOTA}")
        return c

    def analista_referencias(self) -> Check:
        """El analista solo decide sobre lo que se le ofrecio, y sobre todo ello.

        La entrada se lee del prompt GUARDADO (la primera linea es el JSON que
        se envio). Una salida invalida no deja decisiones: vale "no hacer nada".
        """
        c = Check("el analista solo decide sobre lo que se le ofrecio", "PRD 6, contrato")
        por_llamada: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for d in self.record.ai_decisions:
            por_llamada[int(d["call_id"])].append(d)
        for x in self.record.ai_calls:
            c.comprobados += 1
            cid, filas = int(x["id"]), por_llamada.get(int(x["id"]), [])
            donde = f"llamada {cid} ({self._fmt(int(x['ts_ms']))})"
            if x["kind"] not in ("decision", "sombra") or not x["valid"]:
                if filas:
                    c.falla(f"{donde}: {len(filas)} decision(es) apuntadas de una salida invalida o de una sonda")
                continue
            if x["outcome"] != "ok":
                c.falla(f"{donde}: valida con resultado '{x['outcome']}'")
            try:
                entrada = json.loads(str(x["prompt"]).split("\n", 1)[0])
                cids = {k["cid"] for k in entrada["candidates"]}
                posiciones = {p["id"] for p in entrada["portfolio"]["open_positions"]}
            except (ValueError, KeyError, TypeError):
                c.falla(f"{donde}: la entrada no esta guardada o no se puede leer")
                continue
            if x["n_candidates"] != len(cids):
                c.falla(f"{donde}: apunta {x['n_candidates']} candidatos y la entrada tenia {len(cids)}")
            for d in filas:
                validos = cids if d["type"] in TIPOS_CANDIDATO else posiciones
                if d["ref"] not in validos:
                    c.falla(f"{donde}: '{d['type']}' sobre '{d['ref']}', que no se le ofrecio")
            sin_fila = cids - {d["ref"] for d in filas if d["type"] in TIPOS_CANDIDATO}
            if sin_fila:
                c.falla(f"{donde}: candidatos sin decision apuntada: {sorted(sin_fila)}")
        return c

    def analista_multiplicador(self) -> Check:
        c = Check("el analista solo reduce el tamanyo", "PRD 6")
        for d in self.record.ai_decisions:
            if d["type"] != "open":
                continue
            c.comprobados += 1
            m = d["size_multiplier"]
            if m is None or not (MULTIPLICADOR_MIN - EPS <= m <= MULTIPLICADOR_MAX + EPS):
                c.falla(f"{d['ref']}: multiplicador {m} fuera de [{MULTIPLICADOR_MIN}; {MULTIPLICADOR_MAX}]")
        return c

    @staticmethod
    def _fmt(ts: int | None) -> str:
        if ts is None:
            return "nada"
        return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%d/%m %H:%M")
