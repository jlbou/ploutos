# Propuesta: que hacer con las actualizaciones automaticas del VPS

Estado: **DECIDIDO por el propietario el 25/09/2026: opcion 2** (reinicio automatico solo cuando haga falta, a
las 07:15 UTC). Hecho en la rama `fase-3-integracion` (`deploy/52ploutos-reboot.conf`, lo instala
`install.sh`); llega al VPS con el despliegue de la fase 3. Propuesta original (24/09): Pendiente de CLAUDE.md "antes de la fase 7";
se adelanta porque ya reinicio la ingesta una vez (23/09) y en la fase 3 el bot va solo una semana.
**No se toca nada antes del cierre del viernes**: la medicion de las 72 h tiene que acabar con la
maquina como estaba.

## 1. Como esta ahora (leido en el VPS el 24/09, solo lectura)

| Pieza | Valor | Que significa |
|---|---|---|
| `20auto-upgrades` | `Unattended-Upgrade "1"` | cada dia se instalan solas las actualizaciones |
| Origenes permitidos | `noble`, `noble-security` y ESM | en la practica, solo las de **seguridad** |
| `apt-daily-upgrade.timer` | 06:00 UTC + hasta 60 min al azar, `Persistent=true` | se instalan entre las **06:00 y las 07:00 UTC**; si la maquina estaba apagada, al arrancar |
| `needrestart` | por defecto de Ubuntu en el gancho de APT: `'a'` | **reinicia SOLO los servicios afectados**, sin preguntar |
| `Automatic-Reboot` | sin poner (por defecto `false`) | **nunca reinicia la maquina** |
| Reinicio pendiente | no hay (`/var/run/reboot-required` no existe); nucleo `6.8.0-139`, arriba desde el 22/09 12:30 | |

Lo que paso el 23/09 a las 06:40: se actualizo `sudo`, `needrestart` reinicio `ploutos-ingest` y
`ploutos-spread`, la ingesta se relleno sola (301 velas por timeframe) y el juez no vio huecos.

## 2. Los dos riesgos reales

**A. Un reinicio de servicio a una hora mala.** Hoy no pasa: las velas de 4 h cierran a las 00, 04,
08, 12, 16 y 20 UTC, y la ventana de las 06:00-07:00 cae **entre dos cierres**. Un reinicio ahi no
hace perder ninguna decision de la IA (las decisiones se toman al cierre). Todos los servicios
estan hechos para reiniciarse (`Restart=always`, estado derivado de lo guardado); lo prueba el 23/09.
Excepcion: `Persistent=true` hace que, tras un apagado, se actualice AL ARRANCAR, a cualquier hora.

**B. Parches del nucleo que nunca se aplican.** Sin reinicio automatico, una actualizacion del
nucleo (o de `libc`) se instala pero no entra en vigor hasta que alguien reinicia la maquina. Nadie
se entera: el unico rastro es el fichero `/var/run/reboot-required`. En la fase 4 el VPS tendra
claves de trading; una maquina con parches de seguridad sin aplicar durante meses es justo lo que
no se quiere.

## 3. Opciones

**1. Dejarlo como esta.** Seguridad automatica y servicios que se reinician solos entre las 06 y
las 07. Riesgo B abierto: los parches del nucleo esperan a un reinicio manual que nadie recuerda.

**2. Como esta, mas reinicio automatico SOLO cuando haga falta, a las 07:15 UTC (recomendada).**
- `Unattended-Upgrade::Automatic-Reboot "true"` y `Automatic-Reboot-Time "07:15"`: solo reinicia si
  existe `/var/run/reboot-required` (nucleo, `libc`...), unas pocas veces al mes como mucho.
- **Por que las 07:15:** despues de que acabe la ventana de las 06-07 y **45 min antes del cierre de
  las 08:00**. Un reinicio tarda ~1 min: la ingesta rellena lo que falte y la vela de las 08:00
  se decide normal. Y va siempre justo DESPUES de instalar, no horas mas tarde.
- **El vigilante no salta en falso:** un reinicio de ~1-2 min queda dentro de los 5 min de
  periodo + 15 de margen de Healthchecks. Si la maquina no vuelve, SI salta: es justo lo que tiene
  que avisar.
- **Con dinero (fase 7):** las posiciones estan protegidas por la OCO **en el exchange** (regla 13)
  aunque el VPS este apagado; al volver, la conciliacion (fase 4) cuadra el estado.
- Coste: un fichero de configuracion en `deploy/` que instala `install.sh` (sin CRLF, con test).

**3. Quitar las automaticas y actualizar a mano cada semana.** Control total, pero depende de
acordarse; en una maquina con claves de trading, olvidarse unas semanas es el riesgo mas probable.
Descartada.

**4. Fijar tambien la hora exacta** (`RandomizedDelaySec=0`, siempre a las 06:00). No aporta: la
ventana 06-07 ya cae entre dos cierres. Se deja como esta para no tocar mas de lo necesario.

## 4. Cuando se aplicaria

Con la opcion 2, dentro del despliegue de la fase 3 (`docs/archivo/despliegue-fase-3.md`, junto a la
memoria del paso 4), despues del cierre del viernes y del OK. Nunca antes: las 72 h miden la
maquina tal como esta.

Y se comprueba (verificar, no suponer): `apt-config dump | grep Automatic-Reboot` tiene que dar
`true` y `07:15`; la prueba de verdad es el primer reinicio real, que se vera en
`last reboot` y, si algo falla, en Healthchecks.

## 5. Decision para el propietario

- **Opcion 2 (recomendada):** actualizaciones de seguridad automaticas (como ahora) y reinicio
  automatico solo cuando haga falta, a las 07:15 UTC, entre dos cierres de vela.
- Opcion 1: como ahora, y reiniciar a mano cuando haya parches del nucleo.
- Opcion 3: todo a mano.
