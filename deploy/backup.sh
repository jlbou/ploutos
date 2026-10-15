#!/usr/bin/env bash
#
# Copia de seguridad de la base de datos (PRD seccion 11).
#
# Usa `VACUUM INTO`, que es la forma correcta de copiar una base SQLite EN USO:
# produce un fichero consistente sin parar la ingesta y sin copiar el WAL a
# medias. Copiar el .db con `cp` mientras el bot escribe da copias corruptas.
#
# Copia DOS bases: la principal (velas, libro, eventos) y la del bucle de
# papel, que vive aparte para no competir por el bloqueo de escritura con
# la ingesta. La de papel guarda las operaciones del criterio de avance de
# la fase 2: perderla seria perder la evidencia.
#
# Lo lanza el temporizador ploutos-backup.timer cada dia a las 03:15 UTC.

set -euo pipefail

DB="${PLOUTOS_DB:-/opt/ploutos/var/ploutos.db}"
PAPER_DB="${PLOUTOS_PAPER_DB:-/opt/ploutos/var/ploutos-paper.db}"
# La cartera de la IA (fase 3, pieza 9). Hasta que se despliegue no existe, y
# `copiar` se la salta sin error.
AI_DB="${PLOUTOS_AI_DB:-/opt/ploutos/var/ploutos-paper-ai.db}"
# Noticias y comandos de Telegram: las flags que el propietario levanto y las pausas no se pueden deducir de
# otro sitio. Hasta que se desplieguen no existen, y `copiar` se las salta.
NEWS_DB="${PLOUTOS_NEWS_DB:-/opt/ploutos/var/ploutos-news.db}"
CONTROL_DB="${PLOUTOS_CONTROL_DB:-/opt/ploutos/var/ploutos-control.db}"
# El ejecutor del demo (fase 4): la foto del saldo, el journal de cada peticion a OKX y el CAPITAL enclavado.
EXEC_DB="${PLOUTOS_EXEC_DB:-/opt/ploutos/var/ploutos-exec.db}"
# Los medios en sombra (07/10): los titulares no se pueden volver a pedir (un RSS solo trae los ultimos).
MEDIOS_DB="${PLOUTOS_MEDIOS_DB:-/opt/ploutos/var/ploutos-medios.db}"
# El embudo de noticias de L (11/10): los casos y cada llamada a la IA no se pueden rehacer.
EMBUDO_DB="${PLOUTOS_EMBUDO_DB:-/opt/ploutos/var/ploutos-embudo.db}"
DEST="${PLOUTOS_BACKUP_DIR:-/var/backups/ploutos}"
KEEP_DAYS="${PLOUTOS_BACKUP_KEEP_DAYS:-14}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

mkdir -p "${DEST}"

# Copia una base y verifica que la copia sirve. Devuelve 1 si sale corrupta.
# La verificacion no es opcional: una copia que no se puede restaurar no es
# una copia, es un fichero que da tranquilidad falsa.
copiar() {
    local origen="$1" prefijo="$2" tabla="$3"
    local salida="${DEST}/${prefijo}-${STAMP}.db"

    if [[ ! -f "${origen}" ]]; then
        log "no existe ${origen}; nada que copiar"
        return 0
    fi

    log "copiando ${origen} -> ${salida}"
    # 12/10/2026: la del embudo salio VACIA (0 bytes) y se dio por buena. El embudo escribia a la misma hora, el
    # VACUUM fallo por el bloqueo y nadie lo miro: dentro de una funcion llamada con `||`, bash ignora `set -e`. Y el
    # integrity_check de despues CREO un fichero vacio, que "esta integro". Ahora: espera al bloqueo hasta 60 s, mira
    # el codigo de salida, y una copia vacia o sin su tabla es un FALLO.
    rm -f "${salida}"
    if ! sqlite3 -cmd ".timeout 60000" "${origen}" "VACUUM INTO '${salida}'"; then
        log "NO SE PUDO COPIAR ${origen} (VACUUM INTO fallo)"
        rm -f "${salida}"
        return 1
    fi
    if [[ ! -s "${salida}" ]]; then
        log "LA COPIA ESTA VACIA: ${salida}"
        rm -f "${salida}"
        return 1
    fi

    local check
    check="$(sqlite3 "${salida}" 'PRAGMA integrity_check;' 2>&1 || echo 'FALLO')"
    if [[ "${check}" != "ok" ]]; then
        log "LA COPIA ESTA CORRUPTA: ${check}"
        rm -f "${salida}"
        return 1
    fi

    local filas size
    filas="$(sqlite3 "${salida}" "SELECT COUNT(*) FROM ${tabla};" 2>/dev/null || echo '?')"
    if ! [[ "${filas}" =~ ^[0-9]+$ ]]; then
        log "LA COPIA NO TIENE LA TABLA ${tabla}: ${salida}"
        rm -f "${salida}"
        return 1
    fi
    size="$(du -h "${salida}" | cut -f1)"
    log "copia correcta: ${size}, ${filas} filas en ${tabla}"

    gzip -f "${salida}"
    log "comprimida: ${salida}.gz ($(du -h "${salida}.gz" | cut -f1))"
    return 0
}

fallos=0
copiar "${DB}"       "ploutos"       "candles"      || fallos=$((fallos + 1))
copiar "${PAPER_DB}" "ploutos-paper" "paper_trades" || fallos=$((fallos + 1))
copiar "${AI_DB}"    "ploutos-paper-ai" "paper_trades" || fallos=$((fallos + 1))
copiar "${NEWS_DB}"  "ploutos-news"  "news_anuncios"   || fallos=$((fallos + 1))
copiar "${CONTROL_DB}" "ploutos-control" "control_comandos" || fallos=$((fallos + 1))
copiar "${EXEC_DB}"  "ploutos-exec"  "exec_journal"  || fallos=$((fallos + 1))
copiar "${MEDIOS_DB}" "ploutos-medios" "medios_titulares" || fallos=$((fallos + 1))
copiar "${EMBUDO_DB}" "ploutos-embudo" "casos" || fallos=$((fallos + 1))

# Rotacion de las dos familias. El patron lleva el "2" del anyo: con "ploutos-*"
# la familia "ploutos" contaba tambien las de "ploutos-paper-" (el log decia 6
# guardadas con 4). Borrar no borraba de mas (las dos usan KEEP_DAYS), pero el
# recuento mentia. Revision del 23/09/2026.
for prefijo in ploutos ploutos-paper ploutos-paper-ai ploutos-news ploutos-control ploutos-exec ploutos-medios ploutos-embudo; do
    borradas="$(find "${DEST}" -name "${prefijo}-2*.db.gz" -mtime "+${KEEP_DAYS}" -print -delete | wc -l)"
    total="$(find "${DEST}" -name "${prefijo}-2*.db.gz" | wc -l)"
    log "${prefijo}: ${borradas} copias viejas borradas, ${total} guardadas"
done

# Latido al vigilante externo (decision del propietario del 24/09/2026): bien -> latido;
# con fallos -> /fail, que avisa YA sin esperar a que falte. La URL se lee con grep
# (sin distinguir mayusculas: Python tampoco las distingue en .env):
# NUNCA `source .env` (bash lo ejecutaria como shell). Nunca se imprime.
ENV_FILE="${PLOUTOS_ENV_FILE:-/opt/ploutos/.env}"
HC_URL="$(grep -iE '^HEALTHCHECK_COPIA=' "${ENV_FILE}" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r"' || true)"
if [[ -n "${HC_URL}" ]]; then
    sufijo=""
    (( fallos > 0 )) && sufijo="/fail"
    curl -fsS -m 10 --retry 3 -o /dev/null "${HC_URL}${sufijo}" 2>/dev/null \
        || log "aviso: no se pudo avisar al vigilante externo"
fi

if (( fallos > 0 )); then
    log "TERMINADO CON ${fallos} FALLO(S)"
    exit 1
fi

# AVISO: esto deja las copias EN EL PROPIO SERVIDOR. El PRD pide que salgan
# fuera del VPS. Eso lo hace `deploy/fetch-backup.sh` desde el portatil, que
# es lo que las convierte en una copia de verdad: si el proveedor del VPS desaparece,
# una copia que vivia en el proveedor del VPS desaparece con el.
