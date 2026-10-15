# Propuesta: el vigilante (watchdog) — "el bot se ha caido"

Escrito el 24/09/2026. Es una PROPUESTA para que decida el propietario; no hay codigo.

## 1. El problema

El PRD (seccion 9) pide avisar de "bot caido (avisa el **watchdog independiente**)".
Hoy, si algo se para, nadie avisa:

| Que pasa | Que ocurre hoy |
|---|---|
| Un servicio se muere | systemd lo relanza (`Restart=always`). Bien |
| Un servicio se queda **colgado** (vivo pero sin avanzar) | Nadie lo nota: systemd lo ve "activo" |
| **El VPS entero cae** (proveedor, red, disco lleno) | Nadie lo nota hasta que el propietario mira |
| La copia de la noche no se hace | La tarea del domingo lo dice... el domingo |

Los avisos de Telegram de la fase 3 no lo arreglan: los manda el propio bot, y **un bot
caido no avisa de que se ha caido**. Hace falta alguien DE FUERA que eche en falta una
senyal. En la semana de la fase 3 esto importa: dos carteras funcionando solas.

## 2. Como funcionan estos vigilantes

Un servicio externo espera una senyal ("latido") cada X minutos. Cada parte del bot la
manda **solo cuando va bien de verdad** (no solo "el proceso existe", sino "ha avanzado").
Si la senyal no llega en X minutos mas un margen, el servicio avisa.

## 3. Opciones

**A. Healthchecks.io, plan gratuito (recomendada).** Comprobado en su web el 24/09/2026:
20 comprobaciones gratis, cada una con "periodo" y "margen", y avisos por **Telegram**,
correo y otros. Se usarian 4 de las 20:

| Comprobacion | Manda el latido cuando... | Periodo + margen |
|---|---|---|
| Ingesta | la ultima vela de 1 m cerrada tiene menos de 2 min | 5 min + 10 min |
| Papel del baseline | una vuelta termina sin error | 5 min + 15 min |
| Papel de la IA | una vuelta termina sin error | 5 min + 15 min |
| Copia de la noche | la copia sale bien y se verifica | 1 dia + 2 h |

- Si el VPS cae, dejan de llegar los cuatro y avisa. Si un servicio se cuelga, deja de
  llegar el suyo. Si la ingesta se para, su latido depende de que haya velas nuevas.
- Lo que sale del VPS: una peticion HTTPS vacia a una URL secreta. Ningun dato del bot.
  Las cuatro URL, al `.env` (son secretos: quien las tenga puede mandar latidos falsos).
- Contra: un servicio de un tercero. Si Healthchecks.io cae, podria no avisar (o avisar de
  mas) un rato. Para un bot de 50 $ en papel, aceptable.

**B. Una tarea del portatil que mire el VPS cada 15 min.** Gratis y sin terceros, pero el
portatil no esta siempre encendido: de noche, que es cuando mas falta hace, no vigila.

**C. Un vigilante propio en otra maquina** (p. ej. Uptime Kuma). Sin terceros, pero hace
falta otro servidor encendido siempre: cuesta dinero y mantenimiento.

**D. Esperar a la fase 5.** Es donde lo pone el PRD, pero la fase 3 es la primera semana en
que el bot va solo con dos carteras.

## 4. Lo que haria falta

1. **el propietario crea la cuenta** en Healthchecks.io (yo no puedo crear cuentas) y las cuatro
   comprobaciones, y conecta el aviso a su Telegram desde su web.
2. El propietario pone las cuatro URL en `/opt/ploutos/.env` (a mano, nunca por el chat).
3. Yo escribo el latido: una funcion que nunca lanza (timeout de pocos segundos, un fallo se
   ignora) y la llamada en cada servicio y en `backup.sh`. Pequenyo, con tests, en la rama de
   la fase 3, y se despliega con ella.

## 5. Lo que tiene que decidir el propietario

**DECIDIDO el 24/09/2026:** ahora (para la fase 3), con Healthchecks.io gratuito y avisos por
Telegram. Aclarado con el propietario: el plan da 20 COMPROBACIONES (cosas vigiladas), no 20 latidos al
dia; cada una admite hasta 5 latidos por minuto y guarda los ultimos 100.

1. Si se hace **ahora** (para la fase 3) o se espera a la fase 5.
2. Que servicio: Healthchecks.io (recomendado) u otro.
3. Por donde avisa: **Telegram** (recomendado: ya lo lleva encima) o correo.
