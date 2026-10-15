# Preregistro: que quiere decir el papel de L y que se hace con el (15/10/2026)

De la tarea 2 de la revision del 15/10 (el propietario, opcion a: no parar nada, no buscar ahora otra estrategia y hacer tres
cosas baratas). Se escribe y se sube **antes** de que haya ningun resultado del papel que juzgar (el primero que cuenta
es el del 11/01/2027). El criterio del papel (`docs/diseno-papel-l.md` 3) **no cambia**: esto dice que significa y que
se hace despues.

## 1. Cuantos intentos llevamos (todos, tambien los de estudios anteriores)

| Hasta | Intentos | De donde |
|---|---|---|
| 09/10 | **27** | `docs/estudios/tendencia/umbral.json` (`descartado_N27`): primera ronda, time-stop, 1 h, segunda ronda, cortos |
| 09/10-10/10 | +8 | Kronos, I, F, H, J, K, L, M (`CLAUDE.md`, `docs/archivo/diseno-tendencia-2.md`) |
| **Total** | **~35** | +/-10: hay ajustes informales sin contar (la ventana de 28 dias de F) |
| con la robustez | ~47 | las 12 variantes de `robustez-l.md`, de solo informacion |

El deflactado de L (0,978) se calculo con **N = 10** (la familia de tendencia, opcion b del propietario del 09/10). Con N = 35
quedaria cerca de 0,93 (calculo del consejo, sin repetir con los scripts del proyecto): por debajo de 0,95. Con N = 27 tal como se calculo el 09/10 (`umbral.json`), el liston anual
era 1,73 y L (1,46) tampoco llegaba. **Ninguna estrategia de Ploutos ha pasado el deflactado contando todos los
intentos.** Desde hoy, cualquier estudio nuevo empieza con N >= 35.

## 2. Cuantos anos de datos harian falta (antes de medir nada)

Deflactado >= 0,95 con N intentos (Bailey y Lopez de Prado; dispersion de los Sharpe de los intentos 0,30 anual,
retornos diarios). Calculo del consejo del 15/10; repasada a mano la casilla N = 10 y Sharpe 1,0 (~9,7 anos):

| Sharpe real | N = 10 | N = 35 |
|---|---|---|
| 0,8 | ~25 anos | ~107 anos |
| 1,0 | ~10 anos | ~21 anos |
| 1,5 | ~2,6 anos | ~3,7 anos |

Las estrategias de tendencia realistas en cripto van de 0,8 a 1,2: **con la historia que hay (unos 5 anos de las 8
monedas) no se pueden demostrar.** Por eso no se busca otra estrategia sobre 12/2020-09/2026: seria sumar intentos.

## 3. Que puede decir el papel de L y que no

- Son 3 meses: **~3-5 operaciones** (`docs/diseno-papel-l.md` 2.4). Dice si L se comporta como se esperaba (sin
  sorpresas de datos, de reglas ni de ejecucion), **no** si gana dinero.
- Si el mercado cae, quedarse en efectivo tambien "pasaria" (no pierde y cae menos que BTC). Un pase en un mercado
  bajista dice que L protege, no que gane.
- Si el mercado sube, L puede pasar ganando menos que BTC: tambien es un pase.
- Se mide tambien, solo como informacion, la caida vela a vela (revision 6) y se compara con BTC.

## 4. Que se hara en cada caso (decisiones del propietario, una a una)

- **Si pasa:** _pendiente del propietario_.
- **Si falla o salta el corte del 25 %:** ya decidido (`docs/diseno-papel-l.md` 4): L se descarta y no se retoca.
- **Si no se puede juzgar** (huecos de velas, el papel no corrio): _pendiente del propietario_.

## 5. La prueba de L con 2018-2020 (una sola vez)

OKX tiene historia contra USDT de BTC y ETH desde 10/2017, XRP y TRX desde 01/2018 y DOGE desde 07/2019
(`docs/hallazgos-fase-3-4.md` 5b). Ningun script de `docs/estudios/` la usa (buscado el 15/10; que nadie la haya
mirado nunca no se puede demostrar). Su criterio se fijara y se subira aqui **antes** de bajarla: _pendiente_.

## 6. La prueba de oro

Cuando L entre en el bot (solo si pasa y el propietario decide): el bot y el simulador, con las mismas velas, tienen que dar las
mismas operaciones y la misma curva, como `scripts/papel_l.py --validar` hace hoy entre el papel y la medicion.
