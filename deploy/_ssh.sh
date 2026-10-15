#!/usr/bin/env bash
#
# Elige el binario de ssh/scp correcto. Lo cargan los demas scripts de deploy.
#
# EL PROBLEMA (medido el 22/09/2026): en Windows con Git Bash hay DOS clientes
# de SSH instalados y no son intercambiables:
#
#   /usr/bin/ssh                      el de Git Bash
#   /c/Windows/System32/OpenSSH/ssh   el de Windows
#
# El agente que guarda la clave descifrada es el SERVICIO de Windows, y el ssh
# de Git Bash NO lo ve. Resultado: los scripts fallan con
# "Permission denied (publickey)" aunque desde PowerShell la misma conexion
# funcione, lo cual despista muchisimo.
#
# Para forzar otro binario:  PLOUTOS_SSH=/ruta/ssh bash deploy/sync.sh ploutos

_pick() {
    local name="$1" override="$2" win="/c/Windows/System32/OpenSSH/${1}.exe"
    if [[ -n "${override}" ]]; then
        echo "${override}"
    elif [[ -x "${win}" ]]; then
        # En Windows preferimos el nativo: es el unico que habla con el agente.
        echo "${win}"
    else
        echo "${name}"
    fi
}

SSH_BIN="$(_pick ssh "${PLOUTOS_SSH:-}")"
SCP_BIN="$(_pick scp "${PLOUTOS_SCP:-}")"

export SSH_BIN SCP_BIN
