"""La comprobacion de las copias de seguridad bajadas (`scripts/verify_backups.py`).

BUG REAL (22/09/2026), salido en el primer simulacro de restauracion: la copia
de la base de papel salia como "NO restaurable" porque se buscaba la tabla
`candles` en todas, y despues el script reventaba en Windows por no cerrar la
conexion. La tarea semanal que saca las copias del VPS habria fallado siempre.
"""

from __future__ import annotations

import gzip
import importlib.util
import sqlite3
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_backups.py"
_spec = importlib.util.spec_from_file_location("verify_backups", SCRIPT)
vb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vb)


def copia(dir_: Path, nombre: str, sql: str) -> Path:
    db = dir_ / nombre.removesuffix(".gz")
    with sqlite3.connect(db) as c:
        c.executescript(sql)
    c.close()
    gz = dir_ / nombre
    gz.write_bytes(gzip.compress(db.read_bytes()))
    db.unlink()
    return gz


PRINCIPAL = "CREATE TABLE candles (x); INSERT INTO candles VALUES (1), (2);"
PAPEL = "CREATE TABLE paper_equity (x); INSERT INTO paper_equity VALUES (1);"


def test_la_copia_de_papel_es_restaurable(tmp_path):
    ok, detalle = vb.verificar(copia(tmp_path, "ploutos-paper-20260922T224929Z.db.gz", PAPEL))
    assert ok, detalle
    assert "1 velas de papel" in detalle


def test_la_copia_principal_cuenta_velas(tmp_path):
    ok, detalle = vb.verificar(copia(tmp_path, "ploutos-20260922T224929Z.db.gz", PRINCIPAL))
    assert ok and "2 velas" in detalle


def test_una_copia_sin_su_tabla_no_es_restaurable_y_no_revienta(tmp_path):
    """El caso que reventaba: fallo dentro de SQLite. Ahora dice MAL y sigue."""
    ok, detalle = vb.verificar(copia(tmp_path, "ploutos-20260922T000000Z.db.gz", PAPEL))
    assert not ok and "candles" in detalle


def test_un_fichero_que_no_es_gzip_no_revienta(tmp_path):
    malo = tmp_path / "ploutos-20260922T000000Z.db.gz"
    malo.write_bytes(b"esto no es un gzip")
    ok, _ = vb.verificar(malo)
    assert not ok


def test_una_familia_desconocida_se_dice(tmp_path):
    ok, detalle = vb.verificar(copia(tmp_path, "otra-cosa.db.gz", PAPEL))
    assert not ok and "desconocida" in detalle


def test_el_directorio_entero(tmp_path, capsys, monkeypatch):
    copia(tmp_path, "ploutos-20260922T224929Z.db.gz", PRINCIPAL)
    copia(tmp_path, "ploutos-paper-20260922T224929Z.db.gz", PAPEL)
    monkeypatch.setattr("sys.argv", ["verify_backups.py", str(tmp_path)])
    assert vb.main() == 0
    assert "2 copia(s), todas restaurables" in capsys.readouterr().out


def test_solo_se_bajan_las_que_faltan_o_no_miden_lo_mismo(tmp_path):
    """27/09: antes se bajaban TODAS las copias del VPS cada domingo."""
    ya = copia(tmp_path, "ploutos-20260926T032001Z.db.gz", PRINCIPAL)
    medias = tmp_path / "ploutos-news-20260927T031755Z.db.gz"
    medias.write_bytes(b"a medias")                                  # una bajada que se corto
    listado = "\n".join([
        f"{ya.stat().st_size} ploutos-20260926T032001Z.db.gz",       # igual: no
        "9416 ploutos-news-20260927T031755Z.db.gz",                  # mide distinto: si
        "28784000 ploutos-20260927T031755Z.db.gz",                   # no esta: si
        "123 ../../fuera.db.gz",                                     # solo cuenta el nombre
        "4000 ploutos-paper-cierre-fase2.db",                        # no es una copia comprimida
        "basura", "",
    ])
    assert vb.a_bajar(listado, tmp_path) == ["fuera.db.gz", "ploutos-20260927T031755Z.db.gz",
                                              "ploutos-news-20260927T031755Z.db.gz"]


def test_se_verifican_solo_las_nombradas(tmp_path, capsys, monkeypatch):
    copia(tmp_path, "ploutos-20260922T224929Z.db.gz", PRINCIPAL)
    (tmp_path / "ploutos-20260921T000000Z.db.gz").write_bytes(b"rota, pero no se ha bajado ahora")
    monkeypatch.setattr("sys.argv", ["verify_backups.py", str(tmp_path), "ploutos-20260922T224929Z.db.gz"])
    assert vb.main() == 0
    assert "1 copia(s), todas restaurables" in capsys.readouterr().out


def test_la_lista_de_las_que_faltan_por_la_linea_de_ordenes(tmp_path, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("10 ploutos-20260927T031755Z.db.gz\n"))
    monkeypatch.setattr("sys.argv", ["verify_backups.py", "--a-bajar", str(tmp_path)])
    assert vb.main() == 0
    assert capsys.readouterr().out.split() == ["ploutos-20260927T031755Z.db.gz"]


def test_en_el_portatil_se_guardan_8_semanas(tmp_path):
    """el propietario, 28/09: antes no se borraba ninguna. La mas reciente de cada base se guarda siempre, y lo que no
    es una copia de la noche (la de cierre de la fase 2, las de antes de una correccion) no se toca."""
    from datetime import UTC, datetime
    ahora = datetime(2026, 12, 1, tzinfo=UTC)                       # 8 semanas antes: 06/10/2026
    nombres = [
        "ploutos-20260922T224929Z.db.gz",          # vieja: se borra
        "ploutos-20261006T031500Z.db.gz",          # justo dentro: se guarda
        "ploutos-20261130T031500Z.db.gz",
        "ploutos-paper-20260925T031906Z.db.gz",    # vieja: se borra
        "ploutos-paper-20261130T031500Z.db.gz",
        "ploutos-news-20260926T032001Z.db.gz",     # vieja pero la UNICA de su base: se guarda
        "ploutos-paper-cierre-fase2.db",           # no es de la noche: nunca
        "ploutos-paper-antes-correccion-20260928.db",
    ]
    assert vb.a_borrar(nombres, ahora) == ["ploutos-20260922T224929Z.db.gz", "ploutos-paper-20260925T031906Z.db.gz"]


def test_14_dias_todas_y_hasta_8_semanas_una_por_semana():
    """el propietario, 07/10 (opcion B): las de los ultimos 14 dias, todas; de ahi a 8 semanas, la mas reciente de cada semana
    ISO; la semana que cruza el limite de 14 dias no guarda dos."""
    from datetime import UTC, datetime, timedelta
    ahora = datetime(2026, 12, 1, 4, 0, tzinfo=UTC)                 # martes; 14 dias antes: martes 17/11
    nombres = [f"ploutos-{(ahora - timedelta(days=d)):%Y%m%d}T031500Z.db.gz" for d in range(0, 70)]
    borrar = set(vb.a_borrar(nombres, ahora))
    guardadas = sorted(set(nombres) - borrar)
    fechas = [datetime.strptime(n[8:16], "%Y%m%d").replace(tzinfo=UTC) for n in guardadas]
    recientes = [f for f in fechas if f >= ahora - timedelta(days=14)]
    antiguas = [f for f in fechas if f < ahora - timedelta(days=14)]
    assert len(recientes) == 14, "los ultimos 14 dias, todas"
    assert all(f >= ahora - timedelta(weeks=8) for f in antiguas), "nada de mas de 8 semanas"
    semanas = [f.isocalendar()[:2] for f in antiguas]
    assert len(semanas) == len(set(semanas)), "como mucho una por semana"
    assert not set(semanas) & {f.isocalendar()[:2] for f in recientes}, "la semana del limite no guarda dos"
    assert all(f.weekday() == 6 for f in antiguas), "de cada semana, la mas reciente (el domingo)"
    assert len(guardadas) == 14 + len(antiguas) and 5 <= len(antiguas) <= 6


def test_la_mas_reciente_de_una_base_parada_se_guarda_aunque_sea_vieja():
    from datetime import UTC, datetime
    ahora = datetime(2026, 12, 1, tzinfo=UTC)
    nombres = ["ploutos-exec-20261001T031500Z.db.gz", "ploutos-exec-20261002T031500Z.db.gz"]
    assert vb.a_borrar(nombres, ahora) == ["ploutos-exec-20261001T031500Z.db.gz"]


def test_limpiar_borra_de_verdad_y_solo_esas(tmp_path, capsys, monkeypatch):
    for n in ("ploutos-20200101T000000Z.db.gz", "ploutos-20990101T000000Z.db.gz", "ploutos-paper-cierre-fase2.db"):
        (tmp_path / n).write_bytes(b"x")
    monkeypatch.setattr("sys.argv", ["verify_backups.py", "--limpiar", str(tmp_path)])
    assert vb.main() == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ploutos-20990101T000000Z.db.gz", "ploutos-paper-cierre-fase2.db"]
    assert "1 copia(s)" in capsys.readouterr().out
