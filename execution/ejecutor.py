"""El ejecutor del demo (fase 4, pieza c): una vuelta cada 15 s, la conciliacion completa cada 5 min.

Une las piezas puras con OKX y con su base (`execution/store.py`). En cada vuelta, en este orden:

1. **Leer OKX** (saldo, ordenes, OCO, bids). Un error sube a la salud: 3 seguidos -> `CLOSE_ONLY_DEGRADED`, y 10 min
   sano para salir (decision 6 del 26/09). Con una lectura a medias no se corrige nada.
2. **Regla 6 y 7** con el saldo VIRTUAL (50 $ + lo cambiado desde la foto; decision del 02/10): equity cada vuelta, dos
   lecturas seguidas en o bajo el suelo -> `CLOSE_ONLY_CAPITAL` enclavado (se guarda: sobrevive al reinicio).
   **Regla 10** con las perdidas del dia del DEMO -> `CLOSE_ONLY_DAILY` hasta las 00:00 UTC.
   **Pausa y parada** de Telegram o del panel (base de control), al momento.
3. Si el modo no es NORMAL: **cancelar las entradas pendientes** (PRD 5), en el momento (pieza f).
4. **Conciliacion** (cada 5 min; gana el exchange) y su plan; entre pasadas, solo lo urgente: una entrada a medias ->
   cancelar el resto al momento (decision del 02/10: asi OKX crea la OCO por lo llenado).
5. **El espejo** de la cartera de la IA (`execution/espejo.py`): vender, cancelar, copiar (con el motor de riesgo
   entero y el estado del demo, `execution/riesgo.py`) u omitir.

Nunca lanza por un error de OKX: lo apunta, lo cuenta y sigue en la vuelta siguiente.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ccxt

from core.config import Settings
from core.modes import Mode, ModeMachine
from core.salud import ENTRAR, SALIR, Salud, Senyales, evaluar
from execution import espejo, ids, lectura, ordenes, peticiones, riesgo
from execution import store as db
from execution.conciliacion import EntradaLocal, Exchange, Local, PosicionLocal, conciliar
from execution.equity import EquityBreakdown, Foto, Vigia, virtual
from execution.equity import lectura as leer_equity
from execution.ordenes import Resultado
from execution.plan import CANCELAR_OCO, CANCELAR_RESTO, CREAR_OCO, planear
from execution.precios import al_tick, techo_al_paso
from notify import messages as mensajes
from risk.limits import Limits
from risk.types import Instrument

log = logging.getLogger("ploutos.exec")

VUELTA_MS = 15_000
# Los codigos de OKX de una clave rechazada (hallazgos-fase-0-1; 50123 visto el 02/10: moneda no permitida en la clave).
CODIGOS_CLAVE = ("50101", "50105", "50110", "50111", "50113", "50114", "50119", "50123")
PASADA_MS = 5 * 60_000


def _ms_a_dia(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _es_nuestro(id_okx: str) -> bool:
    try:
        ids.decision_id_de(id_okx)
        return True
    except ids.IdInvalido:
        return False


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Informe:
    """Lo que paso en una vuelta (para el log, el estado y los tests)."""

    ts_ms: int
    leido: bool = False
    pasada: bool = False
    equity: EquityBreakdown | None = None
    modo: Mode = Mode.NORMAL
    hechos: list[str] = field(default_factory=list)


class Ejecutor:
    def __init__(self, *, ex: Any, settings: Settings, conn: sqlite3.Connection, papel_db: Path,
                 instrumentos: dict[str, Instrument], operables: Iterable[str], tf_ms: int,
                 manuales: Callable[[int], dict[Mode, str] | None] = lambda _ms: None,
                 flags: Callable[[int], dict[str, tuple[str, ...]]] = lambda _ms: {},
                 reloj: Callable[[], int] = lambda: int(time.time() * 1000)) -> None:
        self.ex, self.settings, self.conn = ex, settings, conn
        self.papel_db = Path(papel_db)
        self.instrumentos = instrumentos
        self.operables = tuple(operables)
        self.whitelist = tuple(settings.whitelist)
        self.tf_ms = tf_ms
        self.manuales, self.flags, self.reloj = manuales, flags, reloj
        self.salud = Salud()
        self.vigia = Vigia()
        self.modos = ModeMachine()
        for nombre, motivo in db.modos_activos(conn).items():
            self.modos.activate(Mode[nombre], motivo)      # CAPITAL enclavado, DAILY, pausa: tal como estaban
        self._ultima_pasada_ms = 0
        ultima = db.ultima_pasada(conn)
        self._sin_oco = frozenset(json.loads(ultima["sin_oco"])) if ultima is not None else frozenset()
        self._ultimo_minuto_equity = -1
        self._esperando: set[str] = set()      # decisiones que esperan a que el modo deje abrir (log una vez)
        self._canceladas: set[str] = set()     # entradas ya canceladas: no se repite cada 15 s

    # --- arranque ---------------------------------------------------------------------------------------------

    def foto(self) -> tuple[int, float, Foto]:
        """La foto del saldo: la guardada o, la primera vez, una nueva (decision del 02/10)."""
        guardada = db.foto(self.conn)
        if guardada is not None:
            return guardada
        ahora = self.reloj()
        # Si ya hay ordenes u OCO NUESTRAS vivas, esta base no es la primera: se perdio. Una foto nueva contaria como
        # ajeno lo que es del bot. No se hace: hay que restaurar la base de la copia (revision del 03/10).
        vivas = lectura.ordenes(self.ex, desde_ms=0, completo=False)
        nuestras = [x.get("clOrdId") or x.get("algoClOrdId") for x in vivas.ordenes + vivas.ocos
                    if _es_nuestro(x.get("clOrdId") or x.get("algoClOrdId") or "")]
        if nuestras:
            raise RuntimeError(f"sin foto y con {len(nuestras)} orden(es) u OCO nuestras vivas en OKX ({nuestras[:3]}): "
                               "la base del ejecutor se perdio; restaurarla de la copia, no hacer una foto nueva")
        f = Foto.de_saldo(lectura.saldo(self.ex, self.whitelist))
        capital = self.settings.capital.initial_capital_usd
        db.guardar_foto(self.conn, ahora, capital, f)
        db.apuntar(self.conn, ahora, None, "foto", "guardada", f"capital {capital} $; {f.a_dict()}")
        log.info("foto del saldo guardada: el bot cuenta como suyo %.2f USDC desde ahora", capital)
        return ahora, capital, f

    # --- una vuelta -------------------------------------------------------------------------------------------

    def vuelta(self) -> Informe:
        ahora = self.reloj()
        inf = Informe(ahora)
        foto_ms, capital, foto = self.foto()
        completo = ahora - self._ultima_pasada_ms >= PASADA_MS
        try:
            saldo = virtual(lectura.saldo(self.ex, self.whitelist), foto, capital_inicial=capital)
            okx = lectura.ordenes(self.ex, desde_ms=foto_ms, completo=completo)
            con_algo = {s for s in self.whitelist if abs(saldo.monedas.get(s.split("/")[0], 0.0)) > 0}
            bids = lectura.bids(self.ex, con_algo)
            desfase = self._desfase_reloj(ahora) if completo else None
        except Exception as exc:  # noqa: BLE001 - OKX o la red: se cuenta para DEGRADED y se sigue
            log.warning("no se pudo leer OKX: %s", exc)
            db.apuntar(self.conn, ahora, None, "leer", "error", f"{type(exc).__name__}: {str(exc)[:300]}")
            if isinstance(exc, (ccxt.AuthenticationError, ccxt.PermissionDenied)):
                # PRD 9: el error de autenticacion de OKX, dicho como tal (no solo "errores seguidos"); una vez por hora.
                # Solo el tipo y el codigo de OKX: nunca la URL ni las cabeceras.
                codigo = next((c for c in CODIGOS_CLAVE if c in str(exc)), "")
                self._aviso("auth", f"exec:auth:{ahora // 3_600_000}", mensajes.error_autenticacion(
                    "OKX (demo)", f"{type(exc).__name__} {codigo}".strip()), ahora)
            self._salud(Senyales(ahora, error_exchange=True), inf)
            inf.modo = self.modos.effective
            return inf
        inf.leido = True
        self._salud(Senyales(ahora, error_exchange=False, desfase_reloj_ms=desfase), inf)

        # 2. Reglas 6, 7 y 10; pausa y parada.
        taker = self.settings.exchange.fees.taker_pct / 100
        equity = leer_equity(saldo, bids, whitelist=self.whitelist, taker=taker)
        inf.equity = equity
        self._regla_7(equity, ahora, inf)
        self._regla_10(equity, ahora, inf)
        self._manuales(ahora, inf)
        inf.modo = self.modos.effective

        # 3. Fuera de NORMAL: ninguna entrada pendiente.
        if inf.modo is not Mode.NORMAL:
            for e in db.entradas(self.conn):
                self._cancelar_entrada(e.decision_id, e.simbolo, f"modo {inf.modo}", ahora, inf)

        # 4. Conciliacion (o lo urgente entre pasadas).
        if completo:
            self._conciliar(saldo, okx, bids, ahora, inf)
        else:
            self._resto_de_parciales(okx, ahora, inf)

        # 5. El espejo.
        self._espejo(foto_ms, equity, bids, ahora, inf)
        return inf

    # --- salud, modos ------------------------------------------------------------------------------------------

    def _desfase_reloj(self, ahora: int) -> int | None:
        try:
            return ahora - int(self.ex.fetch_time())
        except Exception:  # noqa: BLE001 - sin hora del servidor no se sabe: no cuenta como desfase
            return None

    def _cambio(self, cambio: Any, ahora: int, inf: Informe) -> None:
        if cambio is None:
            return
        db.guardar_modo(self.conn, ahora, cambio.mode.name, cambio.activated, cambio.reason)
        texto = (f"{'Entra en' if cambio.activated else 'Sale de'} {cambio.mode}: {cambio.reason}"
                 f" (modo efectivo: {cambio.effective_after})")
        inf.hechos.append(texto)
        self._aviso("modo", f"modo:{cambio.mode.name}:{int(cambio.activated)}:{ahora}",
                    f"<b>Demo</b> · {texto}", ahora)
        log.warning(texto)

    def _salud(self, s: Senyales, inf: Informe) -> None:
        self.salud, que, motivo = evaluar(self.salud, s)
        if que == ENTRAR:
            self._cambio(self.modos.activate(Mode.CLOSE_ONLY_DEGRADED, motivo), s.ahora_ms, inf)
        elif que == SALIR:
            self._cambio(self.modos.deactivate(Mode.CLOSE_ONLY_DEGRADED, motivo), s.ahora_ms, inf)

    def _regla_7(self, e: EquityBreakdown, ahora: int, inf: Informe) -> None:
        suelo = self.settings.capital.floor_usd
        minuto = ahora // 60_000
        if minuto != self._ultimo_minuto_equity or (e.is_reliable and e.equity_usd <= suelo):
            self._ultimo_minuto_equity = minuto
            db.guardar_equity(self.conn, ahora, e.equity_usd, e.is_reliable, e.free_quote_usd, e.positions_value_usd)
        dispara, self.vigia = self.vigia.con(e, suelo)
        if dispara:
            self._cambio(self.modos.activate(
                Mode.CLOSE_ONLY_CAPITAL, f"equity {e.equity_usd:.2f} $ <= suelo {suelo:.2f} $ en dos lecturas"),
                ahora, inf)

    def _regla_10(self, e: EquityBreakdown, ahora: int, inf: Informe) -> None:
        dia = _ms_a_dia(ahora)
        inicio = int(datetime.strptime(dia, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
        perdida = -sum(c.pnl_usd for c in db.cierres(self.conn, inicio))
        limite = Limits.for_state(self.settings, e.equity_usd, riesgo.SLIDER).daily_loss_limit_usd
        activo = self.modos.reason_for(Mode.CLOSE_ONLY_DAILY)
        if perdida >= limite and activo is None:
            self._cambio(self.modos.activate(Mode.CLOSE_ONLY_DAILY,
                                             f"{dia}: perdida del dia {perdida:.2f} $ >= {limite:.2f} $"), ahora, inf)
        elif activo is not None and not activo.startswith(dia):
            self._cambio(self.modos.deactivate(Mode.CLOSE_ONLY_DAILY, "nuevo dia UTC"), ahora, inf)

    def _manuales(self, ahora: int, inf: Informe) -> None:
        estado = self.manuales(ahora)
        if estado is None:
            return
        for modo in (Mode.CLOSE_ONLY_MANUAL, Mode.HALTED):
            if modo in estado:
                self._cambio(self.modos.activate(modo, estado[modo]), ahora, inf)
            elif modo in self.modos.active:
                self._cambio(self.modos.manual_reset(modo, "levantada desde Telegram o el panel"), ahora, inf)

    # --- enviar y apuntar ---------------------------------------------------------------------------------------

    def _aviso(self, tipo: str, clave: str, texto: str, ahora: int) -> None:
        from portfolio import store as papel_store
        papel_store.encolar_avisos(self.conn, ahora, [(tipo, clave, texto)])

    def _resultado(self, r: ordenes.Respuesta, que: str, peticion: Any, ahora: int, inf: Informe) -> None:
        db.apuntar(self.conn, ahora, r.decision_id, que, r.resultado.value, r.detalle, peticion)
        inf.hechos.append(f"{que} {r.decision_id}: {r.resultado.value}")
        if r.resultado is Resultado.SIN_RESPUESTA:
            self._salud(Senyales(ahora, error_exchange=True), inf)
        elif r.resultado is Resultado.RECHAZADA:
            self._aviso("exec", f"rechazo:{que}:{r.decision_id}:{ahora // PASADA_MS}",
                        f"<b>Demo</b> · OKX rechazo {que} de <code>{r.decision_id}</code>: {r.detalle[:300]}", ahora)

    def _cancelar_entrada(self, did: str, simbolo: str, motivo: str, ahora: int, inf: Informe) -> None:
        if did in self._canceladas:
            return             # ya cancelada: la conciliacion la quita de lo local en su pasada
        p = peticiones.cancelar_entrada(decision_id=did, simbolo=simbolo, whitelist=self.whitelist)
        r = ordenes.cancelar_entrada(self.ex, p, decision_id=did, whitelist=self.whitelist)
        self._resultado(r, "cancelar_entrada", {**p, "motivo": motivo}, ahora, inf)
        if r.resultado in (Resultado.CANCELADA, Resultado.YA_NO_ESTABA):
            self._canceladas.add(did)

    # --- conciliacion ------------------------------------------------------------------------------------------

    def _local(self) -> Local:
        entradas = db.entradas(self.conn)
        con_entrada = {e.decision_id for e in entradas}
        posiciones = [p for p in db.posiciones(self.conn) if p.decision_id not in con_entrada]
        abiertas = db.posiciones(self.conn)
        usdc = (db.foto(self.conn)[1] + sum(c.pnl_usd for c in db.cierres(self.conn))
                - sum(p.cantidad * p.entrada + db.posicion_completa(self.conn, p.decision_id)["comision_entrada_usd"]
                      for p in abiertas))
        return Local(entradas=tuple(EntradaLocal(e.decision_id, e.simbolo, e.cantidad) for e in entradas),
                     posiciones=tuple(PosicionLocal(p.decision_id, p.simbolo, p.cantidad) for p in posiciones),
                     usdc=usdc)

    def _conciliar(self, saldo: Any, okx: lectura.Ordenes, bids: dict[str, float], ahora: int, inf: Informe) -> None:
        # La orden que lanza una OCO al saltar lleva un clOrdId de OKX ("O..."), no el nuestro, y nuestro algoClOrdId
        # (prueba 10, 03/10): es parte de su OCO, no una orden ajena.
        ex = Exchange(saldos=saldo.monedas, usdc=saldo.usdc_total,
                      ordenes=tuple(ordenes.orden_ex(o) for o in okx.ordenes if not o.get("algoClOrdId")),
                      ocos=tuple(ordenes.oco_ex(a) for a in okx.ocos))
        lotes = {s: i.lot_size for s, i in self.instrumentos.items() if s in self.whitelist}
        r = conciliar(self._local(), ex, lotes=lotes, sin_oco_antes=self._sin_oco)
        for paso in r.acciones:
            self._paso_local(paso, okx, bids, ahora, inf)
        precios = self._precios()
        plan = planear(r, precios=precios, ex=self.ex, whitelist=self.whitelist)
        for envio in plan.envios:
            if envio.que == CANCELAR_RESTO:
                rr = ordenes.cancelar_entrada(self.ex, envio.peticion, decision_id=envio.decision_id,
                                              whitelist=self.whitelist)
            elif envio.que == CANCELAR_OCO:
                rr = ordenes.cancelar_oco(self.ex, envio.peticion, decision_id=envio.decision_id,
                                          whitelist=self.whitelist)
            elif envio.que == CREAR_OCO:
                rr = ordenes.crear_oco(self.ex, envio.peticion, decision_id=envio.decision_id,
                                       whitelist=self.whitelist)
            else:
                raise ValueError(f"envio sin tratar: {envio.que}")
            self._resultado(rr, envio.que, envio.peticion, ahora, inf)
            if envio.que == CREAR_OCO and rr.resultado is Resultado.RECHAZADA:
                self._precio_pasado(envio.decision_id, envio.simbolo, ahora, inf)
        for did, motivo in plan.sin_proteger.items():
            self._aviso("exec", f"sin_proteger:{did}:{ahora // PASADA_MS}",
                        f"<b>Demo</b> · posicion SIN stop ni objetivo: <code>{did}</code> ({motivo})", ahora)
        for f in r.descuadres:
            self._aviso("exec", f"descuadre:{f.tipo}:{f.detalle[:80]}:{ahora // (60 * 60_000)}",
                        f"<b>Demo</b> · descuadre ({f.tipo}): {f.detalle}", ahora)
        db.guardar_pasada(self.conn, ahora, r.cuadra,
                          [{"accion": p.accion.value, "decision_id": p.decision_id, "cantidad": p.cantidad,
                            "detalle": p.detalle} for p in r.acciones],
                          [{"tipo": f.tipo.value, "detalle": f.detalle} for f in r.descuadres], list(r.sin_oco))
        self._sin_oco = r.sin_oco
        self._ultima_pasada_ms = ahora
        inf.pasada = True

    def _precio_pasado(self, did: str, simbolo: str, ahora: int, inf: Informe) -> None:
        """OKX rechazo la OCO. Si el ULTIMO precio ya toco el objetivo o el stop, se vende a mercado: es lo que habria
        hecho la OCO (decision del propietario del 03/10, opcion A; OKX: `51279` "TP trigger price cannot be lower than the last
        price"). Se mira el precio y no el codigo de error: el del stop no se ha visto. Si no, solo se avisa."""
        p = db.posicion_completa(self.conn, did)
        if p is None or p["vendiendo_ms"] is not None:
            return
        try:
            ultimo = float(self.ex.fetch_ticker(simbolo)["last"])
        except Exception as exc:  # noqa: BLE001 - sin precio no se vende: la pasada siguiente lo vuelve a intentar
            db.apuntar(self.conn, ahora, did, "precio_pasado", "sin_precio", f"{type(exc).__name__}")
            return
        if ultimo >= p["objetivo"]:
            pata = "objetivo"
        elif ultimo <= p["stop"]:
            pata = "stop"
        else:
            return
        motivo = f"OCO rechazada con el precio ya pasado el {pata} (ultimo {ultimo:g}, {pata} {p[pata]:g})"
        self._aviso("exec", f"precio_pasado:{did}", f"<b>Demo</b> · <code>{did}</code>: {motivo}; se vende a mercado",
                    ahora)
        self._vender(did, motivo, ahora, inf)

    def _precios(self) -> dict[str, tuple[float, float]]:
        """Stop y objetivo para (re)crear una OCO, AL TICK del exchange y hacia su lado seguro (los dos hacia arriba,
        como `execution.precios.al_tick`): sin esto ccxt redondea al MAS CERCANO y podria bajar el stop un tick
        (visto el 03/10 en el test de caos 5: el objetivo 134,01 de SOL volvio como 134, no 134,1)."""
        out = {}
        for fila in self.conn.execute("SELECT decision_id, simbolo, stop, objetivo FROM exec_posiciones UNION ALL "
                                      "SELECT decision_id, simbolo, stop, objetivo FROM exec_entradas"):
            ins = self.instrumentos.get(fila["simbolo"])
            paso = ins.tick_size if ins is not None else 0.0
            out[fila["decision_id"]] = (techo_al_paso(fila["stop"], paso), techo_al_paso(fila["objetivo"], paso))
        return out

    def _paso_local(self, paso: Any, okx: lectura.Ordenes, bids: dict[str, float], ahora: int, inf: Informe) -> None:
        from execution.conciliacion import Accion
        did = paso.decision_id
        inf.hechos.append(f"conciliacion: {paso.accion.value} {did} {paso.detalle}")
        if paso.accion is Accion.APUNTAR_LLENADO or paso.accion is Accion.ADOPTAR_POSICION:
            o = okx.orden(ids.cl_ord_id(did)) or {}
            e = db.entrada_completa(self.conn, did)
            papel = self._orden_papel(did)
            stop = e["stop"] if e is not None else (papel.stop if papel else 0.0)
            objetivo = e["objetivo"] if e is not None else (papel.objetivo if papel else 0.0)
            precio = _num(o.get("avgPx")) or (e["limite"] if e is not None else (papel.entrada if papel else 0.0))
            db.guardar_posicion(self.conn, did, paso.simbolo, paso.cantidad, precio, stop, objetivo,
                                int(o.get("fillTime") or o.get("uTime") or ahora), -_num(o.get("fee")))
            if o.get("state") in ("filled", "canceled", "mmp_canceled"):
                db.borrar_entrada(self.conn, did)
            if paso.accion is Accion.ADOPTAR_POSICION:
                motivo = ("adoptada: OCO nuestra viva sin posicion local" if stop > 0 and objetivo > precio > stop
                          else "adoptada SIN stop y objetivo conocidos")
                db.tratar(self.conn, did, ahora, "adoptada", motivo, papel.cantidad if papel else None, paso.cantidad)
                self._aviso("exec", f"adoptada:{did}", f"<b>Demo</b> · posicion <code>{did}</code> {motivo}"
                            f" ({paso.cantidad:g} {paso.simbolo} a {precio:g})", ahora)
        elif paso.accion is Accion.ADOPTAR_ENTRADA:
            papel = self._orden_papel(did)
            o = okx.orden(ids.cl_ord_id(did)) or {}
            if papel is None:
                self._aviso("exec", f"adoptada:{did}", f"<b>Demo</b> · orden <code>{did}</code> en OKX sin orden"
                            " de papel: no se sabe su stop ni su objetivo", ahora)
                return
            db.guardar_entrada(self.conn, did, paso.simbolo, paso.cantidad, _num(o.get("px")) or papel.entrada,
                               papel.stop, papel.objetivo, papel.creada_ms, ahora)
        elif paso.accion is Accion.OLVIDAR_ENTRADA:
            db.borrar_entrada(self.conn, did)
        elif paso.accion is Accion.CERRAR_LOCAL:
            self._cerrar(did, okx, bids, ahora, inf)

    def _cerrar(self, did: str, okx: lectura.Ordenes, bids: dict[str, float], ahora: int, inf: Informe) -> None:
        p = db.posicion_completa(self.conn, did)
        if p is None:
            return
        taker = self.settings.exchange.fees.taker_pct / 100
        venta = okx.orden(ids.cl_ord_id_salida(did))
        oco = okx.oco(ids.algo_cl_ord_id(did))
        estimada = False
        if venta is not None and _num(venta.get("accFillSz")) > 0:
            precio, comision, motivo = _num(venta.get("avgPx")), -_num(venta.get("fee")), "salida"
            cuando = int(venta.get("fillTime") or venta.get("uTime") or ahora)
        elif oco is not None and oco.get("state") == "effective":
            # Prueba 10 (03/10): la OCO que salta trae `actualSide` y el `ordId` / `ordIdList` de la orden de mercado que
            # lanza (de ella salen el precio medio y la comision de verdad); `actualPx` llega VACIO. Sin ella, se estima.
            motivo = str(oco.get("actualSide") or "desconocido")
            lanzada = self._orden_lanzada(oco, p["simbolo"])
            if lanzada is not None and _num(lanzada.get("avgPx")) > 0:
                precio, comision = _num(lanzada.get("avgPx")), -_num(lanzada.get("fee"))
                cuando = int(lanzada.get("fillTime") or lanzada.get("uTime") or oco.get("uTime") or ahora)
            else:
                precio = _num(oco.get("actualPx")) or (p["stop"] if motivo == "sl" else p["objetivo"])
                comision, estimada = precio * p["cantidad"] * taker, True
                cuando = int(oco.get("uTime") or ahora)
        else:
            precio, motivo, estimada = bids.get(p["simbolo"], p["entrada"]), "desconocido", True
            comision, cuando = precio * p["cantidad"] * taker, ahora
        c = db.cerrar(self.conn, did, salida=precio, cerrada_ms=cuando, motivo=motivo, comision_salida_usd=comision,
                      estimada=estimada)
        if c is not None:
            riesgo_usd = (p["entrada"] - p["stop"]) * p["cantidad"]
            texto = mensajes.cierre_demo(simbolo=p["simbolo"], decision_id=did, pnl_usd=c.pnl_usd,
                                         r=c.pnl_usd / riesgo_usd if riesgo_usd > 0 else None, motivo=motivo,
                                         entrada=p["entrada"], salida=precio, duracion_ms=cuando - p["abierta_ms"],
                                         estimada=estimada)
            self._aviso("operacion", f"cierre:{did}", texto, ahora)
            inf.hechos.append(f"cerrada {did} ({motivo}) a {precio:g}: {c.pnl_usd:+.2f} $"
                              + (" (precio ESTIMADO)" if estimada else ""))

    def _orden_lanzada(self, oco: dict[str, Any], simbolo: str) -> dict[str, Any] | None:
        ord_id = oco.get("ordId") or next(iter(oco.get("ordIdList") or []), "")
        if not ord_id:
            return None
        try:
            datos = self.ex.private_get_trade_order({"instId": simbolo.replace("/", "-"), "ordId": ord_id})
            return next(iter(datos.get("data") or []), None)
        except Exception:  # noqa: BLE001 - sin ella se estima (y la conciliacion del USDC lo dira)
            return None

    def _resto_de_parciales(self, okx: lectura.Ordenes, ahora: int, inf: Informe) -> None:
        """Entre pasadas: una entrada nuestra a medias se cancela YA (lo llenado no tiene stop hasta entonces)."""
        for o in okx.ordenes:
            cid = str(o.get("clOrdId") or "")
            if o.get("state") != "partially_filled" or ids.es_salida(cid) or o.get("algoClOrdId"):
                continue
            try:
                did = ids.decision_id_de(cid)
            except ids.IdInvalido:
                continue
            simbolo = str(o["instId"]).replace("-", "/")
            self._cancelar_entrada(did, simbolo, "llenada a medias: OKX crea la OCO por lo llenado", ahora, inf)

    # --- el espejo ---------------------------------------------------------------------------------------------

    def _papel(self) -> tuple[list[espejo.OrdenPapel], list[espejo.CierrePapel]] | None:
        try:
            conn = sqlite3.connect(f"file:{self.papel_db}?mode=ro", uri=True, timeout=10)
        except sqlite3.Error:
            return None
        conn.row_factory = sqlite3.Row
        try:
            desde = (db.foto(self.conn) or (0,))[0] - 2 * self.tf_ms
            ords = [espejo.OrdenPapel(r["decision_id"], r["symbol"], r["qty"], r["limit_price"], r["stop_price"],
                                      r["target_price"], r["created_ts_ms"], r["state"], r["setup"])
                    for r in conn.execute("SELECT * FROM paper_orders WHERE created_ts_ms >= ?", (desde,))]
            cierres = [espejo.CierrePapel(r["decision_id"], r["reason"])
                       for r in conn.execute("SELECT decision_id, reason FROM paper_trades WHERE closed_ts_ms >= ?",
                                             (desde,))]
            return ords, cierres
        finally:
            conn.close()

    def _orden_papel(self, did: str) -> espejo.OrdenPapel | None:
        """La orden de papel de esa decision, sea de cuando sea (una posicion adoptada puede ser de antes de la foto:
        decision del propietario del 03/10)."""
        try:
            conn = sqlite3.connect(f"file:{self.papel_db}?mode=ro", uri=True, timeout=10)
        except sqlite3.Error:
            return None
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute("SELECT * FROM paper_orders WHERE decision_id = ?", (did,)).fetchone()
        finally:
            conn.close()
        return None if r is None else espejo.OrdenPapel(
            r["decision_id"], r["symbol"], r["qty"], r["limit_price"], r["stop_price"], r["target_price"],
            r["created_ts_ms"], r["state"], r["setup"])

    def _mercado(self, creada_ms: int, bids: dict[str, float], ahora: int) -> tuple[riesgo.Mercado, dict]:
        """El mercado con el que DECIDIO la cartera de la IA (su vela) y las flags de ahora."""
        conn = sqlite3.connect(f"file:{self.papel_db}?mode=ro", uri=True, timeout=10)
        try:
            corr = {(a, b): c for a, b, c in conn.execute(
                "SELECT a, b, corr FROM paper_correlations WHERE ts_ms = ?", (creada_ms,))}
            fila = conn.execute("SELECT deviation_pct FROM paper_usdc WHERE ts_ms = ?", (creada_ms,)).fetchone()
            spreads = dict(conn.execute("SELECT symbol, spread_pct FROM paper_market WHERE ts_ms = ?", (creada_ms,)))
        finally:
            conn.close()
        return riesgo.Mercado(bids=bids, correlaciones=corr, usdc_desviacion_pct=fila[0] if fila else None,
                              flags=self.flags(ahora)), spreads

    def _espejo(self, foto_ms: int, equity: EquityBreakdown, bids: dict[str, float], ahora: int,
                inf: Informe) -> None:
        papel = self._papel()
        if papel is None:
            return
        ordenes_papel, cierres_papel = papel
        demo = espejo.Demo(entradas_vivas=frozenset(e.decision_id for e in db.entradas(self.conn)),
                           posiciones=frozenset(p.decision_id for p in db.posiciones(self.conn)),
                           tratadas=db.tratadas(self.conn), vendiendo=db.vendiendo(self.conn))
        acciones = espejo.decidir(ordenes_papel, cierres_papel, demo, operables=self.operables,
                                  arranque_ms=foto_ms, ahora_ms=ahora, tf_ms=self.tf_ms)
        for a in acciones:
            if a.que is espejo.Que.VENDER:
                if self.modos.effective is Mode.HALTED:
                    continue           # HALTED no cierra posiciones (decision 4): las OCO siguen
                self._vender(a.decision_id, a.motivo, ahora, inf)
            elif a.que is espejo.Que.CANCELAR:
                e = next(x for x in db.entradas(self.conn) if x.decision_id == a.decision_id)
                self._cancelar_entrada(a.decision_id, e.simbolo, a.motivo, ahora, inf)
            elif a.que is espejo.Que.OMITIR:
                db.tratar(self.conn, a.decision_id, ahora, "omitida", a.motivo,
                          a.orden.cantidad if a.orden else None)
                db.apuntar(self.conn, ahora, a.decision_id, "espejo", "omitida", a.motivo)
                inf.hechos.append(f"omitida {a.decision_id}: {a.motivo}")
            elif a.que is espejo.Que.COPIAR:
                self._copiar(a.orden, equity, bids, ahora, inf)

    def _vender(self, did: str, motivo: str, ahora: int, inf: Informe) -> None:
        p = db.posicion_completa(self.conn, did)
        if p is None:
            return
        cancelar = peticiones.cancelar_oco(decision_id=did, simbolo=p["simbolo"], whitelist=self.whitelist)
        rc = ordenes.cancelar_oco(self.ex, cancelar, decision_id=did, whitelist=self.whitelist)
        self._resultado(rc, "cancelar_oco", {**cancelar, "motivo": motivo}, ahora, inf)
        if rc.resultado not in (Resultado.CANCELADA, Resultado.YA_NO_ESTABA):
            return             # sin cancelar la OCO no se vende: podria vender dos veces; la vuelta siguiente reintenta
        if rc.resultado is Resultado.YA_NO_ESTABA:
            # "Ya no estaba" puede ser que la OCO YA SALTO (y vendio) sin que la conciliacion lo haya visto aun. Vender
            # entonces seria vender DOS veces, y con otros fondos en la cuenta (el ETH de la foto del demo) OKX no lo
            # impediria. Revision del 03/10.
            try:
                oco = ordenes.consultar_oco(self.ex, decision_id=did)
            except Exception as exc:  # noqa: BLE001 - sin saberlo no se vende: la vuelta siguiente reintenta
                db.apuntar(self.conn, ahora, did, "salida", "no_vendida", f"sin saber si la OCO salto: {exc}")
                return
            if oco is not None and oco.get("state") == "effective":
                db.apuntar(self.conn, ahora, did, "salida", "no_vendida", "la OCO ya salto: la cierra la conciliacion")
                return
        venta = peticiones.salida(self.ex, decision_id=did, simbolo=p["simbolo"], cantidad=p["cantidad"],
                                  whitelist=self.whitelist)
        rv = ordenes.enviar_salida(self.ex, venta, decision_id=did, simbolo=p["simbolo"], whitelist=self.whitelist)
        self._resultado(rv, "salida", {**venta, "motivo": motivo}, ahora, inf)
        if rv.resultado in (Resultado.ENVIADA, Resultado.LLENADA, Resultado.YA_ESTABA):
            db.marcar_vendiendo(self.conn, did, ahora)

    def _copiar(self, orden: espejo.OrdenPapel, equity: EquityBreakdown, bids: dict[str, float], ahora: int,
                inf: Informe) -> None:
        did = orden.decision_id
        if not self.modos.can_open:
            if did not in self._esperando:
                self._esperando.add(did)
                db.apuntar(self.conn, ahora, did, "espejo", "esperando", f"modo {self.modos.effective}")
            return             # se vuelve a mirar en la vuelta siguiente; si caduca, el espejo la omite
        ins = self.instrumentos[orden.simbolo]
        try:
            precios = al_tick(ins, entrada=orden.entrada, stop=orden.stop, objetivo=orden.objetivo,
                              cantidad=orden.cantidad, riesgo_aprobado_usd=float("inf"))
        except Exception as exc:  # noqa: BLE001
            self._omitir(did, f"precios al tick del demo: {exc}", orden, ahora, inf)
            return
        ajustada = espejo.OrdenPapel(did, orden.simbolo, orden.cantidad, precios.entrada, precios.stop,
                                     precios.objetivo, orden.creada_ms, orden.estado, orden.setup)
        mercado, spreads = self._mercado(orden.creada_ms, bids, ahora)
        foto = riesgo.estado(ahora_ms=ahora, equity=equity, modo=self.modos.effective,
                             posiciones=db.posiciones(self.conn), entradas=db.entradas(self.conn),
                             cierres=db.cierres(self.conn), mercado=mercado)
        if orden.simbolo not in spreads:
            self._omitir(did, "sin el spread de la vela en la cartera de papel", orden, ahora, inf)
            return
        ap = riesgo.aprobar(ajustada, foto, equity, instrumento=ins, spread_pct=spreads[orden.simbolo],
                            settings=self.settings)
        if not ap.enviar:
            self._omitir(did, ap.motivo, orden, ahora, inf)
            return
        try:      # comprobar (no suponer) con la cantidad final: minimos del demo y riesgo <= el aprobado
            final = al_tick(ins, entrada=precios.entrada, stop=precios.stop, objetivo=precios.objetivo,
                            cantidad=ap.cantidad, riesgo_aprobado_usd=ap.veredicto.risk_usd)
        except Exception as exc:  # noqa: BLE001
            self._omitir(did, f"al tick con la cantidad aprobada: {exc}", orden, ahora, inf)
            return
        peticion = peticiones.entrada(self.ex, decision_id=did, simbolo=orden.simbolo, precios=final,
                                      whitelist=self.whitelist)
        r = ordenes.enviar_entrada(self.ex, peticion, decision_id=did, simbolo=orden.simbolo,
                                   whitelist=self.whitelist)
        self._resultado(r, "entrada", peticion, ahora, inf)
        if r.resultado in (Resultado.ENVIADA, Resultado.YA_ESTABA, Resultado.LLENADA):
            # LLENADA: OKX ya la tenia (se envio y no se llego a apuntar); la conciliacion apunta el llenado.
            db.guardar_entrada(self.conn, did, orden.simbolo, final.cantidad, final.entrada, final.stop,
                               final.objetivo, orden.creada_ms, ahora)
            db.tratar(self.conn, did, ahora, "copiada", ap.motivo, orden.cantidad, final.cantidad)
        elif r.resultado in (Resultado.RECHAZADA, Resultado.NO_REENVIAR):
            db.tratar(self.conn, did, ahora, "omitida", f"OKX: {r.resultado.value} {r.detalle[:200]}",
                      orden.cantidad, ap.cantidad)
        # SIN_RESPUESTA: no se trata; la vuelta siguiente consulta antes de nada (ordenes.enviar_entrada)

    def _omitir(self, did: str, motivo: str, orden: espejo.OrdenPapel, ahora: int, inf: Informe) -> None:
        db.tratar(self.conn, did, ahora, "omitida", motivo, orden.cantidad)
        db.apuntar(self.conn, ahora, did, "veto", "omitida", motivo)
        inf.hechos.append(f"no se copia {did}: {motivo}")
