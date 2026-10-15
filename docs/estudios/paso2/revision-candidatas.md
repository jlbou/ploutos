# Revision de las candidatas antes de construir el simulador (16/10/2026)

Con las skills ml4t-lookahead-bias y ml4t-backtest-overfitting, sobre la seccion 8 del plan congelado
(`docs/plan-estudio-paso-2.md`, etiqueta `criterio-paso2`). **Todavia no se ha medido nada**: lo que se aclara aqui no
viene de ver datos. Una regla escrita a medias deja al simulador elegir, y elegir despues es un intento escondido.

## Lo que esta bien

- **Sin informacion del futuro:** las tres senyales usan solo cierres hasta el dia t; la orden va a la apertura de
  t+1. Las rupturas de H2 comparan con los maximos de los N dias ANTERIORES (sin el de hoy).
- **Sin parametros afinados:** los plazos (20/50/100/200; 1-4 semanas) y el 60 % vienen de la literatura o de L.
- **Pocos intentos:** 5; cada plazo de H2 no es un intento aparte porque van juntos y fijos.

## Lo que falta definir (huecos, sin decidir)

| # | Hueco | Por que importa | Propuesta |
|---|---|---|---|
| C1 | **Volver a entrar tras un stop** | sin la regla 14, H1 volveria a comprar al dia siguiente si sigue sobre las medias: se repite el mismo golpe | **Solo con una senyal nueva:** la senyal tiene que apagarse y volver a encenderse (en H3, el lunes siguiente) |
| C2 | **Que es "riesgo a la mitad"** (escalones, regla 9) | puede ser la mitad del tamanyo o la mitad del riesgo hasta el stop, y no dan lo mismo | **Las dos:** el tope por moneda pasa del 45 % al 22,5 % y el del riesgo, del 5 % al 2,5 % |
| C3 | **Como salta el stop en una vela diaria** | con una vela no se sabe a que hora toco el stop | si el minimo del dia <= stop: **sale al stop, o a la apertura si abrio por debajo** (el hueco); sin objetivo, no hay empates |
| C4 | **A que tipo de mercado va cada dia** | clasificar el dia con su propio cierre es mirar el final del dia | **con el cierre de AYER** de BTC/EUR y su media de 200 dias |
| C5 | **Que equity se usa para el tamanyo** | el de hoy (con el precio que aun no ha llegado) seria futuro | **el equity al cierre del dia t** (el de la senyal), con las comisiones de salida |
| C6 | **Tamanyos parciales de H2 y H3** (25 %, 50 %...) | cada cambio de un cuarto es una operacion con su coste | **se ajusta solo si cambia la fraccion**; una diferencia menor que el minimo por orden de OKX no se opera |
| C7 | **El limite diario (regla 10) en un sistema diario** | ¿que dia cuenta? | desde las 00:00 UTC con el equity de ese momento; si salta, ese dia no se abre ni se aumenta nada |
| C8 | **BTC mantenido de referencia** | desde cuando y con que costes | compra a la apertura del primer dia del tramo (taker y deslizamiento), vende al cierre del ultimo, y paga el impuesto entonces |
| C9 | **El PBO con solo 5 configuraciones** | con tan pocas, el PBO dice poco | se calcula igual (validacion combinatoria, 8 trozos) y **se dice que es poco informativo**; no cambia el liston |
| C10 | **La primera ETH de Bitstamp** (16/08/2017) en la exploracion no influye, pero ETH solo tiene 200 dias de historia el 04/03/2018 | la media de 200 dias de ETH sale justa en el primer dia de la prueba limpia | bien asi; **se comprueba con un test** que ninguna media se calcula con menos dias de los que dice |

## Lo que no se toca

El liston, las hipotesis, los plazos, el 60 %, las fechas y los costes: lo congelado sigue igual. Si el propietario
aprueba C1-C10, se anyaden al plan como **aclaracion 1** y se pone una etiqueta nueva (`criterio-paso2-a1`) antes de
medir.
