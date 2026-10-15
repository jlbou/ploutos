#!/usr/bin/env bash
#
# Cierra el acceso SSH por contrasenya y el login de root (regla 19).
#
# POR QUE IMPORTA: el proveedor del VPS manda la contrasenya de root en texto plano por
# correo. Esa contrasenya vive para siempre en el buzon. Mientras el servidor
# acepte contrasenyas, ese correo es una llave. Despues de esto, no lo es.
#
# CUIDADO: equivocarse aqui te deja fuera del servidor. El script comprueba
# que tu clave SSH funciona ANTES de tocar nada, y deja una copia de la
# configuracion para poder volver atras desde la consola web del proveedor del VPS.
#
#   sudo bash /opt/ploutos/deploy/harden-ssh.sh

set -euo pipefail

SSHD_CONFIG="/etc/ssh/sshd_config"
DROPIN_DIR="/etc/ssh/sshd_config.d"
DROPIN="${DROPIN_DIR}/99-ploutos-hardening.conf"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "hay que ejecutarlo como root (usa sudo)"

# --- 1. Comprobar que hay claves instaladas ------------------------------
log "Comprobando que puedes entrar con clave SSH"

FOUND=0
for home in /root /home/*; do
    keyfile="${home}/.ssh/authorized_keys"
    [[ -f "${keyfile}" ]] || continue
    n="$(grep -c '^ssh-' "${keyfile}" 2>/dev/null || echo 0)"
    if [[ "${n}" -gt 0 ]]; then
        echo "    ${keyfile}: ${n} clave(s)"
        FOUND=$((FOUND + n))
    fi
done

if [[ "${FOUND}" -eq 0 ]]; then
    die "NO hay ninguna clave SSH instalada.
     Si desactivo las contrasenyas ahora, te quedas fuera del servidor.

     Desde tu portatil, primero:
         ssh-copy-id root@<IP>
     Comprueba que puedes entrar sin contrasenya y vuelve a ejecutar esto."
fi

log "Encontradas ${FOUND} clave(s). Antes de seguir, LEE ESTO:"
cat <<'EOF'

    1. Deja ESTA sesion SSH abierta.
    2. Abre OTRA terminal y comprueba que puedes entrar sin contrasenya.
    3. Si algo sale mal, siempre te queda la consola web (VNC) del panel
       del proveedor del VPS, que no pasa por SSH.

EOF

read -r -p "Has comprobado que entras con clave y tienes otra sesion abierta? (si/NO) " answer
if [[ "${answer}" != "si" ]]; then
    warn "Cancelado. No se ha tocado nada."
    exit 0
fi

# --- 2. Copia de seguridad ------------------------------------------------
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "${SSHD_CONFIG}" "${SSHD_CONFIG}.ploutos-${STAMP}.bak"
log "Copia de la configuracion: ${SSHD_CONFIG}.ploutos-${STAMP}.bak"

# --- 3. Aplicar el endurecimiento ----------------------------------------
# Se hace con un fichero aparte en sshd_config.d en vez de editar el principal:
# es mas facil de revisar y de deshacer (basta con borrar el fichero).
log "Escribiendo ${DROPIN}"
mkdir -p "${DROPIN_DIR}"
cat > "${DROPIN}" <<'EOF'
# Ploutos - endurecimiento de SSH (regla dura 19).
# Para deshacerlo: borra este fichero y `systemctl restart ssh`.

# Sin contrasenyas: la que el proveedor del VPS manda por correo deja de servir.
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitEmptyPasswords no

# Sin login directo de root: se entra con usuario normal y se usa sudo.
PermitRootLogin prohibit-password

# Solo claves.
PubkeyAuthentication yes

# Menos superficie
X11Forwarding no
AllowAgentForwarding no
MaxAuthTries 3
LoginGraceTime 30
EOF
chmod 644 "${DROPIN}"

# --- 4. Validar ANTES de reiniciar ---------------------------------------
log "Validando la configuracion de sshd"
if ! sshd -t; then
    rm -f "${DROPIN}"
    die "la configuracion no valida. He borrado el fichero y no he tocado el servicio."
fi
echo "    configuracion valida"

# --- 5. Recargar ----------------------------------------------------------
log "Recargando el servicio SSH (las sesiones abiertas NO se cortan)"
systemctl reload ssh || systemctl reload sshd

log "Hecho"
cat <<EOF

  Ahora el servidor solo acepta clave SSH.

  COMPRUEBALO AHORA, sin cerrar esta sesion, desde otra terminal:
      ssh root@<IP>          <- debe entrar sin pedir contrasenya

  Si algo falla, deshazlo desde esta sesion:
      rm ${DROPIN} && systemctl reload ssh

  Y ya puedes borrar del correo la contrasenya de root: ya no sirve para entrar.

EOF
