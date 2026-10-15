"""El embudo de noticias para L (`docs/diseno-embudo-noticias.md`, aprobado por el propietario el 11/10/2026). EN SOMBRA.

Cada 30 min (`ploutos-embudo.timer`), con los titulares de los medios (`ploutos-medios.db`, en `mode=ro`):
1. **Palabras clave:** el clasificador de los anuncios de OKX (`features/news.py`) TAL CUAL. Un titular de una de las
   8 monedas con un tipo critico o alto abre un CASO (moneda + tipo); los de las 12 h siguientes se le juntan.
2. **Confirmacion** (en las 12 h): 3 o mas medios distintos con al menos uno de calidad A, o una caida de 2 ATR (4 h)
   en las 3 velas siguientes. **Camino rapido:** si L tiene la moneda, el tipo es critico y hay un titular de calidad
   A, va directo al paso 3. Sin confirmar a las 12 h: "no confirmado".
3. **La IA da el veredicto** (`ai/clasificador.py`): si / no / dudoso. Sin respuesta valida, "sin veredicto" (no hacer
   nada). Presupuesto propio: 6 al dia; y nunca si el total del dia con el analista llega a 40 o el de 5 h a 8 (regla
   18; el analista no ve las del embudo, para no tocar su camino en la fase 6).

Telegram con cada veredicto si, dudoso o sin veredicto. Lo que hace el filtro con L lo apunta `scripts/papel_l.py`.
No toca nada del bot ni tiene claves de OKX; escribe solo en su base (`var/ploutos-embudo.db`).

    .venv/bin/python scripts/embudo_noticias.py           # lo lanza ploutos-embudo.timer
    .venv/bin/python scripts/embudo_noticias.py --seco    # dice lo que haria, sin llamar a la IA ni mandar nada
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai.clasificador import MAX_TITULARES  # noqa: E402
from ai.clasificador import clasificar as preguntar_ia  # noqa: E402
from features.indicators import atr  # noqa: E402
from features.news import GRAVEDAD, Gravedad, Tipo  # noqa: E402
from features.news import clasificar as palabras_clave  # noqa: E402

VAR = REPO / "var"
MEDIOS = VAR / "ploutos-medios.db"
INGESTA = VAR / "ploutos.db"
ANALISTA = VAR / "ploutos-paper-ai.db"
BASE = VAR / "ploutos-embudo.db"
PAPEL_L = VAR / "papel-l" / "ultimo.json"
CLAUDE_HOME = VAR / "claude_home_embudo"
BASES = ("BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "TRX", "NEAR")
INICIO = "2026-10-12"                       # como el papel de L: los titulares de antes no se miran
H4 = 4 * 3600_000
VENTANA_MS = 12 * 3600_000
MIN_FUENTES = 3
ATR_CAIDA = 2.0
VELAS_PRECIO = 3
PRESUPUESTO_DIA = 6
REGLA18_DIA, REGLA18_5H = 40, 8

log = logging.getLogger("ploutos.embudo")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS casos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    moneda        TEXT    NOT NULL,
    tipo          TEXT    NOT NULL,
    abierto_ms    INTEGER NOT NULL,            -- el primer titular
    estado        TEXT    NOT NULL,            -- abierto | no_confirmado | confirmado | juzgado
    paso2         TEXT,                        -- fuentes | precio | rapido
    confirmado_ms INTEGER,
    veredicto     TEXT,                        -- si | no | dudoso | sin_veredicto
    motivo        TEXT    NOT NULL DEFAULT '',
    veredicto_ms  INTEGER,
    avisado       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS caso_titulares (
    caso_id     INTEGER NOT NULL,
    titular_id  TEXT    NOT NULL,
    fuente      TEXT    NOT NULL,
    calidad     TEXT    NOT NULL,
    titulo      TEXT    NOT NULL,              -- texto NO confiable
    ms          INTEGER NOT NULL,
    PRIMARY KEY (caso_id, titular_id)
);
CREATE TABLE IF NOT EXISTS llamadas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ms          INTEGER NOT NULL,
    caso_id     INTEGER NOT NULL,
    entrada     TEXT    NOT NULL,
    salida      TEXT    NOT NULL,
    outcome     TEXT    NOT NULL,
    valida      INTEGER NOT NULL,
    veredicto   TEXT,
    latencia_s  REAL    NOT NULL,
    detalle     TEXT    NOT NULL DEFAULT '',
    modelo      TEXT
);
CREATE TABLE IF NOT EXISTS pasadas (ms INTEGER PRIMARY KEY, ok INTEGER NOT NULL, detalle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cursor (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL);
"""


def ms(fecha: str) -> int:
    return int(datetime.fromisoformat(fecha).replace(tzinfo=UTC).timestamp() * 1000)


def conectar(ruta: Path = BASE) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=10)
    conn.row_factory = sqlite3.Row
    # Sin WAL (14/10): el embudo escribe una vez cada 30 min y cierra. En WAL, al cerrar se borran el -wal y el -shm, y
    # quien lee desde un sistema de ficheros de solo lectura (la copia de cada noche, ProtectSystem=strict) no puede
    # volver a crearlos: "unable to open database file". Con el diario normal se lee sin escribir nada.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.executescript(ESQUEMA)
    return conn


def ro(ruta: Path) -> sqlite3.Connection | None:
    if not ruta.exists():
        return None
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# --- paso 1 ----------------------------------------------------------------------------------------------------------

def abrir_casos(emb: sqlite3.Connection, medios: sqlite3.Connection, desde_ms: int) -> int:
    """Lee los titulares nuevos y los junta en casos. Devuelve cuantos titulares entraron en alguno.

    "Nuevos" por el NUMERO DE FILA (`rowid`), no por `visto_ms` (revision del 15/10/2026): ploutos-medios pone el mismo
    `visto_ms` a toda una pasada y la guarda fuente a fuente; leyendo a mitad de guardado, el cursor por hora marcaba
    esa hora como vista y las fuentes que faltaban no se leian nunca. El `rowid` crece con cada fila y no se repite.
    """
    fila = emb.execute("SELECT valor FROM cursor WHERE clave = 'rowid'").fetchone()
    if fila is not None:
        cursor = fila[0]
    else:
        # El cursor viejo era por hora: se pasa al ultimo rowid de lo que ya estaba visto (solo una vez).
        viejo = emb.execute("SELECT valor FROM cursor WHERE clave = 'visto_ms'").fetchone()
        cursor = 0 if viejo is None else (medios.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM medios_titulares WHERE visto_ms < ?", (viejo[0],)).fetchone()[0])
    nuevos = medios.execute(
        "SELECT rowid, id, fuente, calidad, titulo, publicado_ms, visto_ms FROM medios_titulares WHERE rowid > ? "
        "ORDER BY rowid", (cursor,)).fetchall()
    entraron = 0
    for t in nuevos:
        cuando = min(t["publicado_ms"] or t["visto_ms"], t["visto_ms"])
        if cuando < desde_ms:
            continue
        for aviso in palabras_clave(t["titulo"], BASES):
            if aviso.tipo is Tipo.RESUMPTION:
                continue
            caso = emb.execute("SELECT id, abierto_ms FROM casos WHERE moneda = ? AND tipo = ? AND ABS(abierto_ms - ?) < ? "
                               "ORDER BY abierto_ms DESC LIMIT 1", (aviso.moneda, aviso.tipo.value, cuando, VENTANA_MS)
                               ).fetchone()
            if caso is None:
                cid = emb.execute("INSERT INTO casos (moneda, tipo, abierto_ms, estado) VALUES (?,?,?,'abierto')",
                                  (aviso.moneda, aviso.tipo.value, cuando)).lastrowid
            else:
                cid = caso["id"]
                if cuando < caso["abierto_ms"]:
                    emb.execute("UPDATE casos SET abierto_ms = ? WHERE id = ?", (cuando, cid))
            emb.execute("INSERT OR IGNORE INTO caso_titulares VALUES (?,?,?,?,?,?)",
                        (cid, t["id"], t["fuente"], t["calidad"], t["titulo"], cuando))
            entraron += 1
    if nuevos:
        emb.execute("INSERT OR REPLACE INTO cursor VALUES ('rowid', ?)", (max(t["rowid"] for t in nuevos),))
    emb.commit()
    return entraron


# --- paso 2 ----------------------------------------------------------------------------------------------------------

def caida_en_atr(ingesta: sqlite3.Connection | None, moneda: str, t0: int) -> float | None:
    """Cuantos ATR (14, velas de 4 h) cae el minimo de las 3 velas siguientes respecto al cierre de la vela anterior
    al primer titular. None si aun no se puede saber (faltan velas o ATR)."""
    if ingesta is None:
        return None
    par = f"{moneda}/USDC"
    antes = ingesta.execute(
        "SELECT ts_open_ms, high, low, close FROM candles WHERE symbol = ? AND timeframe = '4h' AND closed = 1 "
        "AND ts_open_ms + ? <= ? ORDER BY ts_open_ms DESC LIMIT 80", (par, H4, t0)).fetchall()[::-1]
    if len(antes) < 45:
        return None
    serie = atr(pd.Series([r["high"] for r in antes]), pd.Series([r["low"] for r in antes]),
                pd.Series([r["close"] for r in antes]), 14)
    valor = float(serie.iloc[-1])
    if not valor == valor or valor <= 0:
        return None
    despues = ingesta.execute(
        "SELECT low FROM candles WHERE symbol = ? AND timeframe = '4h' AND closed = 1 AND ts_open_ms >= ? "
        "ORDER BY ts_open_ms LIMIT ?", (par, antes[-1]["ts_open_ms"] + H4, VELAS_PRECIO)).fetchall()
    if not despues:
        return None
    return (antes[-1]["close"] - min(r["low"] for r in despues)) / valor


def confirmar(emb: sqlite3.Connection, ingesta: sqlite3.Connection | None, tenidas: set[str], ahora_ms: int) -> None:
    for c in emb.execute("SELECT * FROM casos WHERE estado = 'abierto'").fetchall():
        tits = emb.execute("SELECT fuente, calidad FROM caso_titulares WHERE caso_id = ?", (c["id"],)).fetchall()
        hay_a = any(t["calidad"] == "A" for t in tits)
        critico = GRAVEDAD[Tipo(c["tipo"])] is Gravedad.CRITICA
        paso = None
        if c["moneda"] in tenidas and critico and hay_a:
            paso = "rapido"
        elif len({t["fuente"] for t in tits}) >= MIN_FUENTES and hay_a:
            paso = "fuentes"
        else:
            caida = caida_en_atr(ingesta, c["moneda"], c["abierto_ms"])
            if caida is not None and caida >= ATR_CAIDA:
                paso = "precio"
        if paso:
            emb.execute("UPDATE casos SET estado = 'confirmado', paso2 = ?, confirmado_ms = ? WHERE id = ?",
                        (paso, ahora_ms, c["id"]))
        elif ahora_ms >= c["abierto_ms"] + VENTANA_MS:
            emb.execute("UPDATE casos SET estado = 'no_confirmado' WHERE id = ?", (c["id"],))
    emb.commit()


# --- paso 3 ----------------------------------------------------------------------------------------------------------

def presupuesto(emb: sqlite3.Connection, analista: sqlite3.Connection | None, ahora_ms: int) -> str | None:
    """None si se puede llamar; si no, el motivo."""
    dia = ahora_ms - ahora_ms % 86_400_000
    cinco = ahora_ms - 5 * 3600_000
    propias_dia = emb.execute("SELECT COUNT(*) FROM llamadas WHERE ms >= ?", (dia,)).fetchone()[0]
    propias_5h = emb.execute("SELECT COUNT(*) FROM llamadas WHERE ms >= ?", (cinco,)).fetchone()[0]
    suyas_dia = suyas_5h = 0
    if analista is not None:
        try:
            q = "SELECT COUNT(*) FROM ai_calls WHERE called_ms >= ? AND outcome NOT LIKE 'skipped%'"
            suyas_dia = analista.execute(q, (dia,)).fetchone()[0]
            suyas_5h = analista.execute(q, (cinco,)).fetchone()[0]
        except sqlite3.OperationalError:
            pass
    if propias_dia >= PRESUPUESTO_DIA:
        return f"presupuesto del embudo agotado ({PRESUPUESTO_DIA} al dia)"
    if propias_dia + suyas_dia >= REGLA18_DIA or propias_5h + suyas_5h >= REGLA18_5H:
        return "regla 18: el total de llamadas a la IA del dia o de 5 h esta en el tope"
    return None


def juzgar(emb: sqlite3.Connection, analista: sqlite3.Connection | None, ahora_ms: int, *, preguntar) -> int:
    """Pasa a la IA los casos confirmados. `preguntar(moneda, tipo, titulares)` -> Veredicto (ai.clasificador)."""
    hechos = 0
    for c in emb.execute("SELECT * FROM casos WHERE estado = 'confirmado'").fetchall():
        motivo_no = presupuesto(emb, analista, ahora_ms)
        if motivo_no:
            emb.execute("UPDATE casos SET estado = 'juzgado', veredicto = 'sin_veredicto', motivo = ?, veredicto_ms = ? "
                        "WHERE id = ?", (motivo_no, ahora_ms, c["id"]))
            continue
        tits = emb.execute("SELECT fuente, titulo, ms FROM caso_titulares WHERE caso_id = ? ORDER BY ms LIMIT ?",
                           (c["id"], MAX_TITULARES)).fetchall()
        filas = [(t["fuente"], datetime.fromtimestamp(t["ms"] / 1000, UTC).strftime("%d/%m %H:%M"), t["titulo"])
                 for t in tits]
        v = preguntar(c["moneda"], c["tipo"], filas)
        emb.execute("INSERT INTO llamadas (ms, caso_id, entrada, salida, outcome, valida, veredicto, latencia_s, "
                    "detalle, modelo) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ahora_ms, c["id"], v.entrada, json.dumps(v.salida, ensure_ascii=False, default=str)[:4000],
                     v.outcome.value, int(v.veredicto is not None), v.veredicto, round(v.latencia_s, 2),
                     v.detalle[:500], v.modelo))
        emb.execute("UPDATE casos SET estado = 'juzgado', veredicto = ?, motivo = ?, veredicto_ms = ? WHERE id = ?",
                    (v.veredicto or "sin_veredicto", v.motivo if v.veredicto else (v.detalle or v.outcome.value)[:200],
                     ahora_ms, c["id"]))
        hechos += 1
    emb.commit()
    return hechos


# --- avisos ----------------------------------------------------------------------------------------------------------

DICE = {"si": "sí, es un problema de la moneda", "dudoso": "dudoso", "sin_veredicto": "sin veredicto"}
QUE_HARIA = {"si": "no comprarla y, si es crítico y L la tiene, venderla", "dudoso": "no comprarla (no hace vender)",
             "sin_veredicto": "nada (sin veredicto no se frena)"}
TIPO_ES = {"delisting": "deslistado", "trading_suspension": "suspensión", "incident": "hackeo o ataque",
           "migration": "migración", "volatility": "volatilidad anómala"}


def mensajes(emb: sqlite3.Connection) -> list[tuple[int, str]]:
    """Un aviso por cada veredicto si, dudoso o sin veredicto aun no avisado. Nunca nombra a Claude: "la IA"."""
    from notify.messages import cabecera, esc
    out = []
    for c in emb.execute("SELECT * FROM casos WHERE estado = 'juzgado' AND avisado = 0 AND veredicto IN "
                         "('si', 'dudoso', 'sin_veredicto') ORDER BY id").fetchall():
        tits = emb.execute("SELECT fuente, titulo FROM caso_titulares WHERE caso_id = ? ORDER BY ms LIMIT 3",
                           (c["id"],)).fetchall()
        lineas = [cabecera("📰", f"Embudo de noticias: {esc(c['moneda'])}", "en sombra: no cambia nada de L"),
                  f"Tipo: {esc(TIPO_ES.get(c['tipo'], c['tipo']))} · confirmado por {esc(c['paso2'] or '-')}",
                  f"La IA: <b>{esc(DICE[c['veredicto']])}</b>" + (f" ({esc(c['motivo'])})" if c["motivo"] else ""),
                  f"El filtro haría: {esc(QUE_HARIA[c['veredicto']])}", ""]
        lineas += [f"· {esc(t['fuente'])}: <i>{esc(t['titulo'])}</i>" for t in tits]
        out.append((c["id"], "\n".join(lineas).replace("Claude", "la IA")))
    return out


def tenidas_por_l(ruta: Path = PAPEL_L) -> set[str]:
    """Las monedas que L tiene segun la ultima pasada de su papel (base, sin "/USDC")."""
    try:
        return {s.split("/")[0] for s in json.loads(ruta.read_text(encoding="utf-8"))["abiertas"]}
    except (OSError, ValueError, KeyError):
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description="El embudo de noticias para L, en sombra")
    ap.add_argument("--seco", action="store_true", help="sin llamar a la IA ni mandar nada")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ahora_ms = int(time.time() * 1000)
    if ahora_ms < ms(INICIO):
        log.info("el embudo empieza el %s, con el papel de L", INICIO)
        return 0
    medios = ro(MEDIOS)
    if medios is None:
        log.error("no hay base de medios: nada que mirar")
        return 1
    emb = conectar(BASE if not args.seco else Path(":memory:"))
    if args.seco:                                   # en seco, sobre una copia en memoria de la base
        real = ro(BASE)
        if real is not None:
            real.backup(emb)
    entraron = abrir_casos(emb, medios, ms(INICIO))
    confirmar(emb, ro(INGESTA), tenidas_por_l(), ahora_ms)
    if args.seco:
        pendientes = emb.execute("SELECT moneda, tipo, paso2 FROM casos WHERE estado = 'confirmado'").fetchall()
        print(f"titulares nuevos en casos: {entraron}; irian a la IA: {[tuple(p) for p in pendientes]}")
        return 0
    from core.config import load_settings
    from core.secrets import Secrets
    from notify.telegram import send_message
    settings, secretos = load_settings(), Secrets()
    token = secretos.claude_code_oauth_token
    token = token.get_secret_value().strip() if token else ""

    def preguntar(moneda, tipo, filas):
        return preguntar_ia(moneda, tipo, filas, token=token, config_dir=CLAUDE_HOME, model=settings.claude.model,
                            timeout_s=settings.claude.timeout_seconds)

    hechos = juzgar(emb, ro(ANALISTA), ahora_ms, preguntar=preguntar) if token else 0
    if not token:
        log.error("falta CLAUDE_CODE_OAUTH_TOKEN: los casos confirmados esperan")
    for cid, texto in mensajes(emb):
        envio = send_message(secretos.valor("telegram_bot_token"), secretos.telegram_chat_id, texto)
        if envio.ok:
            emb.execute("UPDATE casos SET avisado = 1 WHERE id = ?", (cid,))
        log.info("aviso del caso %s: %s", cid, envio.detalle)
    emb.execute("INSERT OR REPLACE INTO pasadas VALUES (?,?,?)",
                (ahora_ms, 1, json.dumps({"titulares": entraron, "juzgados": hechos})))
    emb.commit()
    log.info("pasada: %d titulares en casos, %d juzgados", entraron, hechos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
