# Decision 8: las fases, del estudio al dinero real (15/10/2026)

## La secuencia

1. **El estudio (paso 2):** la estrategia pasa con el criterio fijado y subido a git antes de medir.
2. **Construirla en el bot**, con la **prueba de oro**: con las mismas velas, el bot y el simulador dan las mismas
   operaciones y la misma curva.
3. **El demo de OKX:** la mecanica (ordenes, proteccion, euros). Sin comprobar que el demo tenga BTC/EUR y ETH/EUR.
4. **Papel hacia adelante**, con datos que aun no han pasado y el criterio fijado antes.
5. **Dinero real, primero poco**, y subir por escalones solo si cada tramo cumple lo esperado.

## El papel hacia adelante (opcion a)

- **6 meses y al menos un cambio de tipo de mercado** (por ejemplo, una subida y una caida). Si en 6 meses no ha
  cambiado, se alarga hasta que cambie, **con un maximo de 12 meses**.
- **Que es "un cambio de tipo de mercado"** se define de forma medible antes de empezar (p. ej. BTC/EUR cruza su media
  de 200 dias, o se mueve mas de un 20 % desde un maximo o un minimo): se fija en el criterio del papel.
- Por que: con L, 3 meses daban ~3-5 operaciones y "decian poco"; un pase en un solo tipo de mercado puede ser suerte.

## El dinero real (opcion a)

- **Se empieza con poco:** una cantidad que el propietario pueda perder sin que le haga dano (referencia: 250-500 €;
  **la cifra la pone el propietario al llegar ahi**).
- **Cada 3 meses se dobla, SOLO si ese tramo cumple** (escrito antes): el resultado esta dentro de lo que el estudio
  dice que es normal, sin incidencias, y la caida no pasa de la peor del estudio. Si no cumple, no se sube; si falla
  grave, se para.
- **Nunca por encima de 10.000 €** (el techo de disenyo, decision 2) sin un estudio nuevo.
- Cada subida la decide el propietario; el bot nunca mueve dinero.
