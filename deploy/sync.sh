#!/usr/bin/env bash
#
# Copia el proyecto del portatil al VPS (PRD seccion 11: despliegue reproducible).
#
#   bash deploy/sync.sh ploutos
#
# NO copia:
#   .env   -> regla 19, los secretos se crean en el servidor a mano
#   var/   -> la base de datos del servidor es la buena, no la de pruebas
#   .venv/ -> se crea alli con las dependencias de Linux
#   privado/, CLAUDE.local.md -> lo personal del propietario no sale del portatil
#   graphify-out/, .ruff_cache/ -> se regeneran, no hacen falta en el servidor

set -euo pipefail

TARGET="${1:-}"
[[ -n "${TARGET}" ]] || { echo "uso: bash deploy/sync.sh <host-ssh>" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=deploy/_ssh.sh
source "${REPO_DIR}/deploy/_ssh.sh"

REMOTE_DIR="/opt/ploutos"

echo "==> Sincronizando ${REPO_DIR} -> ${TARGET}:${REMOTE_DIR}"

"${SSH_BIN}" "${TARGET}" "mkdir -p ${REMOTE_DIR}"

if command -v rsync >/dev/null 2>&1; then
    rsync -az --delete --info=stats1 -e "${SSH_BIN}" \
        --exclude '.env' \
        --exclude '.venv/' \
        --exclude 'var/' \
        --exclude '.git/' \
        --exclude '__pycache__/' \
        --exclude '.pytest_cache/' \
        --exclude '.hypothesis/' \
        --exclude '*.egg-info/' \
        --exclude '*.db' \
        --exclude '*.db-wal' \
        --exclude '*.db-shm' \
        --exclude 'privado/' \
        --exclude 'CLAUDE.local.md' \
        --exclude 'graphify-out/' \
        --exclude '.ruff_cache/' \
        "${REPO_DIR}/" "${TARGET}:${REMOTE_DIR}/"
else
    # Sin rsync (habitual en Windows): tar por la tuberia hace lo mismo.
    # No borra ficheros que ya no existan, pero para desplegar basta.
    echo "    (sin rsync: usando tar sobre ssh)"
    tar czf - -C "${REPO_DIR}" \
        --exclude='.env' \
        --exclude='.venv' \
        --exclude='var' \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.hypothesis' \
        --exclude='*.egg-info' \
        --exclude='*.db' \
        --exclude='*.db-wal' \
        --exclude='*.db-shm' \
        --exclude='privado' \
        --exclude='CLAUDE.local.md' \
        --exclude='graphify-out' \
        --exclude='.ruff_cache' \
        . | "${SSH_BIN}" "${TARGET}" "tar xzf - -C ${REMOTE_DIR}"
fi

# El .env del servidor no se toca nunca, pero si existe hay que dejarlo con
# sus permisos (regla 19) por si el chown de abajo lo ha aflojado.
"${SSH_BIN}" "${TARGET}" "
    chown -R ploutos:ploutos ${REMOTE_DIR}
    chmod +x ${REMOTE_DIR}/deploy/*.sh
    [ -f ${REMOTE_DIR}/.env ] && chmod 600 ${REMOTE_DIR}/.env
    true
"

echo "==> Listo. En el servidor:"
echo "      sudo bash ${REMOTE_DIR}/deploy/install.sh"
echo "      systemctl restart ploutos-ingest"
