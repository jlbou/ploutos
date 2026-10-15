# PRD v3 — Ploutos: bot de trading spot de cripto, construido para escalar

**Version:** 3.0 BORRADOR (15/10/2026), pendiente de la aprobacion del propietario. Sustituira al PRD v2
(`docs/prd-ploutos-v2.md`) y al PRD v3 del 11/10 (archivado, `docs/archivo/propuesta-prd-v3.md`, que no llego a
aplicarse). **Sale de las decisiones del paso 1** (`docs/decisiones/01` a `09`); cada seccion dice de cual.
**Documento complementario:** `docs/informe-ploutos.md` (el *como*); si algo lo contradice, manda este PRD.

## 1. Objetivo (decisiones 1 y 2)

Un bot de trading **spot** de cripto, autonomo, que **gane dinero**: una estrategia pasa si **gana mas que mantener
BTC**, o **lo mismo con una caida claramente menor**, **medido en euros y neto de comisiones e impuestos**.

- **Construido para escalar:** nada depende de un capital concreto. Las reglas van en porcentajes; los estudios miden
  en porcentaje y con los costes de una cartera de **10.000 €** (el techo de disenyo). Con 1.000 € y 100.000 €, solo
  como informacion: nunca mueve el liston.
- **Antes de construir, demostrar:** primero una estrategia que pase un estudio con el criterio fijado antes de medir;
  despues el bot. Lo que no se ha demostrado no decide nada con dinero.

## 2. Usuario (decision 6)

El propietario, uso personal. **Sin ritmo fijo mientras se construye; cuando funcione, totalmente autonomo:** avisos
solo si algo va mal y un resumen semanal. Las decisiones de dinero (poner, retirar, parar) son siempre suyas.

## 3. Lo que cambia respecto al PRD v2

| Tema | v2 | v3 | Decision |
|---|---|---|---|
| Objetivo | aprender; la rentabilidad, secundaria | ganar a BTC (o lo mismo con menos caida), en euros, neto | 1 |
| Moneda de medida | dolares (USDC) | **euros** | 1 |
| Capital | 50 $, reglas en dolares | **escalable**: reglas en %, disenyado para 10.000 € | 1, 2 |
| Mercado | 8 monedas contra USDC | **BTC/EUR y ETH/EUR** | 3 |
| Apalancamiento y cortos | nunca | nunca, salvo lo que decida la exploracion con las condiciones fijadas | 4 |
| La IA | elige entre candidatos | **freno**: la estrategia funciona sin ella | 5 |
| Reglas duras | 19 | **17** (fuera la 14, la 17 y la correlacion de la 15) | 7 |
| Fases | papel 2-3 semanas, 50 $ | papel 6-12 meses, dinero real por escalones | 8 |
| Aprendizaje | bucle de hipotesis (fase 8) | **fuera** | 9 |
| Baseline | cartera sin IA en paralelo | la estrategia sin IA ES la base; la IA se mide contra ella | 5 |

## 4. Reglas duras (decision 7; ni la IA ni nadie las cambia desde el codigo)

Se conserva la numeracion del v2 para seguir el rastro en el codigo y los tests.

1. Sin apalancamiento. Solo spot: nunca margen, futuros ni prestamos (condiciones de revision: decision 4).
2. Exchange: OKX EU, via `ccxt`.
3. Solo **BTC/EUR y ETH/EUR**, validado en 4 puntos (arranque, generador de candidatos, motor de riesgo y justo antes de
   enviar la orden). La clave de OKX, limitada a BTC, ETH y EUR.
4. Maximo **1 posicion por moneda** (2 en total); las entradas pendientes cuentan. Prohibido promediar a la baja y la
   martingala. Anyadir a una posicion que gana, solo si la estrategia lo lleva escrito antes de medir.
5. **Capital de referencia en euros**, puesto a mano; **suelo al 50 %** de ese capital. Solo se cambian a mano.
6. `equity` = euros + Σ(cantidad × mejor bid en euros) − comisiones estimadas de salida, cada 15 s, con datos del
   **exchange** (el saldo total).
7. Equity ≤ suelo en **dos lecturas seguidas** → `CLOSE_ONLY_CAPITAL`, **enclavado** (solo reset manual) + Telegram.
8. Se abre solo si, con **todas** las posiciones (incluida la nueva) cerradas en su stop y con la comision de salida,
   el equity queda ≥ suelo + **2 %** del capital de referencia.
9. Escalones (en % del capital de referencia): **−10 %** → riesgo por operacion a la mitad + Telegram; **−20 %** →
   maximo 1 posicion; **−30 %** → maximo 1 posicion y riesgo a la mitad.
10. Perdida del dia (cerrado **y** abierto, desde las 00:00 UTC) ≥ **6 %** del capital de referencia →
    `CLOSE_ONLY_DAILY` hasta las 00:00 UTC.
11. Maximo **6 operaciones al dia** (cerradas mas vivas).
12. Riesgo hasta el stop: **lo fija el estudio antes de medir, con techo de 5 % del equity por posicion y 10 % entre
    las dos**. El deslizador del panel solo puede reducirlo.
13. **El stop, siempre en el exchange** desde que se llena la entrada, sin un momento sin el; el objetivo, si la
    estrategia lo tiene. Salida por senyal: cancelar la proteccion y vender a mercado.
14. *(retirada el 15/10: la cubren los escalones, el limite diario y el suelo)*
15. Exposicion maxima del **90 %** del equity.
16. No entrar con spread > **0,10 %**; con objetivo fijo, no entrar si el objetivo esperado es < **3×** el coste de ida
    y vuelta.
17. *(retirada el 15/10: no se opera en USDC)*
18. Presupuesto de la IA: maximo **40 llamadas al dia** y **8 por ventana de 5 h** (configurable), todas juntas.
19. Claves API: solo lectura y trading, **nunca retirada**, lista de IP del VPS, fuera del repositorio. La IA nunca ve
    claves ni variables de entorno.

Cada regla se comprueba en al menos dos sitios y tiene su test; la prueba de mutacion las rompe una a una.

## 5. Modos de operacion

El modo efectivo es el mas restrictivo de los activos. Al entrar en cualquier `CLOSE_ONLY_*`: cancelar las entradas
pendientes, verificar que cada posicion tiene su stop en el exchange (y crearlo si falta), gestionar con reglas
deterministas y notificar.

| Modo | Se activa | Abre | Cierra | Salida |
|---|---|---|---|---|
| `NORMAL` | arranque correcto | si | si | — |
| `CLOSE_ONLY_QUOTA` | presupuesto o acceso de la IA agotado; *propuesta (sin decidir):* solo si el bot usa a la IA para decidir | no | si | automatica, al volver |
| `CLOSE_ONLY_DEGRADED` | datos obsoletos, errores repetidos del exchange, desfase del reloj | no | si | automatica, tras un rato sano |
| `CLOSE_ONLY_DAILY` | regla 10 | no | si | 00:00 UTC |
| `CLOSE_ONLY_CAPITAL` | regla 7 | no | si | **solo manual** |
| `CLOSE_ONLY_MANUAL` | pausa del propietario (Telegram o panel) | no | si | manual |
| `HALTED` | parada de emergencia o error critico | no | configurable | manual |

## 6. La IA (decision 5)

- **La estrategia funciona sin IA.** La IA puede: filtrar noticias, reducir o aplazar una compra, explicar lo que pasa.
  **Nunca** anyade riesgo ni decide sola que algo es "muy seguro".
- Todo uso de la IA que afecte a decisiones se prueba **primero en sombra** contra la estrategia sin IA, con un criterio
  escrito antes. Ideas a estudiar con condiciones: que **apruebe** operaciones (es un freno) o que las **potencie** (anyade
  riesgo: mismas condiciones que el apalancamiento de la decision 4), y un modelo de **scikit-learn** (una variante de
  estrategia mas, con las skills de ml4t).
- Se invoca con `claude -p`, salida validada por esquema, sin herramientas, sin sesion y desde un directorio vacio;
  salida invalida o timeout = **no hacer nada**. Version fijada. Las noticias son texto no confiable.

## 7. La estrategia y el estudio (paso 2)

- **Criterio fijado y subido a git ANTES de medir.** Primero se calcula cuantos anyos de datos hacen falta para pasar
  el liston; los datos no vistos se usan **una sola vez**; **todos** los intentos cuentan (N >= 35 al empezar); se
  evalua **por tipo de mercado**.
- **Datos:** la historia larga contra USDT (BTC y ETH desde 10/2017) pasada a euros; la historia contra euro (desde
  11/2023) y los libros de ordenes en euros, para los costes. Datos limpios: lo anterior a 12/2020 y lo que venga.
- **El estudio simula las reglas** (escalones, limite diario, suelo, riesgo y exposicion): lo que se mide es la
  estrategia como la ejecutaria el bot. Una estrategia no pasa si su peor caida historica se acerca al suelo.
- **Apalancamiento y cortos** (decision 4): solo con las condiciones escritas; se decide entre la exploracion y la
  prueba limpia, antes de mirarla.

## 8. Fases y criterios de avance (decision 8)

| Paso | Contenido | Para avanzar |
|---|---|---|
| Estudio | la estrategia, con el criterio fijado antes | pasa el liston de la seccion 1 |
| Construir | la estrategia en el bot, con la **prueba de oro** | el bot y el simulador dan lo mismo con las mismas velas |
| Demo | la mecanica en el demo de OKX (ordenes, stops, euros) | sin descuadres; los caos de la estrategia |
| Papel | hacia adelante, con datos nuevos | **6 meses y al menos un cambio de tipo de mercado** (max. 12), con el criterio fijado antes |
| Dinero real | poco al principio (la cifra, del propietario) | **se dobla cada 3 meses solo si el tramo cumple**: resultado dentro de lo normal del estudio, sin incidencias, caida no peor que la peor del estudio. Nunca > 10.000 € sin un estudio nuevo |

## 9. Notificaciones (Telegram)

Obligatorias: cada operacion (*propuesta (sin decidir):* al abrir y al cerrar, no solo al cerrar como en el v2; con el resultado en euros y en %), cambio de modo, bot caido (avisa el
vigilante externo), fallo de conciliacion, error de acceso a la IA o a OKX, token de la IA a punto de caducar y un
**resumen semanal**. Comandos solo desde el chat del propietario: `/status`, `/pause`, `/kill`, `/resume`.

## 10. Interfaz (se rehace en el paso 3, con la estrategia)

Panel de solo lectura, solo por la red privada (Tailscale); **antes del dinero real, que solo responda a su propio
nombre** (el hueco de DNS rebinding pendiente). Lo que tiene que ensenyar: equity en euros, caida, distancia al suelo y
a los escalones, posiciones con su stop en el exchange, operaciones cerradas, la curva frente a BTC mantenido (en
euros), el estado de cada servicio y el CSV fiscal en euros.

## 11. Infraestructura

VPS europeo de pago, despliegue reproducible (script de instalacion y systemd), reloj con `chrony`, copias diarias
fuera del VPS verificadas y un simulacro de restauracion. Un vigilante externo (Healthchecks) avisa si algo deja de
latir.

## 12. Criterios de calidad

- Las reglas duras se cumplen siempre (tests de propiedades y prueba de mutacion).
- Cada decision se puede seguir de principio a fin (`decision_id`: senyal → riesgo → orden → fill → cierre).
- El estado verdadero es el del exchange (conciliacion al arrancar y cada 5 min).
- `risk/` no depende de `ai/`.
- **La prueba de oro:** el bot hace exactamente lo que el simulador.
- **El repositorio es publico:** sin datos personales ni nada con forma de secreto (hay tests).

## 13. Riesgos aceptados

- Puede no haber ninguna estrategia que pase: entonces no hay bot con dinero (y se dice).
- Los datos limpios son pocos: el estudio puede acabar en "no se puede demostrar, solo papel".
- Uso de la suscripcion de la IA en zona gris de los terminos; se mitiga con pocas llamadas, el binario oficial y el
  token propio.
- Fiscalidad: cada venta tributa en el IRPF; el bot exporta el CSV fiscal en euros.

## 14. Sin comprobar (antes de usarlo)

- Las comisiones de OKX para BTC/EUR y ETH/EUR (`account/trade-fee` con la clave).
- Si el demo de OKX tiene BTC/EUR y ETH/EUR.
- Si OKX spot deja dos stops de venta a la vez sobre la misma cantidad (o si hay que modificar el que hay).
- Que la historia contra USDT pasada a euros se parezca a la de BTC/EUR donde coinciden.
- La profundidad de los libros en euros en momentos de panico (solo una foto del 15/10).
