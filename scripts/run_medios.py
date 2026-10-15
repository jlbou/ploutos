"""El servicio de medios EN SOMBRA `ploutos-medios` (docs/diseno-medios-sombra.md; decision del propietario del 07/10/2026).

Cada 10 min lee los RSS de los medios (`data/medios/rss.py`) y guarda los titulares nuevos en su base
(`var/ploutos-medios.db`). Nada mas:
- **no decide nada**: ninguna cartera, ni el ejecutor, ni la IA leen esta base (test de arquitectura);
- **no manda nada por Telegram** (en sombra no se avisa; los titulares son texto no confiable);
- late a Healthchecks si la mitad de las fuentes o mas se leyeron bien, y solo si existe `HEALTHCHECK_MEDIOS`.

    .venv/bin/python scripts/run_medios.py              # el servicio
    .venv/bin/python scripts/run_medios.py --una-vez    # una pasada y sale
    .venv/bin/python scripts/run_medios.py --status     # por fuente, y las flags en sombra activas
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import load_settings  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from data.medios import rss  # noqa: E402
from data.medios import store as db  # noqa: E402
from features.news import bases_de, flags  # noqa: E402
from notify.latido import Latido  # noqa: E402

PASADA_S = 600
log = logging.getLogger("ploutos.medios")
_parar = False


def _senyal(signum, _frame) -> None:
    global _parar
    _parar = True
    log.info("senyal %s: parando al acabar la pasada", signum)


class MediosRunner:
    SERVICIO = "ploutos-medios"
    LATIDO = "healthcheck_medios"

    def __init__(self, ruta_db: Path | str, *, fuentes: tuple[rss.Fuente, ...] = rss.FUENTES,
                 secretos: Secrets | None = None, _leer: Any = rss.leer, _latido: Latido | None = None) -> None:
        self.fuentes = fuentes
        self.calidad = {f.nombre: f.calidad for f in fuentes}
        self.conn = db.conectar(ruta_db)
        db.migrar(self.conn)
        self._leer = _leer
        if _latido is None:
            secretos = secretos or Secrets()
            _latido = Latido(secretos.valor(self.LATIDO), self.SERVICIO)
        self._latido = _latido

    def pasada(self, ahora_ms: int | None = None) -> dict[str, Any]:
        """Una vuelta por todas las fuentes. NUNCA lanza."""
        ahora_ms = ahora_ms if ahora_ms is not None else int(time.time() * 1000)
        try:
            lecturas = self._leer(self.fuentes)
            buenas = nuevos = 0
            for lec in lecturas:
                n = db.guardar(self.conn, lec.titulares, self.calidad.get(lec.fuente, "?"), ahora_ms)
                ok = lec.error is None
                db.registrar_lectura(self.conn, ahora_ms, lec.fuente, ok, len(lec.titulares), n, lec.error)
                buenas += ok
                nuevos += n
            sano = buenas * 2 >= len(self.fuentes)
            if sano:
                self._latido.enviar()
            return {"ok": sano, "fuentes_bien": buenas, "fuentes": len(self.fuentes), "nuevos": nuevos}
        except Exception as exc:  # noqa: BLE001 - la base, un bug: se apunta y la siguiente vuelta lo reintenta
            log.exception("la pasada de medios fallo")
            return {"ok": False, "fuentes_bien": 0, "fuentes": len(self.fuentes), "nuevos": 0,
                    "error": f"{type(exc).__name__}: {exc}"}

    def estado(self, ahora_ms: int, whitelist: list[str] | tuple[str, ...]) -> str:
        def hora(ms: int | None) -> str:
            return "nunca" if ms is None else datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%d/%m %H:%M")
        filas = db.resumen_fuentes(self.conn)
        total = sum(r["titulares"] for r in filas)
        lineas = [f"titulares guardados: {total} de {len(filas)} fuentes (de {len(self.fuentes)})"]
        for r in filas:
            error = f"  ultimo error: {r['ultimo_error']}" if r["ultimo_error"] else ""
            lineas.append(f"  [{r['calidad']}] {r['fuente']:16s} {r['titulares']:5d}  ultima buena {hora(r['ultima_buena'])}"
                          f"{error}")
        activas = [f for f in flags(db.anuncios(self.conn), bases_de(whitelist), duraciones_h=db.DURACIONES_SOMBRA_H)
                   if f.activa(ahora_ms)]
        lineas.append(f"flags EN SOMBRA activas ahora: {len(activas)} (no bloquean nada)")
        for f in activas:
            lineas.append(f"  {f.moneda} {f.tipo} ({f.gravedad}) desde {hora(f.desde_ms)}: {f.anuncio.split(':', 1)[0]}")
        return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Medios de cripto en sombra (solo recoger)")
    ap.add_argument("--db", default=str(REPO / "var" / "ploutos-medios.db"))
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    r = MediosRunner(args.db)
    if args.status:
        print(r.estado(int(time.time() * 1000), load_settings().whitelist))
        return 0
    signal.signal(signal.SIGTERM, _senyal)
    signal.signal(signal.SIGINT, _senyal)
    while True:
        info = r.pasada()
        log.info("pasada: %s", info)
        if args.una_vez:
            return 0 if info["ok"] else 1
        for _ in range(PASADA_S):
            if _parar:
                return 0
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
