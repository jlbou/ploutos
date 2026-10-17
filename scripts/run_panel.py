"""El panel `ploutos-panel` (fase 5; docs/diseno-api-panel.md): SOLO en la red de Tailscale.

Decision del propietario del 25/09: el panel se ve solo por Tailscale; desde Internet no existe. Por eso aqui
NO se escucha en todas las interfaces: se pide a Tailscale la IP de ESTA maquina en su red (100.x.y.z)
y se escucha solo ahi. Si no la hay (Tailscale parado o sin autorizar), el panel NO arranca: preferible
a abrirlo por error en la IP publica. El cortafuegos del VPS, ademas, solo deja pasar el puerto del
panel por la interfaz de Tailscale (dos cierres, no uno).

    .venv/bin/python scripts/run_panel.py                 # el servicio
    .venv/bin/python scripts/run_panel.py --host 127.0.0.1   # a mano, para probar en la propia maquina
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PUERTO = 8765
# La red que reparte Tailscale (CGNAT, 100.64.0.0/10): una IP de aqui no es alcanzable desde Internet.
RED_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


class SinTailscale(Exception):
    pass


def ip_de_tailscale(_run=subprocess.run) -> str:
    try:
        r = _run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SinTailscale(f"no se pudo preguntar a Tailscale: {exc}") from None
    ip = (r.stdout or "").strip().splitlines()[0].strip() if r.returncode == 0 and r.stdout.strip() else ""
    return comprobar(ip)


def comprobar(host: str) -> str:
    """Solo la IP de Tailscale o la de la propia maquina (para probar). Nunca todas ni una publica."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise SinTailscale(f"{host!r} no es una IP") from None
    if ip.is_loopback or ip in RED_TAILSCALE:
        return host
    raise SinTailscale(f"{host} no es de la red de Tailscale ni de la propia maquina: el panel no se abre ahi")


def hosts_permitidos(ip: str, puerto: int, _run=subprocess.run) -> set[str]:
    """Los valores de la cabecera Host con los que se entra al panel (api/guardia.py, hueco S5): su IP y, si
    Tailscale lo da, su nombre de MagicDNS entero y el corto. Se preguntan al arrancar: nada escrito en el
    repositorio (es publico). En la propia maquina, la IP y `localhost`."""
    hosts = {f"{ip}:{puerto}"}
    if ipaddress.ip_address(ip).is_loopback:
        return hosts | {f"localhost:{puerto}"}
    try:
        r = _run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
        nombre = ((json.loads(r.stdout or "{}").get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return hosts
    if nombre.endswith(".ts.net"):
        hosts |= {f"{nombre}:{puerto}", f"{nombre.split('.')[0]}:{puerto}"}
    return hosts


def rutas(var: Path) -> dict[str, Path]:
    return {"principal": var / "ploutos.db", "baseline": var / "ploutos-paper.db", "ai": var / "ploutos-paper-ai.db",
            "noticias": var / "ploutos-news.db", "control": var / "ploutos-control.db",
            "ejecutor": var / "ploutos-exec.db", "papel_l": var / "papel-l",
            # 10/10: SOLO para ver si el servicio de medios lee (api/foto.py); los titulares no (test_medios).
            "medios": var / "ploutos-medios.db"}


def main() -> int:
    ap = argparse.ArgumentParser(description="El panel, solo por Tailscale")
    ap.add_argument("--host", help="por defecto, la IP de Tailscale de esta maquina")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--var", default=str(REPO / "var"))
    args = ap.parse_args()
    try:
        host = comprobar(args.host) if args.host else ip_de_tailscale()
    except SinTailscale as exc:
        print(f"el panel no arranca: {exc}", file=sys.stderr)
        return 1

    import uvicorn

    from api.app import crear_app
    from core.config import load_settings
    app = crear_app(load_settings(), rutas(Path(args.var)), hosts=hosts_permitidos(host, args.puerto))
    uvicorn.run(app, host=host, port=args.puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
