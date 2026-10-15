#!/usr/bin/env bash
#
# Ploutos - instala el CLI de Claude en el VPS (pieza 11 del plan de la fase 3).
#
#   sudo bash /opt/ploutos/deploy/install-claude.sh
#
# Idempotente. NO pone el token: eso lo hace el propietario a mano en /opt/ploutos/.env
# (CLAUDE_CODE_OAUTH_TOKEN, permisos 600). Este script solo comprueba que esta,
# sin ensenyarlo nunca.
#
# Lo que hace, y por que:
# 1. La instalacion NATIVA, sin Node.js (el plan decia Node: era para la de npm,
#    y la del portatil, la verificada, es la nativa).
# 2. La version VERIFICADA, fija (`ai.invoke.VERIFIED_VERSION`, hay test). Con
#    otra version los flags pueden cambiar: ya pasaba con lo que daba el informe.
# 3. Comprueba el binario contra el manifiesto FIRMADO por Anthropic (huella de
#    la clave fijada aqui). Un binario que no cuadra se borra y el script para.
# 4. `/usr/local/bin/claude` apunta al binario de ESA version, no al lanzador de
#    `~/.local/bin`, que una actualizacion podria mover. Y el bot lanza el CLI con
#    DISABLE_UPDATES=1 (ai/invoke.py).
#
# Lo que NO hace: tocar los servicios que corren. Instalar el CLI no cambia nada
# de la ingesta ni del bucle de papel.

set -euo pipefail

CLAUDE_VERSION="2.1.266"
PLATFORM="linux-x64"
# Huella de "Anthropic Claude Code Release Signing <security@anthropic.com>",
# tal como la publica code.claude.com/docs/en/setup (comprobada el 23/09/2026).
SIGNING_FPR="31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
RELEASES="https://downloads.claude.ai/claude-code-releases"

APP_USER="ploutos"
APP_DIR="/opt/ploutos"
APP_HOME="/home/${APP_USER}"
BIN="${APP_HOME}/.local/share/claude/versions/${CLAUDE_VERSION}"
LINK="/usr/local/bin/claude"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "hay que ejecutarlo como root (usa sudo)"
[[ "$(uname -m)" == "x86_64" ]] || die "se esperaba x86_64 (${PLATFORM}) y es $(uname -m)"
getent passwd "${APP_USER}" >/dev/null || die "no existe el usuario ${APP_USER}: primero deploy/install.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
chmod 755 "${TMP}"

# --- 1. Lo necesario ---------------------------------------------------------
log "Paquetes: curl, gnupg, python3 y time (para medir la memoria de una llamada)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl gnupg python3 time >/dev/null

# --- 2. La memoria -------------------------------------------------------------
# La documentacion pide 4 GB. El VPS tiene 2 GB y sin swap (medido el 23/09/2026).
# No se decide aqui: se avisa, y la medida real sale del paso 7.
MEM_MB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
SWAP_MB=$(( $(awk '/SwapTotal/ {print $2}' /proc/meminfo) / 1024 ))
log "Memoria: ${MEM_MB} MB, swap ${SWAP_MB} MB"
if (( MEM_MB < 3800 )); then
    warn "Claude Code pide 4 GB y aqui hay ${MEM_MB} MB (swap ${SWAP_MB} MB)."
    warn "Mide una llamada real (paso 7) ANTES de enchufar la IA al bucle: sin swap,"
    warn "si falta memoria el kernel mata un proceso, y puede ser la ingesta."
fi

# --- 3. La casa del usuario del servicio --------------------------------------
# La instalacion nativa va a ~/.local. El usuario es de sistema (sin shell).
install -d -o "${APP_USER}" -g "${APP_USER}" -m 750 "${APP_HOME}"

# --- 4. La clave de firma y el manifiesto de la version -----------------------
log "Verificando el manifiesto firmado de la ${CLAUDE_VERSION}"
export GNUPGHOME="${TMP}/gnupg"
install -d -m 700 "${GNUPGHOME}"
curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o "${TMP}/key.asc"
gpg --batch --quiet --import "${TMP}/key.asc"
HUELLAS="$(gpg --batch --with-colons --fingerprint | awk -F: '/^fpr:/ {print $10}')"
grep -qx "${SIGNING_FPR}" <<<"${HUELLAS}" \
    || die "la clave descargada NO es la de Anthropic (huellas: ${HUELLAS})"
curl -fsSL "${RELEASES}/${CLAUDE_VERSION}/manifest.json" -o "${TMP}/manifest.json"
curl -fsSL "${RELEASES}/${CLAUDE_VERSION}/manifest.json.sig" -o "${TMP}/manifest.json.sig"
# La salida de gpg se guarda ANTES de buscar en ella. Con `gpg ... | grep -q` y
# `pipefail`, grep sale en cuanto encuentra la linea, gpg recibe SIGPIPE si sigue
# escribiendo y la tuberia entera da 141: una firma VALIDA acabaria en "no valida"
# (revision del 23/09/2026, reproducido con `seq 1 200000 | grep -q`).
ESTADO_GPG="$(gpg --batch --status-fd 1 --verify "${TMP}/manifest.json.sig" "${TMP}/manifest.json" 2>/dev/null)" \
    || die "gpg no pudo verificar la firma del manifiesto"
grep -q "^\[GNUPG:\] VALIDSIG ${SIGNING_FPR} " <<<"${ESTADO_GPG}" \
    || die "la firma del manifiesto NO es de la clave de Anthropic"
ESPERADO="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["platforms"][sys.argv[2]]["checksum"])' \
    "${TMP}/manifest.json" "${PLATFORM}")"
[[ "${ESPERADO}" =~ ^[0-9a-f]{64}$ ]] || die "el manifiesto no trae un sha256 para ${PLATFORM}"

# --- 5. El binario ----------------------------------------------------------------
if [[ -f "${BIN}" ]] && [[ "$(sha256sum "${BIN}" | cut -d' ' -f1)" == "${ESPERADO}" ]]; then
    log "La ${CLAUDE_VERSION} ya esta instalada y cuadra con el manifiesto"
else
    log "Instalando la ${CLAUDE_VERSION} (instalacion nativa, como ${APP_USER})"
    curl -fsSL https://claude.ai/install.sh -o "${TMP}/install.sh"
    chmod 644 "${TMP}/install.sh"
    # Desde la casa del usuario: si el instalador escribe algo en el directorio
    # actual, el de root (/root, o desde donde se lanzo esto) no es suyo.
    # SIN DISABLE_UPDATES aqui (25/09, en el despliegue): con esa variable el instalador
    # contesta "Updates are disabled by your administrator", NO instala nada y aun asi
    # dice "Installation complete". La version sigue fija (se pide la ${CLAUDE_VERSION} y
    # abajo se comprueba contra el manifiesto firmado) y en marcha el bot SIEMPRE llama
    # con DISABLE_UPDATES=1 (ai/invoke.py).
    (cd "${APP_HOME}" && sudo -u "${APP_USER}" -H \
        bash "${TMP}/install.sh" "${CLAUDE_VERSION}")
    [[ -f "${BIN}" ]] || die "el instalador no dejo ${BIN}"
    REAL="$(sha256sum "${BIN}" | cut -d' ' -f1)"
    if [[ "${REAL}" != "${ESPERADO}" ]]; then
        rm -f "${BIN}"
        die "el binario NO cuadra con el manifiesto firmado (${REAL} != ${ESPERADO}); borrado"
    fi
fi

ln -sfn "${BIN}" "${LINK}"
VERSION_OUT="$(sudo -u "${APP_USER}" -H env DISABLE_UPDATES=1 "${LINK}" --version)"
[[ "${VERSION_OUT}" == "${CLAUDE_VERSION} "* ]] \
    || die "claude --version dice '${VERSION_OUT}', se esperaba ${CLAUDE_VERSION}"
log "OK: ${LINK} -> ${BIN} (${VERSION_OUT})"

# --- 6. El token: que esta, sin ensenyarlo -------------------------------------
ENV_FILE="${APP_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    warn "no existe ${ENV_FILE}"
elif [[ "$(stat -c '%U %a' "${ENV_FILE}")" != "${APP_USER} 600" ]]; then
    warn "${ENV_FILE} tiene que ser de ${APP_USER} con permisos 600 (es $(stat -c '%U %a' "${ENV_FILE}"))"
elif ! grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' "${ENV_FILE}"; then
    warn "falta CLAUDE_CODE_OAUTH_TOKEN en ${ENV_FILE}: lo pone el propietario a mano (nunca por el chat)"
else
    log "El token esta en ${ENV_FILE} (no se muestra)"
fi

# --- 7. Lo siguiente, a mano ------------------------------------------------------
cat <<EOF

Siguiente paso (gasta UNA llamada de la cuota y mide la memoria):

  cd ${APP_DIR} && sudo -u ${APP_USER} /usr/bin/time -v .venv/bin/python \\
      scripts/verify_claude_cli.py --sin-sesion 2>&1 | tail -40

"Maximum resident set size" es el pico del proceso MAS GRANDE (el CLI), en KB.
Compararlo con lo que queda libre con los servicios en marcha: free -m.
EOF
