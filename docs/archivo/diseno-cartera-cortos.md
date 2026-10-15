# Diseno: una tercera cartera de papel, solo de cortos, en sombra (28/09/2026)

**Estado: DISENYO, sin construir ni desplegar. El estudio NO paso (28/09, `plan-segunda-ronda-estrategia.md` 5b): no se
construye.** el propietario, 28/09: estudio de los cortos ya y, en paralelo, preparar
esta cartera; **no se despliega hasta que el estudio pase su criterio** (`docs/archivo/plan-segunda-ronda-estrategia.md`,
5b). La regla 1 no cambia: esta cartera es PAPEL, como las otras dos, y no manda nada a OKX.

## 1. Que es y que no

- Una cartera de 50 $ ficticios que **solo abre cortos, y solo con BTC bajo su media de 200 dias**: el espejo de
  los tres setups actuales, lo mismo que mide el estudio. Sin IA (como el baseline): lo que se quiere saber es si
  la idea funciona en vivo, no si la IA la mejora.
- **No toca las otras dos carteras** ni su codigo de decision: la muestra de la fase 6 no se parte. Es un servicio
  aparte (`ploutos-paper-cortos`) con su base (`var/ploutos-paper-cortos.db`), como la de la IA.

## 2. Como (dos caminos)

**A. El espejo de precios, como el estudio (recomendado para empezar).** El servicio lee las velas de la ingesta,
las pasa a C/precio al vuelo (el maximo pasa a ser el minimo) y usa el MISMO bucle, simulador y motor de riesgo
que las otras dos carteras, sin cambiar ni una linea suyo. Una capa fina traduce al guardar: precios, P&L y R de
cada operacion se escriben ya como CORTO real (la formula del estudio, con test), para que el juez, el panel y
Telegram vean numeros de verdad.
- A favor: cero cambios en el codigo que usan las carteras de la fase 6; se prueba lo mismo que se midio.
- En contra: dentro del bucle, el equity y las reglas en dolares (suelo, perdida diaria, escalones) se calculan
  sobre los precios invertidos: se parecen al corto real, pero no son identicos (la diferencia crece con el
  movimiento). Para una cartera en sombra, sin dinero, es aceptable **si se dice**; para dinero real, no.

**B. Cortos de verdad en el simulador y el motor de riesgo.** Una posicion con lado (largo o corto), stop por
encima, P&L invertido, financiacion cada 8 h y las 19 reglas pensadas para los dos lados.
- A favor: exacto; es lo que haria falta de todos modos antes de operar cortos con dinero.
- En contra: toca `portfolio/paper.py` y `risk/`, el codigo que usan las carteras de la fase 6 (mas riesgo de
  romper algo a mitad de la muestra) y exige repasar las 19 reglas y su prueba de mutacion. Varios dias.

**Recomendado: A ahora** (si el estudio pasa), **B solo si los cortos llegan a plantearse con dinero**, despues de
la fase 6 y con la regla 1 decidida por el propietario.

## 3. Piezas (camino A)

| # | Pieza | Que hace |
|---|---|---|
| 1 | `portfolio/espejo.py` | Pura: vela -> vela invertida, y operacion invertida -> operacion corta real (la cuenta del estudio, con tests) |
| 2 | `scripts/run_paper_cortos.py` | El `PaperRunner` con las velas invertidas y el filtro de BTC (solo con BTC bajista); `DECIDER = "cortos"` |
| 3 | Base propia + migracion | Las mismas tablas de papel; las operaciones, guardadas como corto real |
| 4 | Juez | `check_paper.py --decider cortos` audita sobre las velas invertidas (las mismas que vio el bucle) y comprueba la traduccion |
| 5 | Panel y Telegram | Una tercera fila en la barra y en la curva ("Cortos (sombra)"); avisos con la etiqueta "sombra" |
| 6 | Despliegue | `deploy/ploutos-paper-cortos.service` (`MemoryMax`, `OOMScoreAdjust`), latido a Healthchecks (7a comprobacion) y copia de la noche |

Coste en el VPS: ~190 MB mas (lo que ocupa cada cartera). Hay ~1 GB libre.

**Ojo con cuando empezaria a hacer algo (medido el 28/09, velas diarias de BTC-USDT, API publica de OKX):** BTC
cierra en 84.479 $, un **18,8 % por ENCIMA** de su media de 200 dias (71.110 $); alcista desde el 19/08/2026. Hoy
la cartera de cortos no abriria nada: empezaria cuando BTC cruzara por debajo. De los ultimos 100 dias, 60 fueron
bajistas: pasa a menudo, pero no se sabe cuando.

## 4. Decisiones para el propietario (cuando el estudio haya pasado)

1. **Camino A o B** (recomendado: A).
2. **Cuanto tiempo en sombra antes de hablar de dinero** (propuesta: lo mismo que la fase 6, minimo 3 semanas, y
   con al menos un tramo de BTC bajista: sin tramo bajista, la cartera no abriria nada y no se aprenderia nada).
3. **Si entra en el panel y en el resumen diario de Telegram**, o solo en el juez.
