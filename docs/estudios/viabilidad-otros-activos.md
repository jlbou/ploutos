# Viabilidad de un bot aparte con otros activos (no cripto)

Pedido por el propietario el 06/10/2026, despues de un anuncio de un bot "TradeGPT" (divisas y oro, 23 h al dia, operaciones de
horas). **Es un estudio de papel: no se ha programado nada ni se ha abierto ninguna cuenta.** Precios leidos el 06/10 en
las paginas publicas de Interactive Brokers Irlanda (la entidad que da servicio a clientes de la UE); lo que no se ha
comprobado se dice.

## 1. Lo que encontre del anuncio

- El regulador britanico (FCA) tiene avisos contra **"TradeGPT / tradegpt-ai.net"** (desde el 17/07/2025) y **"Trade
  Gpt UK"**: no autorizadas. Hay un analisis de **trade-gpt.fr** como estafa de "robot de trading con IA".
- **En Espanya la publicidad de CFD a minoristas esta PROHIBIDA** desde 2023 (resolucion de la CNMV del 11/07/2023, en
  el BOE el 14/07): ni anuncios al publico general, ni patrocinios, ni famosos. Un bot de divisas y oro para un
  particular es, casi siempre, un CFD. **Un anuncio asi en Espanya es de una entidad que no esta autorizada aqui, o de
  una que se salta la norma.** Cualquiera de las dos es motivo para no seguir.
- La CNMV dice que entre el **70 y el 90 %** de las cuentas de minoristas pierden dinero con CFD (segun la entidad).

## 2. Cada activo, sin apalancamiento (como la regla 1 de Ploutos) y con el

| Activo | Sin apalancamiento | Coste minimo por orden (IBKR) | Para que la comision sea <= 0,10 % por lado | Horario |
|---|---|---|---|---|
| Acciones espanyolas (BME) | si | 0,05 %, **minimo 3 €** | posiciones de **3.000 €** | ~8,5 h, dias laborables |
| Acciones alemanas (Xetra), tarifa escalonada | si | 0,05 %, **minimo 1,25 €** | **1.250 €** | ~8,5 h |
| Acciones de EE. UU. (fracciones) | si | hasta el 0,5-1 % en ordenes pequenyas (el tope) | ~1.000 $ o mas | 6,5 h (15:30-22:00 aqui) |
| Divisas al contado | **si**, convirtiendo divisa con saldo propio (que se pueda en una cuenta sin margen, no lo he comprobado) | 0,002 %, **minimo 2 $** | **2.000 $**; pero un par mayor se mueve ~0,5 % al dia, asi que hace falta ~0,02 % -> **10.000 $** | 24 h, 5 dias |
| Oro al contado (Loco London) | si, en teoria (IBKR lo lista; no he comprobado si una cuenta de la UE puede) | 0,015 %, **minimo 2 $** | **2.000 $** | ~24 h, 5 dias |
| Micro futuro de oro (10 onzas) | **no**: un futuro siempre es apalancado | 0,25 $ + tasas por contrato | barato en %, pero cada contrato son 10 onzas (decenas de miles de dolares) | **~23 h, 5 dias**: probablemente el "23 h" del anuncio |
| CFD (divisas, oro, indices) | **no** | sin comision; el coste va en el spread | - | ~24 h, 5 dias |

Limites de apalancamiento de los CFD en la UE (ESMA, minoristas): 30:1 en divisas mayores; 20:1 en el oro, en las demas
divisas y en los indices principales; 5:1 en acciones. Con 50 € y 30:1 se mueven 1.500 € de divisa: un 3,3 % en contra
se lo come todo (el broker cierra antes, al 50 % del margen, y hay proteccion de saldo negativo).

## 3. Lo que eso significa con 50 €

**Con 50 € no se puede hacer sin apalancamiento.** Las comisiones minimas por orden (1,25-3 € o 2 $) son de un 3 a un
13 % de una posicion de 15-20 €, POR LADO. En Ploutos son el 0,10-0,20 %. Para que un bot de horas no se lo coman las
comisiones haria falta **entre 1.000 y 10.000 € de capital** segun el activo (el de divisas, el mas caro).

La unica forma de operar divisas u oro con 50 € es apalancado (CFD o futuros). Eso es exactamente lo que la regla 1 de
Ploutos prohibe, y donde la CNMV dice que pierden el 70-90 % de los minoristas.

## 4. Otras cosas que cambian respecto a la cripto

- **Hacienda:** en acciones y ETF, si se vende con perdida y se recompra el mismo valor en dos meses, la perdida no se
  puede restar hasta que se venda la nueva (art. 33.5 de la ley del IRPF). Con operaciones de horas sobre los mismos
  valores pasaria todo el rato. En derivados (futuros, CFD) esa regla no se aplica.
- **ETF de EE. UU.:** un minorista de la UE no puede comprarlos (no tienen el documento europeo de datos fundamentales);
  hay que ir a los ETF europeos.
- **Horario:** las acciones cierran de noche y los fines de semana; los precios saltan al abrir (huecos que el stop no
  frena). La cripto no cierra nunca.
- **Broker con API:** Interactive Brokers la tiene y da servicio en Espanya, sin minimo de cuenta (comprobado en su
  web). Otros (Saxo, Trading 212...) no los he comprobado.

## 5. Lo que se reaprovecharia de Ploutos

Casi todo lo que no es OKX: las reglas duras, el motor de riesgo, el papel y su juez, la IA como analista, el panel,
Telegram, Healthchecks, las copias. Lo nuevo seria la ingesta y la ejecucion del broker, y los horarios de mercado.

## 6. Conclusion

| Camino | Viable con 50 € | Viable con ~2.000-10.000 € |
|---|---|---|
| Acciones y ETF europeos, sin apalancamiento | no (comisiones) | si, con IBKR; operaciones de horas penalizadas por Hacienda |
| Divisas u oro al contado, sin apalancamiento | no | si, pero divisas pide ~10.000 € para que las comisiones no pesen |
| CFD o futuros (lo que vende el anuncio) | tecnicamente si | si; con apalancamiento, fuera de la regla 1 |

**Recomendacion:** no empezar otro bot ahora. Con el capital de Ploutos no es viable sin apalancamiento; y con mas
capital, la pregunta de fondo es la misma que en Ploutos (tener ventaja), que aun no tiene respuesta: el veredicto de la
fase 6 (desde el 16/10) y el estudio de operaciones de horas (`docs/estudios/operaciones-cortas/`) la dan antes.
Si el propietario quiere seguir con la idea, el siguiente paso es decidir **cuanto capital** y **si acepta apalancamiento**: con
esas dos respuestas se escribe un PRD propio.

Fuentes: comisiones de [acciones](https://www.interactivebrokers.ie/en/pricing/commissions-stocks.php?region=europe),
[divisas](https://www.interactivebrokers.ie/en/pricing/commissions-spot-currencies.php),
[metales](https://www.interactivebrokers.ie/en/pricing/commissions-metals.php) y
[futuros](https://www.interactivebrokers.ie/en/pricing/commissions-futures.php) de IBKR Irlanda (06/10/2026);
[FCA: TradeGPT](https://www.fca.org.uk/news/warnings/tradegpt-tradegpt-ainet);
[la CNMV prohibe la publicidad de CFD](https://ga-p.com/publicaciones/la-cnmv-prohibe-las-comunicaciones-publicitarias-sobre-cfds-a-inversores-minoristas-o-al-publico-en-general-e-introduce-restricciones-a-la-comercializacion-de-productos-apalancados/);
[resolucion de la CNMV del 11/07/2023](https://noticias.juridicas.com/base_datos/Privado/767810-r-cnmv-11-jul-2023-medidas-de-intervencion-de-producto-relativas-a-contratos.html);
[consulta de la CNMV sobre CFD](https://www.cnmv.es/DocPortal/DocFaseConsulta/CNMV/CP_ComercializacionCFD.pdf).
