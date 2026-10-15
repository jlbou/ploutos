# PRD v2 — Ploutos: bot de trading autónomo con IA

**Versión:** 2.0 (22/09/2026). Sustituye al PRD v1.
**Documento complementario:** `informe-ploutos.md` (referencia técnica del *cómo*).
**Jerarquía:** si algo del informe contradice este PRD, **manda este PRD**.

## 1. Objetivo

Construir **Ploutos**, un bot de trading spot de criptomonedas totalmente autónomo (sin humano en el bucle), que decide con ayuda de Claude (vía Claude Code CLI) cuándo abrir y cerrar operaciones, dentro de unas reglas de seguridad deterministas que la IA no puede modificar.

Es un **proyecto personal de experimentación y aprendizaje**. El éxito se mide por: (1) respetar siempre las reglas de seguridad, (2) trazabilidad total de cada decisión y (3) saber con datos si la IA aporta ventaja frente a un baseline sin IA. La rentabilidad es secundaria.

## 2. Usuario

el propietario, uso personal exclusivo.

## 3. Decisiones cerradas (cambios respecto a v1)

| Tema | v1 | v2 | Motivo |
|---|---|---|---|
| Exchange | Binance | **OKX EU** | Binance sin licencia MiCA; servicios UE suspendidos o en zona gris desde 07/2026 |
| Pares | USDT o BTC | **Solo contra USDC** | USDT deslistado para el EEE; los pares contra BTC complican medir el riesgo |
| Frecuencia | 10–20 op./día | **1–5 op./día, máximo duro 6** | Arrastre de comisiones con 50 $ |
| Acceso a Claude | Plan normal | **Plan normal + token de 1 año + presupuesto de llamadas** | Autenticación desatendida y protección de la cuota personal |
| Límites | Solo el suelo de 25 $ | **Suelo de 25 $ + escalones de drawdown + límite diario** | No esperar a perder el 50 % para reaccionar |
| Simulación | Sin decidir | **Demo 1 semana + papel 2–3 semanas** antes del dinero real | Detectar bugs sin perder capital |
| VPS | Sin decidir | **Oracle Cloud Always Free (región UE) + plan B reproducible** | Coste cero, con salida rápida si falla |

## 4. Reglas duras (no modificables por la IA ni por el bucle de aprendizaje)

1. **Sin apalancamiento.** Solo spot. Nunca margin, futuros ni préstamos.
2. **Exchange:** OKX EU, a través de `ccxt`.
3. **Pares:** solo `X/USDC` de una whitelist explícita de **8 monedas**. Nunca altcoin/altcoin ni ningún par fuera de la whitelist. Se valida al arrancar, en el generador de candidatos, en el motor de riesgo y justo antes de enviar la orden.
4. **Máximo 3 posiciones simultáneas.** Las órdenes de entrada pendientes cuentan como posición. Máximo 1 posición por símbolo. Prohibido promediar a la baja y la martingala.
5. **Capital inicial:** 50 $ (`initial_capital = 50`, `floor = 25`, en configuración; solo se cambian a mano).
6. **Equity** = USDC libre + Σ(cantidad × mejor bid) − comisiones estimadas de salida, calculado cada 15 s con datos del exchange.
7. **Suelo de 25 $:** si el equity ≤ 25 $ en dos lecturas consecutivas → modo `CLOSE_ONLY_CAPITAL`, **enclavado** (solo se sale con reset manual) + Telegram.
8. **Regla preventiva:** solo se abre una operación si, con todas las posiciones (incluida la nueva) cerradas en su stop, el equity queda ≥ 25 $ + 1 $ de colchón.
9. **Escalones de drawdown:** < 45 $ → riesgo por operación a la mitad + Telegram; < 40 $ → máximo 2 posiciones; < 35 $ → máximo 1 posición.
10. **Límite diario:** pérdida del día ≥ 3 $ → `CLOSE_ONLY_DAILY` hasta las 00:00 UTC.
11. **Máximo 6 operaciones al día.**
12. **Riesgo por operación:** 1 % del equity por defecto (modulado por el slider, entre 0,5 % y 1,5 %).
13. **Stop-loss y take-profit siempre en el exchange** (OCO u orden algorítmica), creados al abrir la posición.
14. **Cooldown:** 2 h en un símbolo tras un stop-loss; pausa de 4 h tras 3 pérdidas seguidas.
15. **Exposición máxima:** 90 % del equity. Como mucho 2 posiciones con correlación entre sí > 0,8 (7 días).
16. **No entrar** con spread > 0,10 % ni con objetivo esperado < 3× el coste de ida y vuelta.
17. **Riesgo de stablecoin:** si USDC se desvía > 1,5 % de su paridad → sin entradas nuevas.
18. **Presupuesto de Claude:** máximo 40 llamadas/día y 8 por ventana de 5 h (configurable).
19. **Claves de API:** permisos solo de lectura y trading (**nunca de retirada**), whitelist de IP del VPS, fuera del repositorio. La IA nunca ve claves ni variables de entorno.

## 5. Modos de operación

El modo efectivo es el más restrictivo de los que estén activos.

| Modo | Se activa | Abre | Cierra | Salida |
|---|---|---|---|---|
| `NORMAL` | Arranque correcto | Sí | Sí | — |
| `CLOSE_ONLY_QUOTA` | Cuota de Claude agotada, login caducado o error de autenticación de Claude | No | Sí, por reglas | Automática cuando una sonda a Claude responde bien |
| `CLOSE_ONLY_DEGRADED` | Datos obsoletos, errores repetidos del exchange, desfase del reloj | No | Sí | Automática tras X min con el sistema sano |
| `CLOSE_ONLY_DAILY` | Pérdida del día ≥ 3 $ | No | Sí | Automática a las 00:00 UTC |
| `CLOSE_ONLY_CAPITAL` | Equity ≤ 25 $ | No | Sí | **Solo manual** |
| `HALTED` | Kill switch o error crítico | No | Configurable | Manual |

Al entrar en cualquier modo `CLOSE_ONLY_*`: cancelar las órdenes de entrada pendientes, verificar que cada posición tiene su OCO en el exchange (y crearla si falta), gestionar las posiciones con reglas deterministas (trailing por ATR, time-stop, salida a mercado ante una flag crítica de hackeo o deslistado) y notificar por Telegram.

## 6. Papel de la IA

- Claude es un **analista**: elige entre candidatos ya filtrados por código, puntúa y justifica. **No emite órdenes, no crea pares y no modifica límites.**
- Se invoca con `claude -p`, salida JSON validada por esquema (`--json-schema`), **sin herramientas**, sin sesiones persistentes y desde un directorio vacío.
- Solo se invoca: (a) cuando hay candidatos nuevos, (b) en una revisión periódica de la cartera (cada 1–4 h), (c) en la revisión diaria de aprendizaje.
- La IA solo puede **reducir** el tamaño calculado por el motor de riesgo (multiplicador entre 0,5 y 1,0).
- Una salida inválida o un timeout se trata como "no hacer nada".
- Autenticación con `CLAUDE_CODE_OAUTH_TOKEN` (generado con `claude setup-token`, válido 1 año). Aviso por Telegram 14 días antes de que caduque.
- Las noticias son **solo un filtro de riesgo** (flags que bloquean o reducen entradas), nunca una señal de compra. Se tratan como texto no confiable.

## 7. Aprendizaje

- Registro de hipótesis con estados: `propuesta → en_prueba → validada | rechazada → aplicada → retirada`.
- La IA propone la hipótesis; **el código la evalúa** (condición medible, `min_n`, confianza estadística calculada).
- La evaluación se hace en sombra, sin cambiar el comportamiento, hasta que la hipótesis se valida.
- Una hipótesis validada solo puede añadir un filtro, ajustar un parámetro dentro de un rango predefinido o entrar en la memoria del prompt (5–10 reglas como máximo). **Nunca** toca las reglas duras.
- El bucle de aprendizaje no se activa hasta tener ≥ 100 operaciones registradas (sumando papel y real).

## 8. Baseline obligatorio

Desde el primer día corre en paralelo, en papel, un **baseline sin IA** con los mismos candidatos y el mismo motor de riesgo. El dashboard compara: equity real, baseline y *hold BTC*.

## 9. Notificaciones (Telegram)

Obligatorias: cierre de cada operación (par, resultado en $ y en R, motivo, duración), cambio de modo, parada del bot, bot caído (avisa el watchdog independiente), fallo de reconciliación, error de autenticación de Claude o de OKX, token de Claude a punto de caducar y resumen diario. Comandos opcionales, restringidos a tu `chat_id`: `/status`, `/pause`, `/closeonly`, `/kill`.

## 10. Interfaz

Dashboard web en tiempo real (FastAPI + WebSocket + SPA), accesible solo vía Tailscale o Cloudflare Tunnel con autenticación. Paneles:

- **Barra de estado:** equity, PnL del día, drawdown, distancia al suelo, operaciones hoy / 6, posiciones / 3, modo, llamadas a Claude hoy / presupuesto.
- **Slider de agresividad (5 niveles):** los cambios se aplican desde el día siguiente y nunca tocan las reglas duras.
- **Diagrama de flujo por nodos:** vista de sistema + vista por moneda.
- **"Qué está pensando la IA":** decisión, razones, candidatos rechazados y veredicto del motor de riesgo.
- **Controles de seguridad:** pausar, solo cierre, cerrar todo con doble confirmación, kill switch.
- **Posiciones abiertas**, con el estado de su OCO.
- **Histórico de operaciones cerradas**, con exportación CSV fiscal.
- **Curva de equity comparada** (real vs baseline vs hold BTC).
- **Hipótesis en curso** y **aprendido**, con confianza calculada por el código.

La UI es de solo lectura sobre el estado; sus comandos pasan por el motor de riesgo y se auditan.

## 11. Infraestructura

Oracle Cloud Always Free (ARM, región Madrid o Frankfurt) con IP fija. Despliegue reproducible (Docker Compose o script de instalación), servicios con systemd, `chrony` para el reloj y backup diario de la base de datos fuera del VPS. Plan B: VPS europeo de pago básico con el mismo despliegue.

## 12. Fases y criterios de avance

| Fase | Contenido | Criterio para avanzar |
|---|---|---|
| 0 | Cuenta en OKX EU (KYC), clave de API trade-only, VPS, bot de Telegram, token de Claude | Todo operativo (lo hace el propietario) |
| 1 | Ingesta de datos (WebSocket + REST), almacenamiento, detector de datos obsoletos | 72 h sin huecos |
| 2 | Features, filtros, candidatos, motor de riesgo, baseline en papel | Tests de propiedades en verde |
| 3 | Analista Claude en sombra, presupuesto de llamadas, máquina de modos | 1 semana estable; consumo de cuota medido |
| 4 | Ejecución en el demo de OKX: OCO, idempotencia, reconciliación, tests de caos | 1 semana sin descuadres |
| 5 | Dashboard, Telegram, watchdog | Todos los paneles con datos reales |
| 6 | Papel con datos en vivo: IA vs baseline vs hold BTC | 2–3 semanas |
| 7 | Dinero real (50 $), agresividad 1–2 | Revisión semanal |
| 8 | Bucle de aprendizaje | ≥ 100 operaciones |

## 13. Criterios de calidad

- Las reglas duras se cumplen siempre, verificado con tests basados en propiedades.
- Cada decisión es trazable de principio a fin (`decision_id`: candidato → llamada a la IA → veredicto → orden → fill → cierre).
- El estado real es siempre el del exchange (reconciliación al arrancar y cada 5 min).
- `risk/` no depende de `ai/`.
- Las notificaciones llegan de forma fiable, incluida la de bot caído.

## 14. Riesgos aceptados

- Uso de la suscripción de Claude en zona gris de los términos; se mitiga con un volumen bajo de llamadas, el binario oficial sin modificar y el token propio sin compartir.
- El tier gratuito de Oracle puede cambiar o reclamar la instancia; se mitiga con un despliegue reproducible y backups.
- La rentabilidad esperada es baja o negativa; el objetivo es el aprendizaje.
- Fiscalidad: cada venta tributa en el IRPF; el bot exporta un CSV fiscal desde el primer día.
