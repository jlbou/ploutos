# Cierre de la fase 5: panel, Telegram y vigilante

PRD 12: **"Dashboard, Telegram, watchdog. Criterio: todos los paneles con datos reales."** Repasado el 03/10/2026
punto por punto contra lo que hay de verdad (el panel en marcha desde el 26/09; Telegram y Healthchecks desde el 25/09;
el demo desde el 03/10).

## 1. El panel (PRD 10)

| Lo que pide el PRD | Estado | Donde y desde cuando |
|---|---|---|
| Tiempo real (FastAPI + WebSocket + SPA), solo por Tailscale | **si** | `ploutos-panel`, IP de Tailscale, cortafuegos solo `tailscale0` (26/09; sin PIN: decision del 25/09) |
| Barra de estado: equity, PnL del dia, drawdown, distancia al suelo, operaciones hoy / 6, posiciones / 3, modo, llamadas a la IA / presupuesto | **si**, las ocho | la fila de cada cartera (equity de la vela y "ahora ≈", hoy, caida maxima, cerradas hoy / 6, posiciones / 3, llamadas IA / 40, modo, barra sobre el suelo) |
| Slider de agresividad (5 niveles), cambios desde el dia siguiente | **se ve; bloqueado en el 3** | decision del propietario del 25/09: bloqueado hasta cerrar la fase 6 y revisar la estrategia. "Desde el dia siguiente" no se puede probar mientras este bloqueado |
| Diagrama de flujo por nodos: sistema y por moneda | **si** | "Flujo de la ultima vela" (28/09) |
| "Que esta pensando la IA": decision, razones, rechazados, veredicto del motor | **si** | pagina IA (velas con candidatos, lo que dijo y lo que hizo el motor) |
| Controles: pausar, solo cierre, cerrar todo con doble confirmacion, kill switch | **si** | pausar / quitar la pausa (= solo cierre manual), parar / levantar, cerrar todo con doble confirmacion; entran en `control_comandos` con origen `panel` |
| Posiciones abiertas, con el estado de su OCO | **si, desde el 03/10** | las de papel no tienen OCO (las gestiona el bucle); las del DEMO, en "Demo de OKX" con "OCO viva / SIN OCO / vendiendo", en tarjetas con grafico |
| Historico de operaciones cerradas, con CSV fiscal | **si** | pagina Operaciones; el CSV en euros con el cambio USDC/EUR de OKX (28/09) |
| Curva de equity comparada: real vs baseline vs hold BTC | **si, con la IA en lugar de "real"** | la curva compara IA, baseline y comprar BTC. "Real" sera la cuenta de dinero en la fase 7 |
| Hipotesis en curso y aprendido | **no: es de la fase 8** | el panel existe ("fase 8") y no tiene datos: el bucle de aprendizaje no existe aun |
| Solo lectura; sus comandos se auditan | **si** | bases en `mode=ro`; comandos con origen; juez `check_control.py` CUMPLIDO (7,1 dias, 02/10) |

## 2. Telegram (PRD 9)

| Obligatorio | Estado | Visto de verdad |
|---|---|---|
| Cierre de cada operacion (par, $ y R, motivo, duracion) | **si en papel; en el demo, sin R ni duracion** | papel: 2 por cartera enviados; demo: "cerrada ... a precio: +x $" (falta R y duracion) |
| Cambio de modo | **si** | demo: DEGRADED entra y sale (03/10, test de caos 3) |
| Parada del bot (y su "en marcha") | **si** | papel y demo (el del demo, desde el 03/10) |
| Bot caido (vigilante independiente) | **si** | Healthchecks, 8 comprobaciones; probado el 25/09 (la IA parada 19 min) y el 03/10 (el ejecutor parado por la prueba 10) |
| Fallo de reconciliacion | **si** | el ejecutor avisa cada descuadre (03/10); aun no ha habido ninguno de verdad |
| Error de autenticacion de la IA o de OKX | **de la IA si; de OKX no explicito** | la IA: aviso `auth` (nunca ha hecho falta). OKX: una clave rechazada sale como "3 errores seguidos del exchange" (DEGRADED), sin decir que es la clave |
| Token de la IA a punto de caducar | **si** | en el resumen diario (`claude.token_expires_on`) |
| Resumen diario | **si** | 8 por cartera |
| Comandos `/status`, `/pause`, `/closeonly`, `/kill` | **si** | `ploutos-telegram`; `check_control.py` CUMPLIDO |

## 3. El vigilante

Healthchecks.io: 7 comprobaciones del VPS (ingesta, papel, papel IA, copia, noticias, comandos, ejecutor) y 1 del
portatil (la copia diaria). Avisa por Telegram. Probado dos veces (25/09 y 03/10).

## 4. Lo que falta y la propuesta

**Dos huecos pequenyos del demo** (arreglables hoy):
1. El aviso de cierre del demo sin R ni duracion (los de papel si los llevan).
2. Un error de autenticacion de OKX no se dice como tal (sale como DEGRADED por errores seguidos).

**Y uno que no depende de la fase 5:** el panel de hipotesis, sin datos hasta la fase 8.

**Propuesta:** arreglar los dos huecos y **cerrar la fase 5** con el panel de hipotesis como parte de la fase 8. El
criterio del PRD al pie de la letra ("todos los paneles con datos reales") no se puede cumplir hasta la fase 8; dejarla
abierta hasta entonces no aporta nada. Decide el propietario.

## 5. Veredicto (03/10/2026)

**el propietario: fase 5 CERRADA**, con el panel de hipotesis como parte de la fase 8. Los dos huecos, arreglados el mismo dia
(con test y mutacion en rojo):
1. El aviso de cierre del demo lleva ahora $, R, motivo y duracion, con el mismo formato que los de papel.
2. Una clave rechazada por OKX en el ejecutor se avisa como "Error de autenticacion con OKX (demo)" con el codigo de
   OKX (nunca la credencial), como mucho una vez por hora; sigue contando como error para DEGRADED.
