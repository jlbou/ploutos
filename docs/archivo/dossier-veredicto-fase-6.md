# El dia del veredicto de la fase 6: las decisiones, en una pagina (preparado el 11/10/2026)

Pedido por el propietario ("1, 2 i 4", 11/10). **Nada de esto se decide hoy:** es para que ese dia se decida rapido y con todo
delante. Cada decision lleva la recomendacion; manda el propietario.

## 0. Cuando y que puede salir

- **Cuando:** minimo el 16/10 y 30 discrepancias; tope el **20/11** (`docs/archivo/protocolo-fase-6.md` 7). Al 10/10: 5 de 30.
  Lo mas probable: el tope, el 20/11.
- **Que puede salir** (`check_fase6.py`; M1 = si la IA elige mejor que el baseline, con intervalo del 90 %):

| Veredicto | Condicion | Probabilidad (dicha el 24/09) |
|---|---|---|
| La IA aporta | 30 discrepancias y el intervalo de M1 entero > 0 | baja: solo se ve una ventaja enorme |
| La IA perjudica | el intervalo de M1 entero < 0 (con cualquier muestra) | baja |
| **No concluyente** | todo lo demas | **la mas probable** |

- **Lo que ha cambiado desde que se fijo:** la estrategia de las dos carteras (setups de 4 h) **pierde** en la historia
  (`docs/estudios/`), y el objetivo del proyecto es ahora ganar dinero (el propietario, 09/10) con **L** en papel hasta el
  11/01/2027 (`docs/diseno-papel-l.md`). El veredicto dice si la IA elige bien DENTRO de una estrategia que pierde.

## 1. Las decisiones de ese dia

**D1. Las dos carteras viejas (baseline e IA, en papel).**
- **a) Retirarlas (recomendada con "no concluyente" o "perjudica").** Su pregunta ya esta contestada y su estrategia
  pierde; seguir no ensenya nada nuevo. Se paran `ploutos-paper` y `ploutos-paper-ai`, sus bases y jueces quedan
  archivados (con copia), y se libera memoria del VPS.
- b) Mantenerlas como estan: datos que no se van a usar.
- c) Mantener solo la de la IA: una cartera sin grupo de control no mide nada.
- Con "aporta": aun asi, a) — la IA elige mejor dentro de algo que pierde —, pero apuntar que vale la pena probarla
  dentro de L (D2 b).

**D2. El papel de la IA con L.**
- **a) Como filtro de riesgo de noticias (recomendada, si sale bien el punto 4 de abajo):** solo puede vetar o
  reducir, nunca empujar (PRD 6).
- b) Elegir entre las monedas que L deja (cuando hay mas que huecos): solo si el veredicto es "aporta", y antes
  medida en sombra con su propio criterio.
- c) Sin IA: L tal cual.

**D3. El demo de OKX** (hoy copia la cartera de la IA).
- **a) Pararlo si se retira la cartera de la IA (recomendada)** y volver a usarlo solo para probar las ordenes de L
  si L pasa el papel. Avisar antes de parar `ploutos-exec` (Healthchecks, ~20 min).
- b) Dejarlo encendido sin nada que copiar: no aporta.

**D4. Las dos ramas preparadas** (`sombra-log`: la sombra de la IA dice en el log lo que miro; `objetivo-taker`: el
objetivo cobrado taker en el papel).
- **a) Si se retiran las carteras viejas: no se despliegan** (no queda a quien aplicarlas); se dejan en el
  repositorio, sin juntar (recomendada).
- b) Si se mantienen: juntarlas y desplegarlas como estaba previsto.

**D5. Los medios en sombra** (24 RSS desde el 07/10).
- **Juzgarlos una vez con el criterio ya escrito** (`docs/diseno-medios-sombra.md` 3), como estaba previsto, aunque
  lo mas probable es que no haya muestra (hacian falta 20 candidatos bloqueados). Despues, ver el punto 4.

**D6. El CLI de la IA** (congelado en 2.1.266 hasta el veredicto): **actualizarlo** si la IA sigue en algun papel;
si no, da igual.

**D7. La segunda ronda de estrategia:** **darla por cerrada** (la sustituyeron la tendencia y L).

## 2. Lo que se hace ese mismo dia, decida lo que decida

1. Pasar `check_fase6.py` y ensenyar el veredicto tal cual (M1, M2, M3, por regimen), sin resumir.
2. Escribir `docs/cierre-fase-6.md` con la salida y las decisiones.
3. Actualizar CLAUDE.md y la memoria.

## 3. Lo que sigue igual

- El papel de L hasta el 11/01/2027, con su juez y sus avisos.
- La regla 1 y las 19 reglas duras; nada de dinero real.

## 4. Las noticias (el propietario, 11/10): ver `docs/archivo/propuesta-noticias-l.md`
