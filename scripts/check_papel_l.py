"""El juez del papel de L (`docs/diseno-papel-l.md`, criterio aprobado por el propietario el 10/10/2026 antes de arrancar).

Sale con 0 (cumplido), 1 (FALLA) o 2 (aun no), como los demas jueces de cada noche:
- antes del 13/10/2026 (el primer dia entero): 2, nada que juzgar;
- FALLA si la ultima pasada tiene mas de 26 h (el papel no corre), si faltan velas de 4 h en el periodo (el papel no
  vale y se dice) o si la caida desde su maximo pasa del 25 % (corte anticipado: L descartada);
- al acabar (11/01/2027): CUMPLIDO si no pierde (>= 0) y su caida maxima <= 2/3 de la de BTC mantenido; si no, FALLA;
- mientras tanto: 2 ("en curso").
La caida vela a vela (cierre de cada vela de 4 h, el propietario 15/10, revision 6) sale como INFORMACION: no cambia el codigo de
salida; el criterio, fijado antes de arrancar, sigue con los cierres diarios.

    .venv/bin/python scripts/check_papel_l.py [--dir var/papel-l] [--ahora-ms N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from papel_l import DIA, FIN, INICIO, ms  # noqa: E402

CORTE = 0.25
FRESCURA_MS = 26 * 3600_000


def juzgar(resultado: dict | None, meta: dict | None, ahora_ms: int) -> tuple[int, list[str]]:
    if ahora_ms < ms(INICIO) + DIA:
        return 2, [f"el papel de L empieza el {INICIO}: aun no hay nada que juzgar"]
    if resultado is None or meta is None:
        return 1, ["FALLA: el papel de L no ha corrido nunca (no hay ultima pasada)"]
    lineas, falla = [], False
    horas = (ahora_ms - int(meta["pasada_ms"])) / 3600_000
    if ahora_ms - int(meta["pasada_ms"]) > FRESCURA_MS:
        lineas.append(f"FALLA: la ultima pasada fue hace {horas:.0f} h (el papel no corre)")
        falla = True
    if meta.get("huecos"):
        lineas.append(f"FALLA: faltan velas de 4 h en el periodo: {meta['huecos']} (el papel no vale asi)")
        falla = True
    met, btc = resultado["metricas"], resultado["btc"]
    lineas.append(f"L: 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), caida max "
                  f"{100 * met['caida_max']:.1f} %, {len(resultado['ops'])} operaciones cerradas, "
                  f"{len(resultado['abiertas'])} abiertas; BTC {100 * btc['rendimiento']:+.1f} %, caida "
                  f"{100 * btc['caida_max']:.1f} %")
    if "caida_max_velas" in met:
        lineas.append(f"  (informacion) caida vela a vela: L {100 * met['caida_max_velas']:.1f} %, BTC "
                      f"{100 * btc.get('caida_max_velas', float('nan')):.1f} %"
                      + ("; pasaria del corte si se midiera asi" if met["caida_max_velas"] > CORTE else ""))
    if met["caida_max"] > CORTE:
        lineas.append(f"FALLA: corte anticipado, la caida ({100 * met['caida_max']:.1f} %) pasa del "
                      f"{100 * CORTE:.0f} %: L se da por descartada")
        return 1, lineas
    if falla:
        return 1, lineas
    if ahora_ms >= ms(FIN):
        gana = met["rendimiento"] >= 0
        cae = met["caida_max"] <= 2 / 3 * btc["caida_max"]
        lineas.append(f"  {'si' if gana else 'NO'}  no pierde (>= 0)")
        lineas.append(f"  {'si' if cae else 'NO'}  caida <= 2/3 de la de BTC ({200 / 3 * btc['caida_max']:.1f} %)")
        if gana and cae:
            lineas.append("RESULTADO: CUMPLIDO (decide el propietario)")
            return 0, lineas
        lineas.append("RESULTADO: FALLA, L no pasa el papel")
        return 1, lineas
    lineas.append(f"RESULTADO: en curso hasta el {FIN}. Aun no.")
    return 2, lineas


def main() -> int:
    ap = argparse.ArgumentParser(description="El juez del papel de L")
    ap.add_argument("--dir", default=str(REPO / "var" / "papel-l"))
    ap.add_argument("--ahora-ms", type=int, default=None)
    args = ap.parse_args()
    d = Path(args.dir)
    leer = lambda n: json.loads((d / n).read_text(encoding="utf-8")) if (d / n).exists() else None  # noqa: E731
    codigo, lineas = juzgar(leer("ultimo.json"), leer("meta.json"), args.ahora_ms or int(time.time() * 1000))
    print("Papel de L (3 meses, desde el 12/10/2026)")
    for linea in lineas:
        print(linea)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
