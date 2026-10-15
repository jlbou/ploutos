#!/usr/bin/env bash
#
# Baja las copias de seguridad del VPS al portatil y COMPRUEBA que se abren.
#
#   bash deploy/fetch-backup.sh ploutos
#
# POR QUE EXISTE: el PRD seccion 11 pide copias "fuera del VPS". Una copia que
# vive en el mismo servidor que la base de datos no es una copia de seguridad:
# si el proveedor desaparece, desaparecen las dos a la vez.
#
# Esto NO se ejecuta solo. Hay que lanzarlo de vez en cuando, o programarlo en
# el Programador de tareas de Windows.
#
# SOLO LAS NUEVAS (27/09/2026): antes bajaba TODAS las copias del VPS cada vez
# (unas 14 por base) y cada copia de la base principal pesa mas que la anterior.
# Ahora baja las que faltan aqui o no miden lo mismo, y verifica esas.

set -euo pipefail

TARGET="${1:-}"
[[ -n "${TARGET}" ]] || { echo "uso: bash deploy/fetch-backup.sh <host-ssh>" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=deploy/_ssh.sh
source "${REPO_DIR}/deploy/_ssh.sh"

LOCAL_DIR="${REPO_DIR}/var/backups"
REMOTE_DIR="/var/backups/ploutos"

mkdir -p "${LOCAL_DIR}"

python_bin="${REPO_DIR}/.venv/Scripts/python.exe"
[[ -x "${python_bin}" ]] || python_bin="${REPO_DIR}/.venv/bin/python"
[[ -x "${python_bin}" ]] || python_bin="python3"
# La logica (que falta y si se puede restaurar) vive en scripts/verify_backups.py,
# con tests. Antes era un trozo de Python aqui dentro, y marcaba la copia de la
# base de papel como "no restaurable" (buscaba la tabla `candles`) y luego
# reventaba en Windows.
verificar="${REPO_DIR}/scripts/verify_backups.py"

# Sin preguntar nunca y sin colgarse (28/09/2026): la pasada del domingo 27/09 empezo y no
# escribio nada mas, ni fallo ni aviso. Si falta la clave en el agente, ssh pide la frase de
# paso a una consola que nadie ve y espera hasta que Windows mata la tarea a los 30 min, sin
# que el script llegue a avisar. Con BatchMode falla al momento y la tarea avisa por Telegram.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

echo "==> Copias en el servidor"
# "tamanyo nombre" por linea (find -printf; el salto de linea lo pone find).
# Si el VPS no responde es un ERROR (la tarea diaria tiene que verlo), no "no hay copias".
if ! listado="$("${SSH_BIN}" "${SSH_OPTS[@]}" "${TARGET}" "find ${REMOTE_DIR} -maxdepth 1 -name '*.db.gz' -printf '%s %f\\n'")"; then
    echo "    ERROR: no se pudo leer la lista de copias del VPS (red o SSH)" >&2
    exit 1
fi
if [[ -z "${listado}" ]]; then
    echo "    No hay copias todavia. El temporizador corre a las 03:15 UTC;"
    echo "    para generar una ahora:  ssh ${TARGET} 'systemctl start ploutos-backup'"
    exit 0
fi
echo "    $(grep -c . <<< "${listado}") en el VPS"

# El Python de Windows escribe CRLF: se quita el retorno de carro de cada nombre.
mapfile -t nuevas < <("${python_bin}" "${verificar}" --a-bajar "${LOCAL_DIR}" <<< "${listado}" | tr -d '\r')
if [[ ${#nuevas[@]} -eq 0 ]]; then
    echo "    ninguna nueva: ya estan todas en ${LOCAL_DIR}"
else
    echo
    echo "==> Bajando ${#nuevas[@]} a ${LOCAL_DIR}"
    fuentes=()
    for n in "${nuevas[@]}"; do fuentes+=("${TARGET}:${REMOTE_DIR}/${n}"); done
    "${SCP_BIN}" -q "${SSH_OPTS[@]}" "${fuentes[@]}" "${LOCAL_DIR}/"

    echo
    echo "==> Comprobando que se pueden restaurar las nuevas"
    # Una copia que no se puede abrir no es una copia. Comprobarlo aqui, y no el
    # dia que haga falta restaurarla. Si falla, el script para aqui y NO se borra nada.
    "${python_bin}" "${verificar}" "${LOCAL_DIR}" "${nuevas[@]}"
fi

echo
echo "==> Limpieza en el portatil: 14 dias todas; hasta 8 semanas, una por semana (el propietario, 07/10)"
# La mas reciente de cada base se guarda siempre; lo que no es una copia de la noche no se toca.
"${python_bin}" "${verificar}" --limpiar "${LOCAL_DIR}"
