"""El papel de L hacia adelante (`docs/diseno-papel-l.md`, aprobado por el propietario el 10/10/2026).

Cada noche rehace L desde el lunes 12/10/2026 hasta la ultima vela cerrada, con el MISMO simulador que se midio
(`docs/estudios/tendencia/tendencia.py`), y avisa por Telegram de CADA operacion nueva (compras, ventas, stops y
objetivos). No tiene estado propio que importe (todo sale de las velas guardadas), ni claves, ni ordenes, y no toca
nada del bot: lee la base de la ingesta en `mode=ro`.

Datos: `var/papel-l/historia.db` (la base del anyo USDC con el calentamiento en USDT, `base_anyo_usdc.py`: solo
velas de 1 h y 4 h, instrumentos y spread; se sube una vez) + las velas CERRADAS de 1 h y 4 h de `var/ploutos.db`.
Donde estan en las dos, manda la historia (y se cuenta si alguna difiere). Instrumentos y spread, los de la historia:
asi una vela de hoy no cambia lo que L decidio ayer.

    .venv/bin/python scripts/papel_l.py            # lo lanza ploutos-papel-l.timer (00:20 UTC)
    .venv/bin/python scripts/papel_l.py --seco     # sin Telegram y sin guardar
    .venv/bin/python scripts/papel_l.py --validar  # el anyo USDC con estos datos: tiene que dar L-usdc.json EXACTO

EL FILTRO DE NOTICIAS, EN SOMBRA (el propietario, 11/10; `docs/diseno-embudo-noticias.md` 3): cada noche, ademas, mira que
habria hecho el filtro con las compras y posiciones de L, con las flags de los anuncios de OKX (`ploutos-news.db`) y
las del embudo de los medios (`ploutos-embudo.db`: veredicto "si" con su gravedad; "dudoso" solo frena compras). Lo
apunta y lo avisa; las cifras de L NO cambian.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.secrets import Secrets  # noqa: E402
from data.news import store as noticias_db  # noqa: E402
from features.news import DURACIONES_H, GRAVEDAD, HORA_MS, Flag, Gravedad, Tipo, flags  # noqa: E402
from notify.messages import cabecera, esc  # noqa: E402
from notify.telegram import send_message  # noqa: E402

DIR = REPO / "var" / "papel-l"
HISTORIA = DIR / "historia.db"
INGESTA = REPO / "var" / "ploutos.db"
SIMULADOR = REPO / "docs" / "estudios" / "tendencia" / "tendencia.py"
REFERENCIA = REPO / "docs" / "estudios" / "tendencia" / "L-usdc.json"
NOTICIAS = REPO / "var" / "ploutos-news.db"
EMBUDO = REPO / "var" / "ploutos-embudo.db"
INICIO, FIN = "2026-10-12", "2027-01-11"            # el propietario, 10/10: 3 meses
VELA_4H = 4 * 3600_000
DIA = 86_400_000

log = logging.getLogger("ploutos.papel_l")


def ms(fecha: str) -> int:
    return int(datetime.fromisoformat(fecha).replace(tzinfo=UTC).timestamp() * 1000)


def construir_datos(destino: Path, historia: Path = HISTORIA, ingesta: Path | None = INGESTA) -> dict:
    """La base de trabajo: la historia + las velas cerradas de la ingesta. Devuelve lo que se comprobo."""
    destino.unlink(missing_ok=True)
    shutil.copyfile(historia, destino)
    con = sqlite3.connect(f"file:{destino}", uri=True)
    info = {"anyadidas": 0, "en_las_dos": 0, "distintas": 0}
    if ingesta is not None and ingesta.exists():
        con.execute("ATTACH DATABASE ? AS ing", (f"file:{ingesta}?mode=ro",))
        info["en_las_dos"], info["distintas"] = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(h.open != i.open OR h.high != i.high OR h.low != i.low OR "
            "h.close != i.close), 0) FROM candles h JOIN ing.candles i USING (symbol, timeframe, ts_open_ms) "
            "WHERE i.timeframe IN ('1h', '4h') AND i.closed = 1").fetchone()
        antes = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        con.execute("INSERT OR IGNORE INTO candles SELECT * FROM ing.candles "
                    "WHERE timeframe IN ('1h', '4h') AND closed = 1")
        con.commit()
        info["anyadidas"] = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0] - antes
        con.execute("DETACH DATABASE ing")
    con.close()
    return info


MARGEN_HUECOS_MS = 2 * 3600_000     # una vela que falta desde hace menos se deja a la ingesta (su backfill la rellena)


def huecos(datos: Path, desde_ms: int, hasta_ms: int, margen_ms: int = MARGEN_HUECOS_MS) -> dict[str, int]:
    """Velas de 4 h que faltan, por moneda, desde `desde_ms` hasta la ultima que deberia haber CERRADO hace
    `margen_ms` antes de `hasta_ms` (revision del 15/10/2026: antes, un hueco recien hecho que el backfill rellena
    despues daba FALLA; y se contaba solo hasta la ultima vela QUE HABIA, asi que las que faltaban al final no se veian).
    """
    ultima = (hasta_ms - margen_ms) // VELA_4H * VELA_4H - VELA_4H      # apertura de la ultima que ya debia cerrar
    if ultima < desde_ms:
        return {}
    esperadas = (ultima - desde_ms) // VELA_4H + 1
    con = sqlite3.connect(f"file:{datos}?mode=ro", uri=True)
    tienen = dict(con.execute("SELECT symbol, COUNT(*) FROM candles WHERE timeframe = '4h' AND ts_open_ms BETWEEN ? AND ? "
                              "GROUP BY symbol", (desde_ms, ultima)).fetchall())
    simbolos = [r[0] for r in con.execute("SELECT symbol FROM instruments")]
    con.close()
    return {s: esperadas - tienen.get(s, 0) for s in simbolos if tienen.get(s, 0) < esperadas}


def simular(datos: Path, desde: str, hasta: str) -> dict:
    r = subprocess.run([sys.executable, str(SIMULADOR), "medir", "L", "--base", str(datos), "--desde", desde,
                        "--hasta", hasta], capture_output=True, text=True, cwd=SIMULADOR.parent, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"el simulador fallo: {r.stderr[-2000:]}")
    return json.loads(r.stdout)


def eventos(antes: dict | None, ahora: dict) -> list[dict]:
    """Las operaciones nuevas desde la pasada anterior: compras (posiciones nuevas) y ventas (operaciones cerradas)."""
    antes = antes or {"ops": [], "abiertas": {}}
    vistas = {(o["simbolo"], str(o["entrada_ms"]), str(o["salida_ms"]), o["motivo"]) for o in antes["ops"]}
    abiertas_antes = {(s, str(p["t"])) for s, p in antes["abiertas"].items()}
    compras_vistas = abiertas_antes | {(o["simbolo"], str(o["entrada_ms"])) for o in antes["ops"]}
    out: list[dict] = []
    for o in ahora["ops"]:
        if (o["simbolo"], str(o["entrada_ms"])) not in compras_vistas:
            out.append({"tipo": "compra", "simbolo": o["simbolo"], "t": int(o["entrada_ms"]),
                        "precio": float(o["entrada"])})
            compras_vistas.add((o["simbolo"], str(o["entrada_ms"])))
        if (o["simbolo"], str(o["entrada_ms"]), str(o["salida_ms"]), o["motivo"]) not in vistas:
            out.append({"tipo": "venta", "simbolo": o["simbolo"], "t": int(o["salida_ms"]),
                        "precio": float(o["salida"]), "motivo": o["motivo"], "neto": float(o["neto"])})
    for s, p in ahora["abiertas"].items():
        if (s, str(p["t"])) not in compras_vistas:
            out.append({"tipo": "compra", "simbolo": s, "t": int(p["t"]), "precio": float(p["entrada"]),
                        "nocional": float(p["coste"])})
    return sorted(out, key=lambda e: (e["t"], e["tipo"] != "venta"))


MOTIVO = {"rotacion": "ya no esta entre las elegidas", "stop": "stop", "objetivo": "objetivo (+100 %)"}


def mensaje(evts: list[dict], resultado: dict) -> str | None:
    """El aviso de Telegram, o None si no hay operaciones nuevas. Nunca nombra a la IA (no participa)."""
    if not evts:
        return None
    met = resultado["metricas"]
    lineas = [cabecera("📒", "Papel de L", f"equity {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), "
                                          f"caida max {100 * met['caida_max']:.1f} %")]
    for e in evts:
        dia = datetime.fromtimestamp(e["t"] / 1000, UTC).strftime("%d/%m %H:%M")
        moneda = esc(e["simbolo"].split("/")[0])
        if e["tipo"] == "compra":
            extra = f", {e['nocional']:.2f} $" if "nocional" in e else ""
            lineas.append(f"🟢 {dia} compra <b>{moneda}</b> a {e['precio']:.6g}{extra}")
        else:
            lineas.append(f"🔴 {dia} vende <b>{moneda}</b> a {e['precio']:.6g} ({esc(MOTIVO.get(e['motivo'], e['motivo']))}): "
                          f"{e['neto']:+.2f} $")
    lineas.append("\n<i>Solo papel: ni ordenes ni dinero. Hasta el 11/01/2027.</i>")
    return "\n".join(lineas)


# --- el filtro de noticias, en sombra (el propietario, 11/10) -----------------------------------------------------------------

BASES = ("BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "TRX", "NEAR")
TIPO_ES = {"delisting": "deslistado", "trading_suspension": "suspension", "incident": "hackeo o ataque",
           "migration": "migracion", "volatility": "volatilidad anomala"}


def _ro(ruta: Path) -> sqlite3.Connection | None:
    if not ruta.exists():
        return None
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def flags_del_filtro(noticias: Path | None = NOTICIAS, embudo: Path | None = EMBUDO) -> list[Flag]:
    """Las flags de los anuncios de OKX y las del embudo. Del embudo: "si" con la gravedad de su tipo; "dudoso", ALTA
    (frena compras, no hace vender). Desde el veredicto, el tiempo de una de OKX (un deslistado de medios, 72 h)."""
    out: list[Flag] = []
    n = _ro(noticias) if noticias else None
    if n is not None:
        try:
            out += flags(noticias_db.anuncios(n), BASES, levantadas=noticias_db.levantadas(n))
        except sqlite3.OperationalError:
            pass
        n.close()
    e = _ro(embudo) if embudo else None
    if e is not None:
        try:
            for c in e.execute("SELECT id, moneda, tipo, veredicto, veredicto_ms, motivo FROM casos "
                               "WHERE veredicto IN ('si', 'dudoso')"):
                tipo = Tipo(c["tipo"])
                horas = DURACIONES_H[tipo] or 72
                gravedad = GRAVEDAD[tipo] if c["veredicto"] == "si" else Gravedad.ALTA
                out.append(Flag(c["moneda"], tipo, gravedad, int(c["veredicto_ms"]),
                                int(c["veredicto_ms"]) + int(horas * HORA_MS), f"embudo:{c['id']}", c["motivo"]))
        except sqlite3.OperationalError:
            pass
        e.close()
    return out


def _origen(f: Flag) -> str:
    de = "medios (la IA)" if f.anuncio.startswith("embudo:") else "OKX"
    return f"{TIPO_ES.get(f.tipo.value, f.tipo.value)}, {de}"


def filtro_en_sombra(resultado: dict, todas: list[Flag], precio_en) -> list[dict]:
    """Lo que el filtro habria hecho con L: compras frenadas y ventas adelantadas. `precio_en(simbolo, ms)`: la
    apertura de la primera vela de 4 h desde `ms` (o None)."""
    tramos = [(o["simbolo"], int(o["entrada_ms"]), int(o["salida_ms"])) for o in resultado["ops"]]
    tramos += [(s, int(p["t"]), None) for s, p in resultado["abiertas"].items()]
    out = []
    for simbolo, entrada, salida in sorted(tramos, key=lambda x: x[1]):
        base = simbolo.split("/")[0]
        activas = [f for f in todas if f.moneda == base and f.activa(entrada)]
        if activas:
            out.append({"tipo": "compra_frenada", "simbolo": simbolo, "t": entrada, "por": _origen(activas[0])})
            continue
        criticas = sorted((f for f in todas if f.moneda == base and f.gravedad is Gravedad.CRITICA
                           and entrada < f.desde_ms and (salida is None or f.desde_ms < salida)),
                          key=lambda f: f.desde_ms)
        if criticas:
            f = criticas[0]
            out.append({"tipo": "venta_adelantada", "simbolo": simbolo, "t": f.desde_ms,
                        "precio": precio_en(simbolo, f.desde_ms), "por": _origen(f)})
    return out


def clave_filtro(e: dict) -> str:
    return f"{e['tipo']}:{e['simbolo']}:{e['t']}"


def mensaje_filtro(evts: list[dict]) -> str | None:
    if not evts:
        return None
    lineas = [cabecera("🛡️", "Papel de L: el filtro de noticias (en sombra)", "las cifras de L no cambian")]
    for e in evts:
        dia = datetime.fromtimestamp(e["t"] / 1000, UTC).strftime("%d/%m %H:%M")
        moneda = esc(e["simbolo"].split("/")[0])
        if e["tipo"] == "compra_frenada":
            lineas.append(f"✋ {dia}: habria impedido comprar <b>{moneda}</b> ({esc(e['por'])})")
        else:
            p = "" if e.get("precio") is None else f" a {e['precio']:.6g}"
            lineas.append(f"🔻 {dia}: habria vendido <b>{moneda}</b>{p} ({esc(e['por'])})")
    return "\n".join(lineas)


def _precio_en(datos: Path):
    def precio(simbolo: str, t: int) -> float | None:
        con = sqlite3.connect(f"file:{datos}?mode=ro", uri=True)
        fila = con.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '4h' AND ts_open_ms >= ? "
                           "ORDER BY ts_open_ms LIMIT 1", (simbolo, t)).fetchone()
        con.close()
        return None if fila is None else float(fila[0])
    return precio


def validar() -> int:
    """Con estos mismos datos, el anyo USDC tiene que salir EXACTO al de la medicion (`L-usdc.json`)."""
    DIR.mkdir(parents=True, exist_ok=True)
    datos = DIR / "validar.db"
    info = construir_datos(datos)
    print(f"datos: {info}")
    ref = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    hoy = simular(datos, "2025-09-01", "2026-09-28")
    igual = hoy["curva"] == ref["curva"] and hoy["ops"] == ref["ops"]
    datos.unlink(missing_ok=True)
    print(f"anyo USDC con los datos del papel: {len(hoy['curva'])} dias, {len(hoy['ops'])} operaciones -> "
          f"{'IGUAL a L-usdc.json' if igual else 'DISTINTO'}")
    if info["distintas"]:
        print(f"OJO: {info['distintas']} velas difieren entre la historia y la ingesta (manda la historia)")
    return 0 if igual and not info["distintas"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="El papel de L, cada noche")
    ap.add_argument("--seco", action="store_true", help="sin Telegram y sin guardar")
    ap.add_argument("--validar", action="store_true", help="el anyo USDC con estos datos, contra L-usdc.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.validar:
        return validar()
    ahora_ms = int(time.time() * 1000)
    if ahora_ms < ms(INICIO) + DIA:                 # el primer dia, entero (la curva es de cierres diarios)
        log.info("el papel de L empieza el %s: aun no hay nada que simular", INICIO)
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    datos = DIR / "datos.db"
    info = construir_datos(datos)
    faltan = huecos(datos, ms(INICIO), min(ahora_ms, ms(FIN)))
    resultado = simular(datos, INICIO, FIN)
    ultimo = DIR / "ultimo.json"
    antes = json.loads(ultimo.read_text(encoding="utf-8")) if ultimo.exists() else None
    evts = eventos(antes, resultado)
    filtro = filtro_en_sombra(resultado, flags_del_filtro(), _precio_en(datos))
    vistos_ruta = DIR / "filtro-avisados.json"
    vistos = set(json.loads(vistos_ruta.read_text(encoding="utf-8"))) if vistos_ruta.exists() else set()
    filtro_nuevo = [e for e in filtro if clave_filtro(e) not in vistos]
    meta = {"pasada_ms": ahora_ms, "datos": info, "huecos": faltan, "eventos": evts, "filtro": filtro}
    log.info("equity %.2f $, %d operaciones, %d abiertas, %d eventos nuevos, huecos %s",
             resultado["metricas"]["final"], len(resultado["ops"]), len(resultado["abiertas"]), len(evts), faltan)
    texto = mensaje(evts, resultado)
    texto_filtro = mensaje_filtro(filtro_nuevo)
    if args.seco:
        print(json.dumps(meta, indent=1, default=str))
        for t in (texto, texto_filtro):
            if t:
                print(t)
        return 0
    if texto_filtro:
        secretos_f = Secrets()
        envio_f = send_message(secretos_f.valor("telegram_bot_token"), secretos_f.telegram_chat_id, texto_filtro)
        log.info("aviso del filtro: %s", envio_f.detalle)
        if envio_f.ok:
            vistos_ruta.write_text(json.dumps(sorted(vistos | {clave_filtro(e) for e in filtro_nuevo})),
                                   encoding="utf-8")
    if texto:
        secretos = Secrets()
        envio = send_message(secretos.valor("telegram_bot_token"), secretos.telegram_chat_id, texto)
        log.info("aviso: %s", envio.detalle)
        if not envio.ok:
            # Sin guardar: la noche siguiente se vuelven a avisar las mismas operaciones.
            (DIR / "meta.json").write_text(json.dumps({**meta, "aviso": envio.detalle}, default=str), encoding="utf-8")
            datos.unlink(missing_ok=True)
            return 1
    ultimo.write_text(json.dumps(resultado, default=str), encoding="utf-8")
    (DIR / "meta.json").write_text(json.dumps(meta, default=str), encoding="utf-8")
    datos.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
