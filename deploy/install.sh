#!/usr/bin/env bash
#
# Ploutos - instalacion en el VPS (PRD seccion 11).
#
# Idempotente: se puede volver a ejecutar siempre que haga falta.
# Se ejecuta como root en un Ubuntu 24.04 recien instalado.
#
#   sudo bash /opt/ploutos/deploy/install.sh
#
# NO toca la configuracion de SSH: eso lo hace harden-ssh.sh aparte, porque
# equivocarse ahi te deja fuera del servidor.

set -euo pipefail

APP_USER="ploutos"
APP_DIR="/opt/ploutos"
VENV_DIR="${APP_DIR}/.venv"
BACKUP_DIR="/var/backups/ploutos"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "hay que ejecutarlo como root (usa sudo)"
[[ -f "${APP_DIR}/pyproject.toml" ]] || die "no encuentro ${APP_DIR}/pyproject.toml; copia antes el proyecto (deploy/sync.sh)"

# --- 1. Paquetes del sistema ---------------------------------------------
log "Actualizando indices de paquetes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

log "Instalando paquetes"
# chrony: el reloj. Las firmas de la API de OKX llevan timestamp y el exchange
# rechaza peticiones desfasadas (informe 1.3[1]).
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential \
    sqlite3 \
    chrony \
    ufw \
    rsync \
    ca-certificates \
    tzdata

# --- 2. Version de Python ------------------------------------------------
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Python del sistema: ${PYVER}"
if [[ "${PYVER}" != "3.12" ]]; then
    die "se esperaba Python 3.12 (Ubuntu 24.04) y hay ${PYVER}.
     El portatil de desarrollo usa 3.12; correr otra version en el servidor
     es la receta del 'en mi maquina funcionaba'. Reinstala el sistema con
     Ubuntu 24.04 o avisa antes de cambiar el stack."
fi

# --- 3. Reloj -------------------------------------------------------------
log "Configurando el reloj (UTC + chrony)"
timedatectl set-timezone UTC
systemctl enable --now chrony
sleep 2
chronyc tracking | head -5 || warn "chrony aun no ha sincronizado; es normal recien arrancado"

# --- 3b. Preferir IPv4 sobre IPv6 ----------------------------------------
# La lista blanca de la clave de API de OKX (regla 19) lleva la IPv4 fija del
# VPS. Por defecto Ubuntu prefiere IPv6: OKX veia las peticiones llegando desde
# la IPv6, que no esta autorizada, y respondia 50119 "API key doesn't exist",
# un error que no da ninguna pista del problema real.
#
# OJO con gai.conf: en cuanto aparece UNA linea `precedence`, la tabla por
# defecto se descarta ENTERA. Hay que repetirla toda, no solo la de IPv4.
log "Configurando preferencia de IPv4 (lista blanca de OKX)"
if ! grep -q "Ploutos: preferir IPv4" /etc/gai.conf 2>/dev/null; then
    cat >> /etc/gai.conf <<'GAIEOF'

# Ploutos: preferir IPv4 sobre IPv6 (lista blanca de la clave de API de OKX).
precedence  ::1/128       50
precedence  ::/0          40
precedence  2002::/16     30
precedence  ::/96         20
precedence  ::ffff:0:0/96 100
GAIEOF
fi
OUT_IP="$(curl -s -m 15 https://api64.ipify.org || echo '?')"
echo "    IP de salida: ${OUT_IP}"
if [[ "${OUT_IP}" == *:* ]]; then
    warn "la IP de salida sigue siendo IPv6. La clave de API de OKX fallara
     con 50119 si la lista blanca solo tiene la IPv4."
fi

# --- 4. Usuario sin privilegios ------------------------------------------
if id "${APP_USER}" &>/dev/null; then
    log "El usuario ${APP_USER} ya existe"
else
    log "Creando el usuario ${APP_USER} (sin login, sin contrasenya)"
    useradd --system --create-home --home-dir "/home/${APP_USER}" \
            --shell /usr/sbin/nologin "${APP_USER}"
fi

# --- 5. Permisos ----------------------------------------------------------
log "Ajustando permisos de ${APP_DIR}"
mkdir -p "${APP_DIR}/var" "${BACKUP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${BACKUP_DIR}"
chmod 750 "${APP_DIR}" "${BACKUP_DIR}"

# Regla 19: si hay .env, solo lo puede leer su duenyo.
if [[ -f "${APP_DIR}/.env" ]]; then
    chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    log "Permisos de .env ajustados a 600"
fi

# --- 6. Entorno virtual ---------------------------------------------------
log "Creando el entorno virtual"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
fi
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
log "Instalando Ploutos y sus dependencias (puede tardar unos minutos)"
# Se instalan tambien las dependencias de desarrollo (pytest, hypothesis).
# Motivo: el servidor es el entorno de referencia, el unico que corre 24/7 y el
# unico donde importa de verdad que las reglas duras se cumplan. Poder lanzar la
# suite ALLI es lo que demuestra que el despliegue esta sano, no solo que el
# portatil lo estaba. Son unos pocos MB.
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -m pip install --quiet -e "${APP_DIR}[dev]"

# --- 7. Comprobacion de la configuracion ---------------------------------
log "Validando config/settings.yaml"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" - <<'PYEOF'
import sys
sys.path.insert(0, "/opt/ploutos")
from core.config import load_settings
s = load_settings("/opt/ploutos/config/settings.yaml")
print(f"    configuracion valida: {len(s.whitelist)} pares, "
      f"max {s.risk.max_positions} posiciones, suelo {s.capital.floor_usd} $")
PYEOF

# --- 8. Cortafuegos -------------------------------------------------------
# Solo SSH. El dashboard (fase 5) ira por Tailscale o Cloudflare Tunnel, nunca
# expuesto a internet: tiene botones que mueven dinero (informe 3.6).
log "Configurando el cortafuegos (solo SSH entrante)"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null
ufw status verbose | head -8

# --- 9. Servicios systemd -------------------------------------------------
log "Instalando los servicios de systemd"
install -m 644 "${APP_DIR}/deploy/ploutos-ingest.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-paper.service"  /etc/systemd/system/
# La cartera de la IA se copia pero NO se habilita: antes hacen falta el CLI de
# Claude, el token, el swap y el OK del propietario (ver la cabecera del servicio).
install -m 644 "${APP_DIR}/deploy/ploutos-paper-ai.service" /etc/systemd/system/
# Noticias y comandos de Telegram: tambien se copian sin habilitar (se arrancan con el OK del propietario,
# pasos en docs/diseno-noticias.md y docs/diseno-comandos-telegram.md).
install -m 644 "${APP_DIR}/deploy/ploutos-news.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-telegram.service" /etc/systemd/system/
# El ejecutor del demo (fase 4): se copia sin habilitar (clave del demo, feeType 1, HEALTHCHECK_EJECUTOR y OK del propietario).
install -m 644 "${APP_DIR}/deploy/ploutos-exec.service" /etc/systemd/system/
# Los medios en sombra (07/10): se copian sin habilitar (se arrancan con el OK del propietario; docs/diseno-medios-sombra.md).
install -m 644 "${APP_DIR}/deploy/ploutos-medios.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-backup.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-backup.timer"   /etc/systemd/system/
# Los jueces una vez al dia; Telegram solo si alguno da FALLA (decision del propietario del 26/09).
install -m 644 "${APP_DIR}/deploy/ploutos-jueces.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-jueces.timer"   /etc/systemd/system/
# El papel de L hacia adelante (el propietario, 10/10/2026): un estudio, rehace L cada noche a las 00:20.
install -m 644 "${APP_DIR}/deploy/ploutos-papel-l.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-papel-l.timer"   /etc/systemd/system/
# El embudo de noticias para L, en sombra (el propietario, 11/10/2026): cada 30 min.
install -m 644 "${APP_DIR}/deploy/ploutos-embudo.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-embudo.timer"   /etc/systemd/system/
# El recolector de libros de ordenes del paso 2 (V5; el propietario, 15/10/2026): cada hora, hasta el 30/10/2026.
install -m 644 "${APP_DIR}/deploy/ploutos-libros.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-libros.timer"   /etc/systemd/system/
# Revision semanal: Tailscale se instala solo; lo demas solo se avisa (el propietario, 26/09).
install -m 644 "${APP_DIR}/deploy/ploutos-actualizaciones.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/ploutos-actualizaciones.timer"   /etc/systemd/system/
# El panel (fase 5), solo por Tailscale: se copia sin habilitar (necesita Tailscale autorizado).
install -m 644 "${APP_DIR}/deploy/ploutos-panel.service" /etc/systemd/system/
install -m 755 "${APP_DIR}/deploy/backup.sh" /usr/local/bin/ploutos-backup
# Reinicio automatico solo si un parche lo pide, a las 07:15 UTC (decision del propietario del 25/09).
install -m 644 "${APP_DIR}/deploy/52ploutos-reboot.conf" /etc/apt/apt.conf.d/52ploutos-reboot
systemctl daemon-reload
systemctl enable ploutos-backup.timer >/dev/null
systemctl start  ploutos-backup.timer
systemctl enable ploutos-jueces.timer >/dev/null
systemctl start  ploutos-jueces.timer
systemctl enable ploutos-papel-l.timer >/dev/null
systemctl start  ploutos-papel-l.timer
systemctl enable ploutos-embudo.timer >/dev/null
systemctl start  ploutos-embudo.timer
systemctl enable ploutos-libros.timer >/dev/null
systemctl start  ploutos-libros.timer
systemctl enable ploutos-actualizaciones.timer >/dev/null
systemctl start  ploutos-actualizaciones.timer

# --- 10. Resumen ----------------------------------------------------------
log "Instalacion terminada"
cat <<EOF

  Usuario:      ${APP_USER}
  Proyecto:     ${APP_DIR}
  Entorno:      ${VENV_DIR}
  Base de datos:${APP_DIR}/var/ploutos.db
  Backups:      ${BACKUP_DIR}

  Siguientes pasos:

    1. Arrancar la ingesta (fase 1):
         systemctl enable --now ploutos-ingest

    2. Ver que hace:
         journalctl -u ploutos-ingest -f

    3. A las 72 h, comprobar el criterio de avance:
         sudo -u ${APP_USER} ${VENV_DIR}/bin/python ${APP_DIR}/scripts/check_gaps.py

    4. Cerrar el acceso por contrasenya (SOLO con la clave SSH ya probada):
         bash ${APP_DIR}/deploy/harden-ssh.sh

EOF
