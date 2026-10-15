"""Baja la historia diaria (UTC) de BTC/EUR y ETH/EUR: Bitstamp desde 2016 (decision V3 del 15/10/2026) y OKX desde
11/2023 (para comprobarla, V4). APIs publicas, sin claves. Deja JSON en var/estudios/paso2/ (fuera de git).

    .venv/Scripts/python.exe docs/estudios/paso2/bajar_historia.py
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[3] / "var" / "estudios" / "paso2"
UA = {"User-Agent": "Mozilla/5.0"}
DIA = 86_400


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read())


def bitstamp(par: str) -> list[list]:
    """[[t_segundos, open, high, low, close, volume], ...] diarias, desde 2016."""
    out, desde = {}, int(datetime(2016, 1, 1, tzinfo=UTC).timestamp())
    ahora = int(time.time())
    while desde < ahora:
        velas = get(f"https://www.bitstamp.net/api/v2/ohlc/{par}/?step={DIA}&limit=1000&start={desde}")["data"]["ohlc"]
        if not velas:
            break
        for v in velas:
            out[int(v["timestamp"])] = [int(v["timestamp"])] + [float(v[k]) for k in ("open", "high", "low", "close", "volume")]
        nuevo = max(out) + DIA
        if nuevo <= desde:
            break
        desde = nuevo
        time.sleep(0.5)
    hoy = ahora // DIA * DIA
    return [out[t] for t in sorted(out) if t < hoy]          # solo velas cerradas


def okx(inst: str) -> list[list]:
    """Diarias en UTC (`1Dutc`), desde la primera, cerradas."""
    out, despues = {}, ""
    while True:
        url = f"https://eea.okx.com/api/v5/market/history-candles?instId={inst}&bar=1Dutc&limit=100" + (f"&after={despues}" if despues else "")
        datos = get(url)["data"]
        if not datos:
            break
        for c in datos:
            if c[8] == "1":
                out[int(c[0]) // 1000] = [int(c[0]) // 1000] + [float(x) for x in c[1:6]]
        despues = datos[-1][0]
        time.sleep(0.2)
    return [out[t] for t in sorted(out)]


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, fn, arg in (("bitstamp-btceur", bitstamp, "btceur"), ("bitstamp-etheur", bitstamp, "etheur"),
                            ("okx-btceur", okx, "BTC-EUR"), ("okx-etheur", okx, "ETH-EUR")):
        velas = fn(arg)
        (DESTINO / f"{nombre}.json").write_text(json.dumps(velas), encoding="utf-8")
        d = lambda t: datetime.fromtimestamp(t, UTC).date().isoformat()  # noqa: E731
        print(f"{nombre}: {len(velas)} velas, {d(velas[0][0])} - {d(velas[-1][0])}")


if __name__ == "__main__":
    main()
