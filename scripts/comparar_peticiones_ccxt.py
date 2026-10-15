"""Las peticiones que el bot mandaria a OKX, construidas y SERIALIZADAS por la version de ccxt de este Python.

Sin red y sin claves de verdad: los mercados salen de un fichero (bajado una vez de los datos publicos) y el envio
se intercepta (`fetch` devuelve una respuesta falsa). Se guarda metodo, URL, cuerpo y la cabecera del demo.

    python scripts/comparar_peticiones_ccxt.py <mercados.json> <salida.json>   # una vez con cada ccxt y comparar las salidas
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import ccxt  # noqa: E402

from core.config import load_settings  # noqa: E402
from execution import guardia, peticiones  # noqa: E402
from execution.precios import PreciosOrden  # noqa: E402

mercados_f, salida_f = Path(sys.argv[1]), Path(sys.argv[2])
settings = load_settings()
ex = ccxt.okx({"hostname": settings.exchange.hostname, "apiKey": "k", "secret": "s", "password": "p",
               "options": {"defaultType": "spot", **guardia.OPCIONES_EXCHANGE}, "headers": {"User-Agent": "ploutos/0.1"}})
ex.set_sandbox_mode(True)
if not mercados_f.exists():
    publico = ccxt.okx({"hostname": settings.exchange.hostname, "options": {"defaultType": "spot"}})
    publico.load_markets()
    mercados_f.write_text(json.dumps({s: publico.markets[s] for s in settings.whitelist}), encoding="utf-8")
ex.set_markets(list(json.loads(mercados_f.read_text(encoding="utf-8")).values()))

enviadas = []


def falso(url, method="GET", headers=None, body=None):
    enviadas.append({"metodo": method, "url": url, "cuerpo": json.loads(body) if body else None,
                     "demo": (headers or {}).get("x-simulated-trading")})
    return {"code": "0", "msg": "", "data": [{"ordId": "1", "clOrdId": "", "algoId": "1", "sCode": "0", "sMsg": ""}]}


ex.fetch = falso
wl = tuple(settings.whitelist)
salida = {"ccxt": ccxt.__version__, "casos": []}
for s in wl:
    m = ex.markets[s]
    tick, lote = float(m["precision"]["price"]), float(m["precision"]["amount"])
    base = 1000 * tick
    for k, f in enumerate((1.0, 1.2345678, 7.77777)):
        p = base * f * (k + 1) * 10
        did = f"d-20261007T{k:02d}00-{s.split('/')[0].lower()}-pb"
        pr = PreciosOrden(entrada=p, stop=p * 0.967, objetivo=p * 1.066, cantidad=(15 / p) + lote * 0.37)
        caso = {"simbolo": s, "precio": p,
                "redondeo": {"precio": ex.price_to_precision(s, p * 1.000123), "cantidad": ex.amount_to_precision(s, pr.cantidad)}}
        e = peticiones.entrada(ex, decision_id=did, simbolo=s, precios=pr, whitelist=wl)
        o = peticiones.proteccion(ex, decision_id=did, simbolo=s, cantidad=pr.cantidad, stop=pr.stop,
                                  objetivo=pr.objetivo, whitelist=wl)
        v = peticiones.salida(ex, decision_id=did, simbolo=s, cantidad=pr.cantidad, whitelist=wl)
        caso["construidas"] = {"entrada": e, "proteccion": o, "salida": v}
        antes = len(enviadas)
        ex.private_post_trade_order(e)
        ex.private_post_trade_order_algo(o)
        ex.private_post_trade_order(v)
        ex.private_post_trade_cancel_order(peticiones.cancelar_entrada(decision_id=did, simbolo=s, whitelist=wl))
        ex.private_post_trade_cancel_algos([peticiones.cancelar_oco(decision_id=did, simbolo=s, whitelist=wl)])
        ex.private_get_trade_order({"instId": s.replace("/", "-"), "clOrdId": "x"})
        caso["serializadas"] = enviadas[antes:]
        salida["casos"].append(caso)
salida_f.write_text(json.dumps(salida, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
print(ccxt.__version__, len(salida["casos"]), "casos,", len(enviadas), "peticiones serializadas")
