#!/usr/bin/env bash
#
# Revision semanal de actualizaciones (decision del propietario del 26/09/2026). La lanza
# ploutos-actualizaciones.timer los domingos a las 07:30 UTC, entre dos cierres de vela.
#
# - Tailscale es lo UNICO que se instala solo: es lo que abre una puerta a la red.
# - NEEDRESTART_SUSPEND=1: actualizar Tailscale no toca las librerias del bot, asi que no hay por que
#   reiniciar sus servicios (el 26/09, instalar Tailscale reinicio la ingesta, las noticias y Telegram).
#   Los parches de seguridad de Ubuntu siguen entrando solos cada dia, como hasta ahora.
# - El resto (librerias del bot, el programa de la IA, Ubuntu no de seguridad) solo se AVISA:
#   scripts/revisar_actualizaciones.py manda un Telegram si hay algo nuevo.
set -uo pipefail

version() { dpkg-query -W -f='${Version}' tailscale 2>/dev/null || echo "-"; }

antes="$(version)"
apt-get update -qq -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/tailscale.list \
    -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 \
    || echo "no se pudo consultar el repositorio de Tailscale"
NEEDRESTART_SUSPEND=1 DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --only-upgrade tailscale \
    || echo "no se pudo actualizar Tailscale"
despues="$(version)"
echo "Tailscale: ${antes} -> ${despues}"

sudo -u ploutos -H /opt/ploutos/.venv/bin/python /opt/ploutos/scripts/revisar_actualizaciones.py \
    --tailscale "${antes}" "${despues}"
