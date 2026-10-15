# Diseno: el bucle de aprendizaje (fase 8)

Estado: **DECIDIDO por el propietario el 25/09/2026: 1a, 2a, 3a y 4a** (seccion 8): dos etapas (historia con
parte reservada y sombra en vivo); solo a la cartera de la IA, el baseline congelado; el propietario aprueba cada
aplicacion; como mucho 3 en prueba y memoria de 5. No hay codigo, ni lo habra
hasta la fase 8: el PRD no lo activa hasta tener >= 100 operaciones.
PRD seccion 7 y 6 (c: "revision diaria de aprendizaje"); informe 1.8.

## 1. Lo que dice el PRD

- Registro de hipotesis: `propuesta -> en_prueba -> validada | rechazada -> aplicada -> retirada`.
- La IA propone; **el codigo evalua** (condicion medible, `min_n`, confianza calculada).
- Evaluacion **en sombra**, sin cambiar el comportamiento, hasta validar.
- Una validada solo puede: anyadir un filtro, ajustar un parametro dentro de un rango predefinido
  o entrar en la memoria del prompt (5-10 reglas). **Nunca** toca las reglas duras.
- No se activa hasta >= 100 operaciones (papel y real).

El informe anyade: condiciones en campos, no en prosa; confianza por bootstrap o Beta; correccion
por comparaciones multiples (como mucho ~5 a la vez); caducidad; memoria acotada.

## 2. El problema de fondo: los numeros (medidos)

Con el anyo de datos (docs/archivo/propuesta-time-stop.md, 159 operaciones del baseline):

- **Una operacion da -0,38 R de media con una desviacion de 1,97 R.** Es muy ruidosa: la mayoria
  pierden 1,3 R y unas pocas ganan 3,4 R.
- Para saber la media de UN grupo con +-0,3 R (90 %) hacen falta **~117 operaciones**. Para saber
  si una condicion cambia el resultado en 0,3 R (comparar dos grupos) hacen falta **~234 en cada
  grupo**; para 0,5 R, ~84 en cada uno.
- El bot hace **~160 operaciones al anyo** (~200 candidatos). Una condicion que afecte a 1 de cada
  4 candidatos junta ~50 al anyo: **validarla solo con datos en vivo costaria de 2 a 5 anyos.**

Conclusion honesta: **un bucle que solo mire en sombra lo que pasa en vivo no validara casi nada**,
y el riesgo contrario es peor: con pocas operaciones, alguna hipotesis saldra "valida" por azar, y
la IA la explicara de forma muy convincente (informe 1.8).

## 3. La propuesta

### La unidad: el candidato, no la operacion

Como en la fase 6 (M1), cada candidato tiene un resultado **contrafactual**: que habria pasado si
se hubiera abierto, simulado contra las velas con las mismas suposiciones que el simulador. Asi
cuentan tambien los que no se abrieron (cartera llena, IA que los salto): ~200 al anyo en vez de
~160, y sin sesgo por lo que se eligio.

### Dos etapas (decision 1)

1. **Criba con historia.** Cada hipotesis se mide primero sobre la historia (contra USDC solo hay un
   anyo; contra USDT, de 5 a 8, medido el 25/09: ver `docs/hallazgos-fase-3-4.md` 5b). La historia se parte en dos: una parte para
   explorar y otra **reservada que solo se mira UNA vez por hipotesis**, al final. Si no aguanta en
   la reservada, se rechaza. Da respuesta en minutos, no en anyos.
2. **Confirmacion en sombra, en vivo.** Si pasa la criba, se marca en vivo sin cambiar nada hasta
   su `min_n` (menor que sin criba: ahora solo hay que confirmar que el efecto no ha desaparecido).

Es exactamente la herramienta que hace falta para **revisar la estrategia antes de la fase 7**
(decision del propietario del 25/09): se construye una vez, para la revision, y el bucle la reutiliza.

### La hipotesis, en campos

La IA la escribe en un JSON con esquema, y el codigo la valida contra un **catalogo cerrado** de
campos que existen al decidir (setup, moneda, regimen, ATR en %, RSI, distancia a la media, spread,
hora UTC, tendencia de BTC...). Un campo que no esta en el catalogo = hipotesis rechazada sin
evaluar. Ejemplo:

```json
{"tipo": "filtro", "condicion": [["setup", "=", "pullback_trend"], ["btc_tendencia_4h", "=", "bajista"]],
 "efecto": "no entrar", "metrica": "R medio", "min_n": 100, "caduca": "2027-06-30",
 "por_que": "texto libre: se guarda, no se evalua"}
```

Un parametro solo se puede mover dentro de un rango escrito en `settings.yaml` (por ejemplo, el
multiplo de ATR entre 1,5 y 2,5); la IA no puede ampliar el rango.

### Cuando es "valida"

La calcula el codigo, por bootstrap por dias (como el juez de la fase 6):
- filtro "no entrar si X": los candidatos con X pierden de verdad (intervalo del 90 % del R medio
  entero por debajo de 0) **y** son peores que el resto;
- parametro: el nuevo valor mejora el R medio con el intervalo entero por encima de 0;
- **correccion por comparaciones:** como mucho **3 hipotesis en prueba a la vez**, y el intervalo se
  ensancha segun cuantas se han probado en total (Bonferroni), no solo las activas.

### Memoria del prompt

Como mucho 5 reglas (el PRD permite 5-10), las de mayor confianza calculada. Cada una caduca: se
remide cada 4 semanas y se retira si deja de cumplirse.

### Cuando llama a la IA

Una llamada al dia (la "revision diaria" del PRD 6), dentro del presupuesto de 40: recibe el
resumen de lo cerrado y de las hipotesis en curso, y propone como mucho UNA hipotesis nueva.

## 4. A que cartera se aplica (decision 2)

Si una regla aprendida se aplica tambien al baseline, el grupo de control deja de ser "sin IA"
(la regla la propuso la IA) y la comparacion pierde sentido. Propuesta: **solo a la cartera de la
IA; el baseline se queda congelado** como control. Asi, lo que se compare en adelante sera "IA +
aprendizaje" contra "reglas fijas", que es la pregunta que importa.

## 5. Quien la aplica (decision 3)

El PRD quiere un bot autonomo, pero cada regla aplicada **cambia la estrategia** y parte en tramos
cualquier comparacion en curso. Seran pocas (con estos numeros, unas pocas al anyo). Propuesta: el
codigo valida y **el propietario aprueba cada aplicacion** con un mensaje (Telegram o panel), viendo los
numeros. Aprobar no puede saltarse nada: solo decide entre "aplicar" y "no aplicar" algo que ya
paso la validacion.

## 6. Lo que NO puede hacer nunca

Tocar las 19 reglas duras, los limites de `settings.yaml` que no tengan rango de aprendizaje, la
whitelist, el slider o el presupuesto de la IA. Se comprueba como las demas invariantes: con un
test de arquitectura (`learning/` no puede escribir configuracion) y con el juez.

## 7. El juez

`check_aprendizaje.py`: rederiva cada hipotesis desde los datos (sin fiarse de lo guardado), comprueba
que ninguna se aplico sin validar ni sin la aprobacion del propietario, que la parte reservada se miro una
sola vez por hipotesis, que ningun parametro salio de su rango y que la memoria no pasa de 5.

## 8. Decisiones para el propietario

**1. Donde se prueban las hipotesis.**
- a) **En dos etapas: criba con la historia (con una parte reservada) y confirmacion en sombra en
  vivo** (recomendado).
- b) Solo en sombra, en vivo, como dice el PRD (de 2 a 5 anyos por hipotesis).

**2. A que cartera se aplica lo aprendido.**
- a) **Solo a la de la IA; el baseline queda congelado como control** (recomendado).
- b) A las dos.

**3. Quien aplica una hipotesis validada.**
- a) **El codigo valida y el propietario aprueba cada aplicacion** (recomendado).
- b) Automatico, sin intervencion.

**4. Cuantas a la vez.**
- a) **Como mucho 3 en prueba, y memoria de 5 reglas** (recomendado): con tan pocas operaciones, cada
  hipotesis de mas es una oportunidad mas de "validar" algo por azar.
- b) 5 en prueba y memoria de 10, como el informe y el maximo del PRD.
