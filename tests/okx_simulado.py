"""Un OKX de mentira para probar el ejecutor entero sin red: se comporta como el demo el 02/10.

Lo verificado en el demo (`docs/preparacion-fase-4.md` 11) que este simulador reproduce:
- la entrada con TP/SL adjuntos crea la OCO (con NUESTRO `algoClOrdId`) al llenarse ENTERA; llenada a medias, al
  CANCELAR el resto, por lo llenado;
- consultar lo que no existe -> `OrderNotFound` (51603); cancelar lo ya llenado -> `OrderNotFound` (51400);
- la comision en USDC (`feeType = 1`): se recibe la cantidad exacta;
- una OCO cancelada se sigue pudiendo consultar por su id; su id se puede reutilizar.

Y lo visto el 03/10 (prueba 10): una OCO que salta trae `actualSide`, `actualPx` VACIO y el `ordId` / `ordIdList` de la
orden de mercado que lanza; esa orden lleva un `clOrdId` de OKX ("O" + numero) y NUESTRO `algoClOrdId`.

Construye las peticiones con el ccxt DE VERDAD (hereda de `ccxt.okx` con los mercados cargados a mano).
"""

from __future__ import annotations

import itertools
from typing import Any

import ccxt

from execution import guardia

FEE = {"maker": 0.001, "taker": 0.002}


def _mercado(simbolo: str, tick: float, lote: float, minimo: float) -> dict[str, Any]:
    base, quote = simbolo.split("/")
    return {"id": f"{base}-{quote}", "symbol": simbolo, "base": base, "quote": quote, "baseId": base,
            "quoteId": quote, "type": "spot", "spot": True, "margin": False, "swap": False, "future": False,
            "option": False, "contract": False, "linear": None, "inverse": None, "settle": None, "active": True,
            "precision": {"amount": lote, "price": tick}, "limits": {"amount": {"min": minimo}, "cost": {"min": None}},
            "info": {}}


# Los instrumentos del DEMO medidos el 02/10 (preparacion-fase-4 12): ticks 10 veces mas gruesos que en el real.
MERCADOS_DEMO = {"BTC/USDC": (1.0, 1e-8, 1e-5), "ETH/USDC": (1.0, 1e-6, 0.001), "SOL/USDC": (0.1, 1e-5, 0.01),
                 "DOGE/USDC": (0.0001, 0.01, 10.0), "NEAR/USDC": (0.001, 0.001, 1.0),
                 "XRP/USDC": (0.0001, 0.01, 1.0), "AVAX/USDC": (0.01, 0.0001, 0.1), "TRX/USDC": (0.0001, 0.01, 1.0)}


class OkxSimulado(ccxt.okx):
    def __init__(self, saldos: dict[str, float], precios: dict[str, float], ahora: list[int]) -> None:
        super().__init__({"hostname": "eea.okx.com", "options": dict(guardia.OPCIONES_EXCHANGE)})
        self.set_markets([_mercado(s, *v) for s, v in MERCADOS_DEMO.items()])
        self.saldos = dict(saldos)
        self.precios = dict(precios)          # mid; bid = mid, ask = mid + un tick
        self.ahora = ahora                    # lista de un elemento: el reloj compartido con el test
        self.ordenes: list[dict[str, Any]] = []
        self.ocos: list[dict[str, Any]] = []
        self.ids = itertools.count(1000)
        self.llamadas: list[tuple[str, Any]] = []
        self.fallar: int = 0                  # cuantas llamadas siguientes dan error de red

    # --- utilidades del test ---------------------------------------------------------------------------------

    def _red(self, nombre: str, peticion: Any) -> None:
        self.llamadas.append((nombre, peticion))
        if self.fallar > 0:
            self.fallar -= 1
            raise ccxt.RequestTimeout(f"okx {nombre} request timeout")

    def _no_existe(self) -> ccxt.OrderNotFound:
        return ccxt.OrderNotFound('okx {"code":"51603","data":[],"msg":"Order does not exist"}')

    def orden(self, cl_ord_id: str) -> dict[str, Any] | None:
        mias = [o for o in self.ordenes if o["clOrdId"] == cl_ord_id]
        return mias[-1] if mias else None

    def oco(self, algo_cl_ord_id: str) -> dict[str, Any] | None:
        mias = [a for a in self.ocos if a["algoClOrdId"] == algo_cl_ord_id]
        return mias[-1] if mias else None

    def _mover(self, simbolo: str, lado: str, cantidad: float, precio: float, fee_rate: float) -> float:
        base = simbolo.split("/")[0]
        nocional = cantidad * precio
        fee = nocional * fee_rate
        signo = 1 if lado == "buy" else -1
        self.saldos[base] = self.saldos.get(base, 0.0) + signo * cantidad
        self.saldos["USDC"] = self.saldos.get("USDC", 0.0) - signo * nocional - fee
        return fee

    def llenar(self, cl_ord_id: str, cantidad: float | None = None) -> None:
        """Llena (entera, o `cantidad` mas) una entrada viva a su precio limite, como maker."""
        o = self.orden(cl_ord_id)
        falta = float(o["sz"]) - float(o["accFillSz"])
        q = falta if cantidad is None else min(cantidad, falta)
        fee = self._mover(o["simbolo"], "buy", q, float(o["px"]), FEE["maker"])
        o["accFillSz"] = str(float(o["accFillSz"]) + q)
        o["avgPx"] = o["px"]
        o["fee"] = str(float(o["fee"]) - fee)
        o["fillTime"] = o["uTime"] = str(self.ahora[0])
        if float(o["accFillSz"]) >= float(o["sz"]) - 1e-12:
            o["state"] = "filled"
            self._oco_adjunta(o)
        else:
            o["state"] = "partially_filled"

    def _oco_adjunta(self, o: dict[str, Any]) -> None:
        for adj in o.get("attachAlgoOrds") or []:
            self.ocos.append({"algoId": str(next(self.ids)), "algoClOrdId": adj["attachAlgoClOrdId"],
                              "instId": o["instId"], "ordType": "oco", "side": "sell", "tdMode": "cash",
                              "sz": o["accFillSz"], "state": "live", "tpTriggerPx": adj["tpTriggerPx"],
                              "slTriggerPx": adj["slTriggerPx"], "tpOrdPx": "-1", "slOrdPx": "-1",
                              "cTime": str(self.ahora[0]), "uTime": str(self.ahora[0]), "ordId": "", "ordIdList": [],
                              "actualSide": "", "actualPx": ""})

    def saltar(self, algo_cl_ord_id: str, pata: str, *, lanzada_viva: bool = False) -> None:
        """La OCO salta (sl o tp): lanza una venta a mercado al precio de disparo, como taker."""
        a = self.oco(algo_cl_ord_id)
        simbolo = a["instId"].replace("-", "/")
        precio = float(a["slTriggerPx"] if pata == "sl" else a["tpTriggerPx"])
        q = float(a["sz"])
        fee = self._mover(simbolo, "sell", q, precio, FEE["taker"])
        ord_id = str(next(self.ids))
        self.ordenes.append({"ordId": ord_id, "clOrdId": "O" + ord_id, "algoClOrdId": a["algoClOrdId"],
                             "algoId": a["algoId"], "instId": a["instId"], "simbolo": simbolo, "side": "sell",
                             "tdMode": "cash",
                             "ordType": "market", "sz": str(q), "accFillSz": str(q), "avgPx": str(precio),
                             "fee": str(-fee), "state": "filled", "cTime": str(self.ahora[0]),
                             "uTime": str(self.ahora[0]), "fillTime": str(self.ahora[0])})
        if lanzada_viva:      # la conciliacion la pilla a medio llenar
            self.ordenes[-1]["state"] = "live"
        a.update(state="effective", actualSide=pata, actualPx="", ordId=ord_id, ordIdList=[ord_id],
                 uTime=str(self.ahora[0]))

    # --- lo que llama el bot ---------------------------------------------------------------------------------

    def fetch_balance(self, params=None):
        self._red("fetch_balance", None)
        return {c: {"total": v, "free": v} for c, v in self.saldos.items()}

    def fetch_order_book(self, symbol, limit=None, params=None):
        self._red("fetch_order_book", symbol)
        return {"bids": [[self.precios[symbol], 1.0]], "asks": [[self.precios[symbol] * 1.0001, 1.0]]}

    def fetch_ticker(self, symbol, params=None):
        self._red("fetch_ticker", symbol)
        return {"symbol": symbol, "last": self.precios[symbol]}

    def fetch_time(self, params=None):
        return self.ahora[0]

    def private_get_trade_order(self, p):
        self._red("get_order", p)
        o = (self.orden(p["clOrdId"]) if "clOrdId" in p
             else next((x for x in self.ordenes if x["ordId"] == p.get("ordId")), None))
        if o is None:
            raise self._no_existe()
        return {"code": "0", "data": [dict(o)]}

    def private_get_trade_order_algo(self, p):
        self._red("get_algo", p)
        a = self.oco(p["algoClOrdId"])
        if a is None:
            raise self._no_existe()
        return {"code": "0", "data": [dict(a)]}

    def private_get_trade_orders_pending(self, p):
        self._red("orders_pending", p)
        return {"code": "0", "data": [dict(o) for o in self.ordenes if o["state"] in ("live", "partially_filled")]}

    def private_get_trade_orders_history(self, p):
        self._red("orders_history", p)
        return {"code": "0", "data": [dict(o) for o in self.ordenes if o["state"] in ("filled", "canceled")]}

    def private_get_trade_orders_algo_pending(self, p):
        self._red("algo_pending", p)
        return {"code": "0", "data": [dict(a) for a in self.ocos if a["state"] == "live"]}

    def private_get_trade_orders_algo_history(self, p):
        self._red("algo_history", p)
        return {"code": "0", "data": [dict(a) for a in self.ocos if a["state"] == p["state"]]}

    def private_post_trade_order(self, p):
        self._red("post_order", p)
        assert p["tdMode"] == "cash", "el simulador tampoco acepta margen"
        simbolo = p["instId"].replace("-", "/")
        o = {"ordId": str(next(self.ids)), "clOrdId": p["clOrdId"], "instId": p["instId"], "simbolo": simbolo,
             "side": p["side"], "ordType": p["ordType"], "sz": p["sz"], "px": p.get("px", ""), "accFillSz": "0",
             "avgPx": "", "fee": "0", "state": "live", "cTime": str(self.ahora[0]), "uTime": str(self.ahora[0]),
             "attachAlgoOrds": p.get("attachAlgoOrds") or [], "tradeQuoteCcy": p.get("tradeQuoteCcy"),
             "tdMode": p["tdMode"]}
        self.ordenes.append(o)
        if p["ordType"] == "market":      # la salida: se llena al momento al bid
            q = float(p["sz"])
            fee = self._mover(simbolo, "sell", q, self.precios[simbolo], FEE["taker"])
            o.update(state="filled", accFillSz=str(q), avgPx=str(self.precios[simbolo]), fee=str(-fee),
                     fillTime=str(self.ahora[0]))
        return {"code": "0", "data": [{"clOrdId": p["clOrdId"], "ordId": o["ordId"], "sCode": "0"}]}

    def private_post_trade_cancel_order(self, p):
        self._red("cancel_order", p)
        o = self.orden(p["clOrdId"])
        if o is None or o["state"] not in ("live", "partially_filled"):
            raise ccxt.OrderNotFound('okx {"code":"1","data":[{"sCode":"51400"}]}')
        o["state"], o["uTime"] = "canceled", str(self.ahora[0])
        if float(o["accFillSz"]) > 0:
            self._oco_adjunta(o)       # prueba 4 del demo: al cancelar el resto, la OCO por lo llenado
        return {"code": "0", "data": [{"clOrdId": p["clOrdId"], "sCode": "0"}]}

    def private_post_trade_order_algo(self, p):
        self._red("post_algo", p)
        ultimo = self.precios[p["instId"].replace("-", "/")]
        if float(p["tpTriggerPx"]) < ultimo:        # visto en el demo el 03/10 (prueba 10)
            raise ccxt.InvalidOrder('okx {"code":"1","data":[{"sCode":"51279","sMsg":"TP trigger price cannot be lower '
                                    'than the last price "}]}')
        if float(p["slTriggerPx"]) > ultimo:        # el espejo para el stop (sin verlo en el demo)
            raise ccxt.InvalidOrder('okx {"code":"1","data":[{"sCode":"51280","sMsg":"SL trigger price cannot be higher '
                                    'than the last price "}]}')
        viva = self.oco(p["algoClOrdId"])
        if viva is not None and viva["state"] == "live":
            raise ccxt.InvalidOrder('okx {"code":"1","data":[{"sCode":"51065","sMsg":"algoClOrdId already exists"}]}')
        self.ocos.append({"algoId": str(next(self.ids)), "algoClOrdId": p["algoClOrdId"], "instId": p["instId"],
                          "ordType": "oco", "side": "sell", "tdMode": p["tdMode"], "sz": p["sz"], "state": "live",
                          "tpTriggerPx": p["tpTriggerPx"], "slTriggerPx": p["slTriggerPx"], "tpOrdPx": p["tpOrdPx"],
                          "slOrdPx": p["slOrdPx"], "cTime": str(self.ahora[0]), "uTime": str(self.ahora[0]),
                          "ordId": "", "ordIdList": [], "actualSide": "", "actualPx": ""})
        return {"code": "0", "data": [{"algoClOrdId": p["algoClOrdId"], "sCode": "0"}]}

    def private_post_trade_cancel_algos(self, ps):
        self._red("cancel_algos", ps)
        for p in ps:
            a = self.oco(p["algoClOrdId"])
            if a is None or a["state"] != "live":
                raise ccxt.OrderNotFound('okx {"code":"1","data":[{"sCode":"51603"}]}')
            a["state"], a["uTime"] = "canceled", str(self.ahora[0])
        return {"code": "0", "data": [{"sCode": "0"}]}

    def fills(self) -> list[dict[str, Any]]:
        """Como `GET /api/v5/trade/fills-history`: un llenado por orden (con su ordId y su clOrdId, vacio si la lanzo
        una OCO). El simulador llena de una vez a un solo precio: con eso basta para el juez."""
        return [{"ordId": o["ordId"], "clOrdId": o["clOrdId"], "instId": o["instId"], "side": o["side"],
                 "fillSz": o["accFillSz"], "fillPx": o["avgPx"], "fee": o["fee"], "feeCcy": "USDC",
                 "ts": o.get("fillTime") or o["uTime"]}
                for o in self.ordenes if float(o["accFillSz"]) > 0]
