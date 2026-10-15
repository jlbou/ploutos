#!/usr/bin/env bash
#
# Ploutos - un fichero de swap de 1 GB en el VPS (decision 2 del propietario del 23/09/2026).
#
#   sudo bash /opt/ploutos/deploy/swap.sh
#
# Idempotente. El VPS tiene 2 GB de RAM y NINGUN swap; una llamada a Claude ocupa
# 400-500 MB. Sin swap, un pico de memoria hace que el kernel mate un proceso. El
# swap no es para usarlo: es el colchon para que un pico no mate nada. Por eso
# `vm.swappiness=10`: el kernel solo lo toca cuando de verdad le falta memoria.

set -euo pipefail

SWAPFILE="/swapfile"
SIZE_MB=1024

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "hay que ejecutarlo como root (usa sudo)"

if swapon --show=NAME --noheadings | grep -qx "${SWAPFILE}"; then
    log "El swap ${SWAPFILE} ya esta activo"
else
    if [[ ! -f "${SWAPFILE}" ]]; then
        log "Creando ${SWAPFILE} de ${SIZE_MB} MB"
        # dd y no fallocate: en algunos sistemas de ficheros fallocate deja
        # huecos que swapon rechaza.
        dd if=/dev/zero of="${SWAPFILE}" bs=1M count="${SIZE_MB}" status=none
        chmod 600 "${SWAPFILE}"
        mkswap "${SWAPFILE}" >/dev/null
    fi
    swapon "${SWAPFILE}"
    log "Swap activado"
fi

grep -qE "^${SWAPFILE}\s" /etc/fstab || echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
echo "vm.swappiness=10" > /etc/sysctl.d/90-ploutos-swap.conf
sysctl -q -p /etc/sysctl.d/90-ploutos-swap.conf

free -m
