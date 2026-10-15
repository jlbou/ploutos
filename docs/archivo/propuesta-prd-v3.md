# PRD v3 para L: APROBADO por el propietario el 11/10/2026 (se aplica solo si L pasa su papel)

**Estado: APROBADA por el propietario el 11/10/2026, los 15 cambios** (seis decisiones, una a una: 1 objetivo y riesgos; 2 L
como estrategia, sin slider, con las referencias de mantener y L en el panel; 3 la IA solo en el embudo de noticias;
4 la regla 12 al 5 % por posicion y 15 % en total; 5 la OCO, las pausas y los modos de solo cierre sin time-stop; 6 la
fase 7 con el papel de L como requisito y su decision expresa). El propietario pregunto si las otras dos carteras desaparecen:
si, pero no ahora (se decide el dia del veredicto de la fase 6, D1 del dossier).
El PRD v2 (`docs/archivo/prd-ploutos-v2.md`) sigue siendo la fuente de verdad hasta que se aplique. **Aprobarla no pone nada
en marcha:** solo se aplicaria si L pasa su papel (11/01/2027) y el propietario decide ir al
dinero real; y nada del bot se toca mientras dure la muestra de la fase 6 (huella `f063d80147a9`).

**Por que.** el propietario (09/10): "El meu objectiu es que el bot sigui rentable, que guanyi diners [...] algunes opinions han
canviat". La primera version de esta propuesta (09/10) era para "una estrategia de tendencia"; desde el 10/10 la
candidata es **L** (`docs/archivo/diseno-tendencia-2.md`), en papel del 12/10/2026 al 11/01/2027 (`docs/diseno-papel-l.md`).
Lo que NO cambia: la seguridad (las reglas duras, salvo la 12) y la trazabilidad.

## Lo que es L, en una linea

Cada lunes a las 00:00 UTC, con el cierre del domingo: de las 8 monedas, hasta 3 que esten por encima de sus medias
de 20, 50, 100 y 200 dias (si BTC lo esta en al menos 2), las mas por encima primero; 30 % del equity cada una; stop
a 3 ATR diarios y objetivo a +100 % en el exchange; las que dejan de cumplir se venden el lunes siguiente. Sin IA.

## Lo que se sabe de L (para leer los cambios con esto delante)

- Exploracion 12/2020-08/2025: 50 -> 421 $, caida 44,5 % (BTC 77 %), deflactado 0,978. **Anyo USDC 09/2025-09/2026:
  -6,9 % (BTC -22 %), caida 20,5 % (BTC 53 %): NO paso** el criterio (perdio). Robusta: las 12 variantes pasan la
  exploracion; las cifras exactas, inciertas (el anyo USDC va de -7 a +13 % segun el dia de la semana).
- **Protege bien en las caidas; ganar dinero, no esta demostrado con datos limpios.** Por eso el papel.

## Los cambios, uno a uno

| # | Seccion del PRD | v2 | Propuesta v3 (con L) | Por que |
|---|---|---|---|---|
| 1 | 1. Objetivo | "La rentabilidad es secundaria"; exito = reglas, trazabilidad y saber si la IA aporta | **El objetivo es ganar dinero** con caidas mucho menores que mantener BTC. Las reglas y la trazabilidad pasan a ser CONDICIONES | lo pide el propietario |
| 2 | 2-3. Estrategia y frecuencia | setups de 4 h (pullback, ruptura, reversion), 1-5 operaciones al dia | **L**: rotacion semanal (lunes 00:00 UTC) con los 4 plazos; unas 13-30 operaciones al anyo (130 en los 4,7 anyos de la exploracion; 13 en el anyo USDC) | lo medido: lo de 4 h pierde; L es lo unico que paso la exploracion |
| 3 | 6. La IA | analista: elige entre candidatos; medir si aporta es un objetivo | **L no usa la IA para elegir.** La IA, solo en el **embudo de noticias** (veredicto final: frenar compras o, con un "si" critico, vender), primero en sombra. Solo puede frenar, nunca comprar. Volver a darle la eleccion solo si la fase 6 dijera "aporta" y se midiera antes dentro de L | el propietario, 11/10; la IA no crea una ventaja que la estrategia no tiene |
| 4 | 4. Regla 12 | riesgo por operacion 1 % (0,5-1,5 % con el slider) | **riesgo hasta el stop por posicion, como mucho el 5 % del equity; la suma, como mucho el 15 %** | con el stop de 3 ATR diarios (~12-18 %), una posicion del 30 % arriesga 4-5 %; con el 1 %, serian 3-4 $ |
| 5 | 4. Regla 13 | stop y objetivo en el exchange (OCO) al abrir | **igual:** OCO con el stop a 3 ATR diarios y el objetivo a +100 %. En la rotacion del lunes: cancelar la OCO y vender a mercado | sin cambio de fondo |
| 6 | 4. Regla 14 | 2 h sin entrar tras un stop; 4 h de pausa tras 3 perdidas | **igual, y L es mas estricta:** tras un stop, esa moneda no vuelve hasta el lunes siguiente | ya lo hace L |
| 7 | 4. Reglas 1-11 y 15-19 | - | **igual** (3 posiciones; suelo de 25 $ enclavado; preventiva >= 26 $; escalones; perdida del dia 3 $; tope de 6 operaciones al dia, que el lunes de L llega como mucho a 6: 3 ventas y 3 compras; exposicion 90 % y correlacion; spread; USDC; presupuesto de la IA; claves sin retirada) | la seguridad no cambia; L se midio con ellas |
| 8 | 5. Modos | gestion de CLOSE_ONLY con "trailing por ATR, time-stop" | en CLOSE_ONLY_*: el lunes **no se compra**; las ventas de la rotacion, los stops y los objetivos siguen. **Sin time-stop** (medido el 07/10: empeora) | coherente con "solo cierre" |
| 9 | Slider de agresividad (1-5) | modula el riesgo (0,5-1,5 %) y los setups | **se quita** (o queda fijo): L se midio con un tamanyo; un slider seria otra estrategia sin medir | no anyadir lo no medido |
| 10 | 8. Comparacion | baseline sin IA; hold BTC | **referencias: mantener BTC, mantener BTC + ETH y quedarse en USDC.** El baseline sin IA desaparece (L ya no tiene IA que comparar) | lo que importa para el objetivo nuevo |
| 11 | 6. Noticias | solo filtro de riesgo; flag critica con posicion = vender | **igual, y se anyaden los medios por el embudo** (`docs/diseno-embudo-noticias.md`): primero en sombra; activo solo si en enero quita al menos el 80 % de las falsas alarmas sin perder ninguna real (el propietario etiqueta a ciegas). Los anuncios de OKX, activos desde el dia 1 | el propietario, 11/10 |
| 12 | 12. Fase 6 | papel IA vs baseline | **sigue hasta su veredicto** (probablemente el 20/11); despues, lo del dossier (`docs/archivo/dossier-veredicto-fase-6.md`): lo recomendado es retirar las dos carteras viejas | no partir la muestra |
| 13 | 12. Fase 7 (dinero real) | 50 $, agresividad 1-2, revision semanal | **requisito: L pasa su papel** (12/10/2026-11/01/2027: no pierde y cae como mucho 2/3 de lo que cae BTC; corte al 25 %) **y el propietario lo decide** sabiendo que el anyo USDC no lo paso. Despues: las ordenes probadas en el demo, la clave real (8 monedas y USDC, sin retirada) y 50 $. **Mas capital, solo tras meses reales que cumplan lo esperado** y con decision expresa del propietario | ganar dinero sin pruebas limpias es apostar; el limite lo pone el capital |
| 14 | 14. Riesgos | "la rentabilidad esperada es baja o negativa; el objetivo es el aprendizaje" | **"L puede perder (el anyo USDC perdio un 7 %). La ganancia depende de que la cripto suba a largo plazo; L sobre todo cae menos. Lo maximo que se puede perder con 50 $ es ~25-27 $ (regla 7)."** | decirlo claro |
| 15 | 10. Panel | el de las carteras de la fase 6 | **L como cartera principal** (ya esta su tarjeta desde el 10/10); el resto, segun el dossier del veredicto | lo que se use |

## Lo que se queda fuera a proposito

- **Apalancamiento y cortos (regla 1):** no crean ventaja (medidos dos veces) y aceleran las perdidas.
- **Quitar el suelo, el limite diario o los escalones:** son lo que permite equivocarse sin perderlo todo.
- **Retocar L** (otro dia de la semana, otros plazos): la robustez del 10/10 dice que la idea es solida, pero elegir la
  variante que mejor salio seria volver a buscar.
- **Mas capital desde el principio.**

## Lo que haria falta construir si L pasa (despues del papel)

1. `docs/prd-ploutos-v3.md` con los cambios aprobados.
2. L en el bot, en una rama: la rotacion semanal, la regla 12 nueva (tests primero en `risk/` y la mutacion 16/16), la
   OCO de 3 ATR / +100 %, la venta de la rotacion, los modos y los jueces.
   El corte del 25 % de caida, medido con el equity de CADA vela, no con los cierres diarios del papel (el propietario, 15/10,
   revision 6).
   La regla 10 como en el simulador de L: la perdida del dia con el equity (realizado Y abierto) frente al del inicio
   del dia UTC, no solo lo cerrado como en las carteras de la fase 6; tests primero y mutacion (el propietario, 15/10, revision 8).
3. El demo para probar las ordenes (solo tiene 5 de las 8 monedas: sirve para la mecanica), con los caos de L: parar
   a mitad de rotacion, que falle la venta tras cancelar la OCO, que OKX rechace la OCO (el propietario, 11/10).
4. La clave real, que pone el propietario.
