"""Las 9 pruebas del demo de OKX (fase 4, paso 3 del guion; `docs/preparacion-fase-4.md` seccion 8).

Lo que no se puede saber sin ejecutarlo, ejecutado en la cuenta DEMO con importes pequenyos (~10 $), y lo que conteste
OKX guardado TAL CUAL en un JSON. Deciden como se escribe la proteccion (pieza b) y si el modelo de costes vale:

1. OCO de spot con `tdMode = cash`: la acepta OKX en esta cuenta?
2. La misma sin `tdMode`: que manda ccxt. NO SE ENVIA: seria una orden de MARGEN (regla 1); se construye en local,
   la guardia la rechaza y se apunta el modo de la cuenta (`acctLv`), que es lo que decide que haria OKX.
3. Entrada con TP/SL adjuntos, llenada entera: se crea la orden algoritmica? con que id y que tipo?
4. Lo mismo llenada A MEDIAS y cancelada: hay stop para la parte llenada? (el caso peligroso de la regla 13)
5. `clOrdId` reutilizado despues de llenarse: crea una orden nueva?
6. Con `feeType = 1`: se recibe la cantidad EXACTA y la comision va en USDC?
7. OCO con `tpOrdKind = limit`: el objetivo puede quedar como limit (maker)?
8. Cancelar la OCO y volver a crearla con el mismo id (lo que hara la conciliacion).
9. `tradeQuoteCcy` en el libro unificado (01/10): con y sin el, en la entrada y en la OCO; que se paga en USDC.

SEGURIDAD: solo con la clave del DEMO (si no, no hace nada); cada orden pasa por `revisar_prueba` (moneda del demo,
`tdMode = cash`, nocional <= MAX_NOCIONAL, ids propios con el sello de esta pasada) y la OCO normal ademas por la
guardia de la fase 4 (`execution.peticiones`). Al acabar, SIEMPRE: cancela lo que quede vivo con nuestros ids y
vende a mercado lo comprado en las pruebas. No imprime nada de la credencial.

    .venv/bin/python scripts/pruebas_demo.py --salida /tmp/pruebas-demo.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEMO = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC", "NEAR/USDC")
SIMBOLO = "NEAR/USDC"
NOCIONAL = 10.0          # $ por orden de prueba
MAX_NOCIONAL = 250.0     # tope duro de cualquier orden de esta pasada
ESPERA_S = 2.5


def _inst(simbolo: str) -> str:
    return simbolo.replace("/", "-")


class Pruebas:
    def __init__(self, ex: Any, sello: str) -> None:
        self.ex, self.sello = ex, sello
        self.resultados: dict[str, Any] = {}
        self.saldo_inicial: dict[str, float] = {}   # para vender al final lo que las pruebas hayan comprado

    # --- utilidades ---

    def did(self, setup: str, base: str | None = None) -> str:
        return f"d-{self.sello}-{base or SIMBOLO.split('/')[0].lower()}-{setup}"

    def libro(self, simbolo: str) -> tuple[float, float, float, float]:
        ob = self.ex.fetch_order_book(simbolo, 5)
        return ob["bids"][0][0], ob["bids"][0][1], ob["asks"][0][0], ob["asks"][0][1]

    def px(self, simbolo: str, valor: float) -> str:
        return self.ex.price_to_precision(simbolo, valor)

    def sz(self, simbolo: str, valor: float) -> str:
        """Al lote; por debajo del paso minimo, "0" (ccxt lanzaria: paso el 02/10 en la limpieza)."""
        try:
            return self.ex.amount_to_precision(simbolo, valor)
        except Exception:  # noqa: BLE001
            return "0"

    def revisar_prueba(self, peticion: dict[str, Any], *, compra: bool) -> None:
        """La guardia de las PRUEBAS: lo minimo que ninguna orden de esta pasada puede saltarse."""
        motivos = []
        simbolo = str(peticion.get("instId", "")).replace("-", "/")
        if simbolo not in DEMO:
            motivos.append(f"{simbolo} no es una moneda del demo")
        if peticion.get("tdMode") != "cash":
            motivos.append(f"tdMode {peticion.get('tdMode')!r}: solo cash (regla 1)")
        ids_propios = [peticion.get(k) for k in ("clOrdId", "algoClOrdId") if peticion.get(k)]
        ids_propios += [a.get("attachAlgoClOrdId") for a in peticion.get("attachAlgoOrds", [])]
        # Los ids de execution.ids empiezan por "d" + el sello de esta pasada (dAAAAMMDDTHHMM...).
        if not all(str(i).startswith("d" + self.sello) for i in ids_propios) or not ids_propios:
            motivos.append(f"ids que no son de esta pasada: {ids_propios}")
        if compra and peticion.get("side") == "buy":
            precio = float(peticion.get("px") or 0)
            nocional = precio * float(peticion.get("sz") or 0)
            if peticion.get("ordType") == "market" or nocional > MAX_NOCIONAL or nocional <= 0:
                motivos.append(f"compra de {nocional:.2f} $ (tope {MAX_NOCIONAL} $, nunca a mercado)")
        if motivos:
            raise RuntimeError("revisar_prueba: " + "; ".join(motivos))

    def llamar(self, metodo: str, peticion: Any) -> dict[str, Any]:
        """Envia y devuelve {'ok', 'resp' | 'error'} sin lanzar. El error de ccxt lleva el cuerpo de OKX, no claves."""
        try:
            return {"ok": True, "resp": getattr(self.ex, metodo)(peticion)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:600]}"}

    def orden(self, simbolo: str, cl_ord_id: str) -> dict[str, Any] | None:
        r = self.llamar("private_get_trade_order", {"instId": _inst(simbolo), "clOrdId": cl_ord_id})
        if not r["ok"]:
            return {"error": r["error"]}
        datos = r["resp"].get("data") or []
        return datos[0] if datos else None

    def algos_pendientes(self, simbolo: str) -> list[dict[str, Any]]:
        out = []
        for tipo in ("oco", "conditional"):
            r = self.llamar("private_get_trade_orders_algo_pending", {"ordType": tipo, "instId": _inst(simbolo)})
            if r["ok"]:
                out += r["resp"].get("data") or []
        return out

    def algo(self, simbolo: str, algo_cl_ord_id: str) -> dict[str, Any] | None:
        return next((a for a in self.algos_pendientes(simbolo) if a.get("algoClOrdId") == algo_cl_ord_id), None)

    def cancelar_algo(self, simbolo: str, algo_cl_ord_id: str) -> dict[str, Any]:
        """Por `algoClOrdId`; si OKX no lo admite, por `algoId`. Apunta cual funciono."""
        r = self.llamar("private_post_trade_cancel_algos", [{"instId": _inst(simbolo), "algoClOrdId": algo_cl_ord_id}])
        if r["ok"] and str((r["resp"].get("data") or [{}])[0].get("sCode", "0")) == "0":
            return {"por": "algoClOrdId", **r}
        a = self.algo(simbolo, algo_cl_ord_id)
        if a is None:
            return {"por": "algoClOrdId", "nota": "ya no estaba pendiente", **r}
        r2 = self.llamar("private_post_trade_cancel_algos", [{"instId": _inst(simbolo), "algoId": a["algoId"]}])
        return {"por": "algoId", "primero_por_algoClOrdId": r, **r2}

    @staticmethod
    def corto(orden: dict[str, Any] | None) -> dict[str, Any] | None:
        if not orden or "error" in orden:
            return orden
        claves = ("ordId", "clOrdId", "state", "ordType", "side", "sz", "px", "accFillSz", "fillSz", "avgPx",
                  "fee", "feeCcy", "rebate", "rebateCcy", "tdMode", "tradeQuoteCcy", "attachAlgoOrds",
                  "attachAlgoClOrdId", "cancelSource", "cTime", "uTime")
        return {k: orden.get(k) for k in claves if k in orden}

    @staticmethod
    def corto_algo(a: dict[str, Any] | None) -> dict[str, Any] | None:
        if not a:
            return a
        claves = ("algoId", "algoClOrdId", "attachAlgoClOrdId", "ordType", "state", "side", "sz", "tdMode",
                  "tpTriggerPx", "tpOrdPx", "tpOrdKind", "slTriggerPx", "slOrdPx", "tradeQuoteCcy", "linkedOrd",
                  "ordId", "ordIdList")
        return {k: a.get(k) for k in claves if k in a}

    def comprar(self, simbolo: str, setup: str, *, base: str, sz: float, px: float, extra: dict | None = None,
                post_only: bool = False) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        did = self.did(setup, base)
        from execution import ids
        peticion = {"instId": _inst(simbolo), "tdMode": "cash", "side": "buy",
                    "ordType": "post_only" if post_only else "limit", "px": self.px(simbolo, px),
                    "sz": self.sz(simbolo, sz), "clOrdId": ids.cl_ord_id(did), **(extra or {})}
        self.revisar_prueba(peticion, compra=True)
        r = self.llamar("private_post_trade_order", peticion)
        time.sleep(ESPERA_S)
        detalle = self.orden(simbolo, peticion["clOrdId"])
        return did, {"peticion": peticion, "respuesta": r}, detalle

    def comprado(self, simbolo: str) -> float:
        """Lo que las pruebas han anyadido de esa moneda: el saldo de ahora menos el del principio."""
        base = simbolo.split("/")[0]
        ahora = float(self.ex.fetch_balance()["total"].get(base) or 0)
        return max(0.0, ahora - float(self.saldo_inicial.get(base) or 0))

    # --- las pruebas ---

    def p5_p6_p9_entrada(self) -> None:
        from execution import ids
        bid, _bq, ask, _aq = self.libro(SIMBOLO)
        sz = NOCIONAL / ask
        antes = self.ex.fetch_balance()["total"]
        did, envio, detalle = self.comprar(SIMBOLO, "pa", base=SIMBOLO.split("/")[0].lower(), sz=sz, px=ask * 1.003)
        despues = self.ex.fetch_balance()["total"]
        self.resultados["6_feetype_cantidad_exacta"] = {
            "envio": envio, "orden": self.corto(detalle),
            "delta_NEAR": (despues.get("NEAR") or 0) - (antes.get("NEAR") or 0),
            "delta_USDC": (despues.get("USDC") or 0) - (antes.get("USDC") or 0),
            "nota": "con feeType = 1: accFillSz == sz, delta_NEAR == accFillSz y feeCcy == USDC",
        }
        # 5. El mismo clOrdId despues de llenarse.
        peticion = dict(envio["peticion"])
        self.revisar_prueba(peticion, compra=True)
        r = self.llamar("private_post_trade_order", peticion)
        time.sleep(ESPERA_S)
        detalle2 = self.orden(SIMBOLO, peticion["clOrdId"])
        self.resultados["5_clordid_reutilizado"] = {
            "primera": self.corto(detalle), "reenvio": r, "detalle_tras_reenvio": self.corto(detalle2),
            "nota": "si el reenvio da otro ordId, OKX crea una orden NUEVA: hay que consultar antes de reenviar",
        }
        # 9a. Con tradeQuoteCcy explicito.
        did9, envio9, det9 = self.comprar(SIMBOLO, "pb", base=SIMBOLO.split("/")[0].lower(), sz=sz, px=ask * 1.003,
                                          extra={"tradeQuoteCcy": "USDC"})
        self.resultados["9a_entrada_con_tradequoteccy"] = {"envio": envio9, "orden": self.corto(det9),
                                                          "sin_el": self.corto(detalle)}
        _ = (bid, ids, did, did9)

    def _oco(self, setup: str, *, cambiar: dict | None = None, quitar: tuple[str, ...] = ()) -> tuple[str, dict, dict]:
        from execution import peticiones
        from execution.precios import PreciosOrden  # noqa: F401 - solo para dejar claro de donde salen los precios
        bid, _bq, ask, _aq = self.libro(SIMBOLO)
        cantidad = float(self.sz(SIMBOLO, min(self.comprado(SIMBOLO), NOCIONAL / ask)))
        if cantidad < float(self.ex.markets[SIMBOLO]["limits"]["amount"]["min"] or 0):
            raise RuntimeError(f"sin {SIMBOLO} comprado en las pruebas: no hay nada que proteger con una OCO")
        did = self.did(setup)
        peticion = peticiones.proteccion(
            self.ex, decision_id=did, simbolo=SIMBOLO, cantidad=cantidad,
            stop=float(self.px(SIMBOLO, bid * 0.85)), objetivo=float(self.px(SIMBOLO, ask * 1.25)), whitelist=DEMO)
        guardia_ok = dict(peticion)
        for k in quitar:
            peticion.pop(k, None)
        peticion.update(cambiar or {})
        self.revisar_prueba(peticion, compra=False)
        r = self.llamar("private_post_trade_order_algo", peticion)
        time.sleep(ESPERA_S)
        return did, {"peticion": peticion, "como_la_dio_la_guardia": guardia_ok if (cambiar or quitar) else None,
                     "respuesta": r}, {"pendiente": self.corto_algo(self.algo(SIMBOLO, peticion["algoClOrdId"]))}

    def p1_p8_oco(self) -> None:
        did, envio, estado = self._oco("pc")
        aid = envio["peticion"]["algoClOrdId"]
        self.resultados["1_oco_cash"] = {"envio": envio, **estado}
        cancel = self.cancelar_algo(SIMBOLO, aid)
        time.sleep(ESPERA_S)
        tras_cancelar = self.corto_algo(self.algo(SIMBOLO, aid))
        r = self.llamar("private_post_trade_order_algo", envio["peticion"])
        time.sleep(ESPERA_S)
        recreada = self.corto_algo(self.algo(SIMBOLO, aid))
        self.resultados["8_cancelar_y_recrear_oco"] = {
            "cancelar": cancel, "pendiente_tras_cancelar": tras_cancelar, "recrear_mismo_id": r,
            "pendiente_tras_recrear": recreada}
        self.cancelar_algo(SIMBOLO, aid)

    def p9_oco(self) -> None:
        did, envio, estado = self._oco("pd", cambiar={"tradeQuoteCcy": "USDC"})
        self.resultados["9b_oco_con_tradequoteccy"] = {"envio": envio, **estado}
        self.cancelar_algo(SIMBOLO, envio["peticion"]["algoClOrdId"])

    def p7_objetivo_limit(self) -> None:
        did, envio, estado = self._oco("pe", quitar=("tpTriggerPx",),
                                       cambiar={"tpOrdKind": "limit"})
        # El objetivo como limit: tpOrdPx = el precio del objetivo (no -1).
        res = {"variante_a_sin_tpTriggerPx": {"envio": envio, **estado}}
        self.cancelar_algo(SIMBOLO, envio["peticion"]["algoClOrdId"])
        # Las dos variantes siempre: la documentacion no deja claro si con tpOrdKind = limit va tpTriggerPx.
        obj = envio["como_la_dio_la_guardia"]["tpTriggerPx"]
        _did_b, envio_b, estado_b = self._oco("pf", cambiar={"tpOrdKind": "limit", "tpOrdPx": obj})
        res["variante_b_con_tpTriggerPx_y_tpOrdPx"] = {"envio": envio_b, **estado_b}
        self.cancelar_algo(SIMBOLO, envio_b["peticion"]["algoClOrdId"])
        self.resultados["7_objetivo_limit"] = res

    def p2_sin_tdmode(self) -> None:
        import ccxt

        from execution import guardia
        local = ccxt.okx({"options": {"defaultType": "spot"}})
        local.markets = self.ex.markets
        local.markets_by_id = self.ex.markets_by_id
        bid, _bq, ask, _aq = self.libro(SIMBOLO)
        peticion = local.create_order_request(SIMBOLO, "limit", "sell", float(self.sz(SIMBOLO, NOCIONAL / ask)), None,
                                              {"stopLossPrice": float(self.px(SIMBOLO, bid * 0.85)),
                                               "takeProfitPrice": float(self.px(SIMBOLO, ask * 1.25))})
        try:
            guardia.revisar(peticion, guardia.PROTECCION, decision_id=self.did("pg"), whitelist=DEMO)
            veredicto = "la guardia la dejaria pasar (MAL)"
        except guardia.PeticionRechazada as exc:
            veredicto = f"rechazada por la guardia: {exc.motivos}"
        cfg = self.llamar("private_get_account_config", {})
        datos = ((cfg.get("resp") or {}).get("data") or [{}])[0] if cfg["ok"] else {}
        self.resultados["2_oco_sin_tdmode"] = {
            "enviada": False, "por_que": "seria una orden de margen (regla 1): no se envia ni en el demo",
            "tdMode_que_pone_ccxt": peticion.get("tdMode"), "ordType": peticion.get("ordType"),
            "guardia": veredicto, "acctLv_cuenta": datos.get("acctLv"),
            "nota": "acctLv 1 = modo spot (sin margen): OKX la rechazaria; 2-4 = con margen: seria margen de verdad"}

    def p3_adjuntos_lleno(self) -> None:
        from execution import ids
        bid, _bq, ask, _aq = self.libro(SIMBOLO)
        did = self.did("ph")
        adj = {"attachAlgoClOrdId": ids.algo_cl_ord_id(did), "tpTriggerPx": self.px(SIMBOLO, ask * 1.25),
               "tpOrdPx": "-1", "slTriggerPx": self.px(SIMBOLO, bid * 0.85), "slOrdPx": "-1"}
        _, envio, detalle = self.comprar(SIMBOLO, "ph", base=SIMBOLO.split("/")[0].lower(), sz=NOCIONAL / ask, px=ask * 1.003,
                                         extra={"attachAlgoOrds": [adj]})
        time.sleep(ESPERA_S)
        creada = self.algo(SIMBOLO, adj["attachAlgoClOrdId"])
        otras = [self.corto_algo(a) for a in self.algos_pendientes(SIMBOLO)]
        self.resultados["3_adjuntos_llenada_entera"] = {"envio": envio, "orden": self.corto(detalle),
                                                        "algo_creada": self.corto_algo(creada),
                                                        "algos_pendientes_del_par": otras}
        if creada:
            self.cancelar_algo(SIMBOLO, adj["attachAlgoClOrdId"])

    def p4_adjuntos_parcial(self) -> None:
        from execution import ids
        elegido = None
        libros = {}
        for s in DEMO:
            bid, bq, ask, aq = self.libro(s)
            libros[s] = {"bid": bid, "bid_sz": bq, "ask": ask, "ask_sz": aq}
            sz = float(self.sz(s, aq * 1.5))
            minimo = float(self.ex.markets[s]["limits"]["amount"]["min"] or 0)
            if sz > aq and sz * ask <= MAX_NOCIONAL * 0.9 and sz >= minimo:
                elegido = elegido or (s, bid, ask, aq, sz)
        if elegido is None:
            self.resultados["4_adjuntos_parcial"] = {"hecha": False, "libros": libros,
                                                     "por_que": "ningun nivel del libro deja forzar un llenado a medias "
                                                                f"con menos de {MAX_NOCIONAL} $"}
            return
        s, bid, ask, aq, sz = elegido
        base = s.split("/")[0].lower()
        did = self.did("pi", base)
        adj = {"attachAlgoClOrdId": ids.algo_cl_ord_id(did), "tpTriggerPx": self.px(s, ask * 1.25), "tpOrdPx": "-1",
               "slTriggerPx": self.px(s, bid * 0.85), "slOrdPx": "-1"}
        _, envio, detalle = self.comprar(s, "pi", base=base, sz=sz, px=ask, extra={"attachAlgoOrds": [adj]})
        antes_cancelar = self.corto(detalle)
        cancel = self.llamar("private_post_trade_cancel_order", {"instId": _inst(s), "clOrdId": envio["peticion"]["clOrdId"]})
        time.sleep(ESPERA_S * 2)
        tras = self.orden(s, envio["peticion"]["clOrdId"])
        creada = self.algo(s, adj["attachAlgoClOrdId"])
        consulta = self.llamar("private_get_trade_order_algo", {"algoClOrdId": adj["attachAlgoClOrdId"]})
        self.resultados["4_adjuntos_parcial"] = {
            "hecha": True, "simbolo": s, "nivel_ask": {"precio": ask, "tamanyo": aq}, "envio": envio,
            "antes_de_cancelar": antes_cancelar, "cancelar": cancel, "tras_cancelar": self.corto(tras),
            "algo_pendiente_para_lo_llenado": self.corto_algo(creada), "consulta_por_algoClOrdId": consulta}
        if creada:
            self.cancelar_algo(s, adj["attachAlgoClOrdId"])

    # --- limpieza ---

    def limpiar(self) -> None:
        out = {"canceladas": [], "algos_canceladas": [], "ventas": []}
        for s in DEMO:
            r = self.llamar("private_get_trade_orders_pending", {"instId": _inst(s)})
            for o in ((r.get("resp") or {}).get("data") or []) if r["ok"] else []:
                if str(o.get("clOrdId", "")).startswith("d" + self.sello):
                    out["canceladas"].append(self.llamar("private_post_trade_cancel_order",
                                                         {"instId": _inst(s), "clOrdId": o["clOrdId"]}))
            for a in self.algos_pendientes(s):
                aid = str(a.get("algoClOrdId") or a.get("attachAlgoClOrdId") or "")
                if aid.startswith("d" + self.sello):
                    out["algos_canceladas"].append(self.llamar("private_post_trade_cancel_algos",
                                                               [{"instId": _inst(s), "algoId": a["algoId"]}]))
        time.sleep(ESPERA_S)
        for s in DEMO:
            base = s.split("/")[0]
            vender = float(self.sz(s, self.comprado(s)))
            if vender <= float(self.ex.markets[s]["limits"]["amount"]["min"] or 0):
                continue
            from execution import ids
            peticion = {"instId": _inst(s), "tdMode": "cash", "side": "sell", "ordType": "market",
                        "sz": self.sz(s, vender), "tgtCcy": "base_ccy",
                        "clOrdId": ids.cl_ord_id(self.did("pz", base.lower()))}
            self.revisar_prueba(peticion, compra=False)
            out["ventas"].append({"simbolo": s, "cantidad": vender, **self.llamar("private_post_trade_order", peticion)})
        self.resultados["limpieza"] = out


def main() -> int:
    import ccxt

    from core.config import load_settings
    from core.secrets import load_secrets
    from execution import guardia

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True, type=Path)
    ap.add_argument("--simbolo", default=SIMBOLO, choices=DEMO, help="la moneda de las pruebas (por defecto NEAR)")
    args = ap.parse_args()
    globals()["SIMBOLO"] = args.simbolo
    settings, secrets = load_settings(), load_secrets()
    if not secrets.has_okx or not secrets.okx_demo:
        print("Solo con la clave del DEMO. No se hace nada.")
        return 2
    ex = ccxt.okx({
        "hostname": settings.exchange.hostname,
        "apiKey": secrets.okx_api_key.get_secret_value(),
        "secret": secrets.okx_api_secret.get_secret_value(),
        "password": secrets.okx_password.get_secret_value(),
        "enableRateLimit": True,
        "options": {"defaultType": "spot", **guardia.OPCIONES_EXCHANGE},
        "headers": {"User-Agent": "ploutos/0.1"},
    })
    ex.set_sandbox_mode(True)
    ex.load_markets()
    sello = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    p = Pruebas(ex, sello)
    saldo_inicial = {k: v for k, v in ex.fetch_balance()["total"].items() if v}
    p.saldo_inicial = dict(saldo_inicial)
    p.resultados["inicio"] = {"sello": sello, "ccxt": ccxt.__version__, "saldo": saldo_inicial}
    pasos = [("5-6-9a", p.p5_p6_p9_entrada), ("1-8", p.p1_p8_oco), ("9b", p.p9_oco), ("7", p.p7_objetivo_limit),
             ("2", p.p2_sin_tdmode), ("3", p.p3_adjuntos_lleno), ("4", p.p4_adjuntos_parcial)]
    try:
        for nombre, paso in pasos:
            print(f"prueba {nombre}...", flush=True)
            try:
                paso()
            except Exception:  # noqa: BLE001 - una prueba que falla no para las demas; queda apuntado
                p.resultados[f"error_{nombre}"] = traceback.format_exc(limit=3)[-1500:]
    finally:
        print("limpieza...", flush=True)
        try:
            p.limpiar()
        except Exception:  # noqa: BLE001
            p.resultados["error_limpieza"] = traceback.format_exc(limit=3)[-1500:]
        time.sleep(ESPERA_S)
        final = {k: v for k, v in ex.fetch_balance()["total"].items() if v}
        p.resultados["fin"] = {"saldo": final, "delta": {k: round((final.get(k) or 0) - (saldo_inicial.get(k) or 0), 8)
                                                         for k in set(final) | set(saldo_inicial)}}
        args.salida.write_text(json.dumps(p.resultados, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"resultados en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
