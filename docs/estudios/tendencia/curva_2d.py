"""La curva diaria de equity de 2 + D (objetivo taker), para compararla con F y H con las mismas metricas.

    python curva_2d.py > curva-2d.json
    python curva_2d.py var/estudios/exploracion-ampliada.db > curva-2d-ampliada.json   # la segunda tanda (10/10)
    python curva_2d.py var/estudios/anyo-usdc-calentado.db --since 2025-09-01 > curva-2d-usdc.json   # su anyo USDC

Repite la medicion del 08/10 (`segunda-ronda/medir_cd.py --idea 2+D --objetivo taker`) y guarda el equity del libro de
papel en cada vela (`PaperLedger.history`); el del dia es el de la vela de las 20:00. Nada nuevo: es la misma medicion.
"""
import contextlib
import io
import json
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import portfolio.paper as paper_mod  # noqa: E402

libros = []
init_original = paper_mod.PaperLedger.__init__


def init(self, *a, **k):
    init_original(self, *a, **k)
    libros.append(self)


paper_mod.PaperLedger.__init__ = init
BASE = str(REPO / (sys.argv[1] if len(sys.argv) > 1 else "var/estudios/exploracion.db"))
sys.argv = ["medir_cd.py", BASE, "2+D-taker", "--objetivo", "taker", "--idea", "2+D"] + sys.argv[2:]
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    runpy.run_path(str(REPO / "docs/estudios/segunda-ronda/medir_cd.py"), run_name="__main__")
res = json.loads(salida.getvalue())
DIA = 86_400_000
curva = [(int(t) - int(t) % DIA, float(e)) for t, e in libros[0].history if int(t) % DIA == 20 * 3600_000]
print(json.dumps({"todo": res["todo"], "equity": res["equity"], "drawdown": res["drawdown"], "curva": curva}))
