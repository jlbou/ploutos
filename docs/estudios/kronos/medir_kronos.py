"""Kronos, paso 1: acierta con nuestras monedas? (`docs/archivo/plan-segunda-ronda-estrategia.md`, idea E; aprobado por el propietario el
08/10 antes de medir, con los detalles fijados en `9ffcb7c`).

Corre en su PROPIO entorno (`var/kronos/.venv`, con PyTorch para CPU), no en el del bot, y no toca el bot:

    var/kronos/.venv/Scripts/python.exe docs/estudios/kronos/medir_kronos.py predecir [--max N]   # -> resultados/
    var/kronos/.venv/Scripts/python.exe docs/estudios/kronos/medir_kronos.py juzgar

- Datos: `docs/estudios/time-stop/historia.db`, velas de 4 h contra USDC (todo despues de junio de 2024, el final del
  pre-entrenamiento de Kronos).
- Kronos-small sin reentrenar, solo OHLC, las 400 velas cerradas anteriores, prediccion de 6 velas, T=1.0, top_p=0.9,
  sample_count=5, semilla de torch fija por prediccion. Una prediccion cada 6 velas desde la vela 400 de cada moneda.
  Las fechas de las 6 velas futuras se generan (ultima + 4 h x k), nunca se leen del futuro.
- predicho = cierre medio de la vela +6 / ultimo cierre - 1; real = cierre de la vela +6 / ultimo cierre - 1.
- Pasa si la correlacion de rangos (Spearman) del conjunto tiene el IC 90 % (bootstrap de dias, 10.000, semilla
  fija) entero por encima de 0 Y es positiva en >= 5 de las 8 monedas.
Cada prediccion se apunta en cuanto sale (`resultados/predicciones.jsonl`): si se corta, se sigue donde iba.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[2]
DB = REPO / "docs" / "estudios" / "time-stop" / "historia.db"
SALIDA = AQUI / "resultados"
PREDICCIONES = SALIDA / "predicciones.jsonl"
KRONOS = REPO / "var" / "kronos" / "Kronos"

CONTEXTO, HORIZONTE, PASO = 400, 6, 6
T, TOP_P, MUESTRAS = 1.0, 0.9, 5
SEMILLA = 20261008
VELA_MS = 4 * 3600_000
ITER = 10_000
MIN_MONEDAS = 5


def velas() -> dict[str, pd.DataFrame]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = {}
    for (s,) in con.execute("SELECT DISTINCT symbol FROM candles WHERE timeframe='4h' ORDER BY symbol").fetchall():
        out[s] = pd.read_sql_query("SELECT ts_open_ms, open, high, low, close FROM candles WHERE symbol=? AND "
                                   "timeframe='4h' ORDER BY ts_open_ms", con, params=(s,))
    con.close()
    return out


def hechas() -> set[tuple[str, int]]:
    if not PREDICCIONES.exists():
        return set()
    return {(r["simbolo"], r["ts_ms"]) for r in map(json.loads, PREDICCIONES.read_text(encoding="utf-8").splitlines())}


def predecir(maximo: int | None) -> None:
    import torch
    sys.path.insert(0, str(KRONOS))
    os.environ.setdefault("HF_HOME", str(REPO / "var" / "kronos" / "hf"))
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    modelo = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    tokenizer.eval()
    modelo.eval()
    pred = KronosPredictor(modelo, tokenizer, device="cpu", max_context=512)

    SALIDA.mkdir(exist_ok=True)
    ya = hechas()
    n = 0
    t0 = time.time()
    with PREDICCIONES.open("a", encoding="utf-8") as f:
        for s, df in velas().items():
            for i in range(CONTEXTO - 1, len(df) - HORIZONTE, PASO):
                ts = int(df["ts_open_ms"].iloc[i])
                if (s, ts) in ya:
                    continue
                ctx = df.iloc[i - CONTEXTO + 1:i + 1]
                x_ts = pd.Series(pd.to_datetime(ctx["ts_open_ms"], unit="ms"))
                y_ts = pd.Series(pd.to_datetime([ts + VELA_MS * k for k in range(1, HORIZONTE + 1)], unit="ms"))
                torch.manual_seed(SEMILLA + ts // VELA_MS)
                p = pred.predict(ctx[["open", "high", "low", "close"]].reset_index(drop=True), x_ts.reset_index(drop=True),
                                 y_ts, pred_len=HORIZONTE, T=T, top_p=TOP_P, sample_count=MUESTRAS, verbose=False)
                ultimo = float(df["close"].iloc[i])
                fila = {"simbolo": s, "ts_ms": ts, "ultimo": ultimo,
                        "predicho": float(p["close"].iloc[-1]) / ultimo - 1,
                        "real": float(df["close"].iloc[i + HORIZONTE]) / ultimo - 1}
                f.write(json.dumps(fila) + "\n")
                f.flush()
                n += 1
                if n % 50 == 0:
                    print(f"{n} predicciones, {(time.time() - t0) / n:.2f} s cada una", flush=True)
                if maximo is not None and n >= maximo:
                    print(f"{n} predicciones en {time.time() - t0:.0f} s ({(time.time() - t0) / n:.2f} s cada una)")
                    return
    print(f"listo: {n} predicciones nuevas en {time.time() - t0:.0f} s")


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def juzgar() -> int:
    filas = [json.loads(x) for x in PREDICCIONES.read_text(encoding="utf-8").splitlines()]
    df = pd.DataFrame(filas)
    df["dia"] = [datetime.fromtimestamp(t / 1000, tz=UTC).date().isoformat() for t in df["ts_ms"]]
    total = spearman(df["predicho"].to_numpy(), df["real"].to_numpy())
    rnd = random.Random(SEMILLA)
    grupos = {d: g.index.to_numpy() for d, g in df.groupby("dia")}
    dias = sorted(grupos)
    pre, rea = df["predicho"].to_numpy(), df["real"].to_numpy()
    muestras = []
    for _ in range(ITER):
        idx = np.concatenate([grupos[d] for d in rnd.choices(dias, k=len(dias))])
        muestras.append(spearman(pre[idx], rea[idx]))
    muestras.sort()
    lo, hi = muestras[int(0.05 * ITER)], muestras[int(0.95 * ITER)]
    por_moneda = {s: (len(g), spearman(g["predicho"].to_numpy(), g["real"].to_numpy())) for s, g in df.groupby("simbolo")}
    positivas = sum(r > 0 for _n, r in por_moneda.values())
    acierto = float(((df["predicho"] > 0) == (df["real"] > 0)).mean())
    print(f"predicciones: {len(df)} en {len(dias)} dias, de {df['simbolo'].nunique()} monedas")
    print(f"Spearman del conjunto: {total:+.4f} (IC 90 %: {lo:+.4f} a {hi:+.4f})")
    for s, (n, r) in sorted(por_moneda.items()):
        print(f"  {s:10} {n:4} predicciones  Spearman {r:+.4f}")
    print(f"monedas con correlacion positiva: {positivas} de {len(por_moneda)}")
    print(f"informativo: acierta la direccion el {100 * acierto:.1f} % de las veces "
          f"(sube de verdad el {100 * float((df['real'] > 0).mean()):.1f} %)")
    pasa = lo > 0 and positivas >= MIN_MONEDAS
    print(f"VEREDICTO paso 1: {'PASA (el paso 2, con su criterio, despues)' if pasa else 'NO PASA: se cierra el tema'}")
    (SALIDA / "veredicto.json").write_text(json.dumps({
        "predicciones": len(df), "dias": len(dias), "spearman": total, "ic90": [lo, hi],
        "por_moneda": {s: {"n": n, "spearman": r} for s, (n, r) in por_moneda.items()},
        "monedas_positivas": positivas, "acierto_direccion": acierto, "pasa": pasa}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    if orden == "predecir":
        predecir(int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None)
    elif orden == "juzgar":
        raise SystemExit(juzgar())
    else:
        print(__doc__)
        raise SystemExit(2)
