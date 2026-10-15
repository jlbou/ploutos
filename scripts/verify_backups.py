"""Comprueba que las copias de seguridad bajadas del VPS se pueden restaurar.

Lo llama `deploy/fetch-backup.sh` despues de bajarlas. Una copia que no se puede
abrir no es una copia: comprobarlo aqui, y no el dia que haga falta restaurarla.

    python scripts/verify_backups.py var/backups                      # todas las del directorio
    python scripts/verify_backups.py var/backups a.db.gz b.db.gz      # solo esas (las recien bajadas)
    ... | python scripts/verify_backups.py --a-bajar var/backups      # que copias del VPS faltan aqui
    python scripts/verify_backups.py --limpiar var/backups            # 14 dias todas; hasta 8 semanas, 1/semana

Exit 0 = todas restaurables. Exit 1 = alguna no (se dice cual).

CUANTAS SE GUARDAN EN EL PORTATIL (el propietario, 28/09/2026): 8 semanas. Desde el 07/10/2026 (el propietario, opcion B): los ultimos
14 dias, todas; de ahi a 8 semanas, una por semana. Antes no se borraba ninguna y la carpeta
crecia sin fin (106 MB el 27/09, GB en unos meses). Solo se borran las copias de la noche con su fecha en el
nombre (`<familia>-AAAAMMDDTHHMMSSZ.db.gz`); la mas reciente de cada base se guarda siempre, tenga la edad
que tenga, y lo que no sigue ese patron (la de cierre de la fase 2, las de antes de una correccion) no se toca.

SOLO LAS NUEVAS (27/09/2026). `fetch-backup.sh` bajaba TODAS las copias del VPS cada domingo (unas 14 por
base, 14 dias de retencion) y cada copia de la base principal pesa mas que la anterior (29 MB el 27/09):
en unos meses, cientos de MB a la semana, casi todo repetido. Ahora recibe la lista del VPS ("tamanyo
nombre" por linea), baja solo las que faltan o no miden lo mismo (una bajada a medias) y verifica esas.

POR QUE ES UN SCRIPT APARTE (22/09/2026). Antes era un trozo de Python dentro de
`fetch-backup.sh`, sin tests, y tenia dos fallos que salieron en el primer
simulacro de restauracion:
1. Contaba las filas de `candles` en TODAS las copias. La base del bucle de
   papel no tiene esa tabla, asi que su copia salia como "NO restaurable"
   aunque estuviera perfecta.
2. Si la comprobacion fallaba, no cerraba la conexion, y en Windows no se puede
   borrar un fichero abierto: el script reventaba con un PermissionError.
La tarea semanal de Windows habria fallado todas las semanas desde la primera
copia de la base de papel, y las copias fuera del VPS habrian dejado de existir.
"""

from __future__ import annotations

import gzip
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Que tabla cuenta cada familia de copias. Si aparece una familia nueva sin
# entrada aqui, se dice en vez de adivinar.
TABLA_POR_FAMILIA = {
    "ploutos-paper-": ("paper_equity", "velas de papel"),
    "ploutos-news-": ("news_anuncios", "anuncios"),
    "ploutos-control-": ("control_comandos", "comandos"),
    "ploutos-exec-": ("exec_journal", "peticiones a OKX"),
    "ploutos-medios-": ("medios_titulares", "titulares de medios"),
    "ploutos-embudo-": ("casos", "casos del embudo de noticias"),
    "ploutos-": ("candles", "velas"),
}


def familia(nombre: str) -> tuple[str, str] | None:
    # La mas especifica primero: "ploutos-paper-" empieza tambien por "ploutos-".
    for prefijo in sorted(TABLA_POR_FAMILIA, key=len, reverse=True):
        if nombre.startswith(prefijo):
            return TABLA_POR_FAMILIA[prefijo]
    return None


def verificar(gz: Path) -> tuple[bool, str]:
    """(restaurable, detalle). Nunca lanza."""
    tabla = familia(gz.name)
    if tabla is None:
        return False, "familia de copia desconocida: no se sabe que comprobar"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / gz.stem
        try:
            with gzip.open(gz, "rb") as src, open(db, "wb") as dst:
                shutil.copyfileobj(src, dst)
            with closing(sqlite3.connect(db)) as conn:
                integridad = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integridad != "ok":
                    return False, f"integrity_check: {integridad}"
                filas = conn.execute(f"SELECT COUNT(*) FROM {tabla[0]}").fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - cualquier fallo = no restaurable
            return False, f"{type(exc).__name__}: {exc}"
    return True, f"{filas} {tabla[1]}"


def a_bajar(listado: str, directorio: Path) -> list[str]:
    """Las copias del VPS que faltan aqui o no miden lo mismo. `listado`: "tamanyo nombre" por linea."""
    out = []
    for linea in listado.splitlines():
        partes = linea.strip().split(maxsplit=1)
        if len(partes) != 2 or not partes[0].isdigit():
            continue
        tam, nombre = int(partes[0]), Path(partes[1]).name     # solo el nombre: nada fuera del directorio
        if not nombre.endswith(".db.gz"):
            continue
        local = directorio / nombre
        if not local.is_file() or local.stat().st_size != tam:
            out.append(nombre)
    return sorted(out)


SEMANAS_EN_EL_PORTATIL = 8
# el propietario, 07/10/2026 (opcion B): las de los ultimos 14 dias, TODAS; de ahi a 8 semanas, UNA por semana (la mas reciente
# de cada semana ISO). Con 8 semanas de todas, la base principal (~85 MB comprimida, y creciendo) pasaba de 5 GB; asi,
# ~1,8 GB y se puede volver igual de atras. El VPS guarda 14 dias: las que se borran aqui ya no se vuelven a bajar.
DIAS_TODAS = 14
_DE_LA_NOCHE = re.compile(r"^(?P<familia>.+)-(?P<fecha>\d{8}T\d{6})Z\.db\.gz$")


def a_borrar(nombres: list[str], ahora: datetime, semanas: int = SEMANAS_EN_EL_PORTATIL,
             dias_todas: int = DIAS_TODAS) -> list[str]:
    """Las copias de la noche que sobran: las de mas de `semanas`, y entre `dias_todas` y `semanas` todas menos la
    mas reciente de cada semana. La mas reciente de cada base, nunca."""
    por_familia: dict[str, list[tuple[datetime, str]]] = {}
    for nombre in nombres:
        m = _DE_LA_NOCHE.match(nombre)
        if m is None:
            continue                                # no es una copia de la noche: no se toca
        fecha = datetime.strptime(m["fecha"], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        por_familia.setdefault(m["familia"], []).append((fecha, nombre))
    limite = ahora - timedelta(weeks=semanas)
    todas_desde = ahora - timedelta(days=dias_todas)
    borrar: list[str] = []
    for copias in por_familia.values():
        copias.sort()
        # Una semana ya tiene copia si hay alguna mas nueva de esa semana guardada (la mas reciente de la base o una
        # de los ultimos 14 dias incluidas): asi la semana que cruza el limite de los 14 dias no guarda dos.
        con_copia: set[tuple[int, int]] = {copias[-1][0].isocalendar()[:2]}
        for fecha, n in reversed(copias[:-1]):      # de la mas nueva a la mas vieja; la mas reciente, nunca
            semana = fecha.isocalendar()[:2]
            if fecha < limite:
                borrar.append(n)
            elif fecha >= todas_desde:
                con_copia.add(semana)
            elif semana in con_copia:
                borrar.append(n)
            else:
                con_copia.add(semana)
    return sorted(borrar)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--limpiar":
        directorio = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("var/backups")
        viejas = a_borrar([p.name for p in directorio.glob("*.db.gz")], datetime.now(UTC))
        for nombre in viejas:
            (directorio / nombre).unlink()
            print(f"    borrada: {nombre}")
        print(f"    {len(viejas)} copia(s) borrada(s) ({DIAS_TODAS} dias todas; hasta {SEMANAS_EN_EL_PORTATIL} semanas,"
              " una por semana)")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--a-bajar":
        directorio = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("var/backups")
        for nombre in a_bajar(sys.stdin.read(), directorio):
            print(nombre)
        return 0
    directorio = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("var/backups")
    nombres = sys.argv[2:]
    copias = sorted(directorio / n for n in nombres) if nombres else sorted(directorio.glob("*.db.gz"))
    if not copias:
        print("    no hay copias locales")
        return 0
    malas = 0
    for gz in copias:
        ok, detalle = verificar(gz)
        tam = gz.stat().st_size / 1024
        print(f"    {'OK ' if ok else 'MAL'}   {gz.name}  {tam:.0f} KB  {detalle}")
        malas += not ok
    print()
    if malas:
        print(f"    {malas} copia(s) NO se pueden restaurar")
        return 1
    print(f"    {len(copias)} copia(s), todas restaurables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
