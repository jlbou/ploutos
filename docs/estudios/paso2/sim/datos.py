"""Los datos del paso 2: velas diarias de Bitstamp en euros (V3), las dos monedas en las mismas fechas. Un dia que falta
detiene todo (no se rellena)."""
from __future__ import annotations

import json
from pathlib import Path

DIA = 86_400
FICHEROS = {"BTC": "bitstamp-btceur.json", "ETH": "bitstamp-etheur.json"}


def cargar(directorio: Path) -> dict[str, dict[str, list]]:
    crudo = {m: {int(v[0]): v for v in json.loads((directorio / f).read_text(encoding="utf-8"))} for m, f in FICHEROS.items()}
    comunes = sorted(set.intersection(*(set(x) for x in crudo.values())))
    desde, hasta = comunes[0], comunes[-1]
    for m, x in crudo.items():
        dentro = [t for t in x if desde <= t <= hasta]
        if len(dentro) != (hasta - desde) // DIA + 1:
            raise ValueError(f"hueco en {m}: {len(dentro)} dias de {(hasta - desde) // DIA + 1}")
    return {m: {"t": comunes, **{k: [float(crudo[m][t][j]) for t in comunes] for j, k in enumerate("ohlc", start=1)}}
            for m in FICHEROS}
