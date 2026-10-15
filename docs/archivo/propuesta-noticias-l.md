# Las noticias con L (PROPUESTA, 11/10/2026, para decidir)

Pedida por el propietario ("sobre les noticies em de mirar a veure com ho fem", 09/10; "1, 2 i 4", 11/10). **Nada en marcha.**

**DECIDIDO por el propietario el 11/10:** A, **si, en sombra desde ya**; B y C se sustituyen por **un embudo de tres pasos
(palabras clave, confirmacion por fuentes y por precio, y la IA con el veredicto final)**, lo que cambia la decision F
del 22/09 solo para esto. Disenyo: `docs/diseno-embudo-noticias.md` (pendiente de sus numeros).

## 0. Lo que ya hay y lo que se sabe

- **Anuncios de OKX** (`ploutos-news`, desde el 25/09): flags por moneda. Critica (deslistado, suspension, incidente) =
  no entrar y, con posicion, vender a mercado; alta (migracion, volatilidad) = no entrar. Lo usan las dos carteras
  viejas (`docs/diseno-noticias.md`).
- **Medido el 24/09:** en 3,5 anyos de anuncios de OKX, **0 criticos de nuestras 8 monedas**. Para monedas grandes es
  un seguro contra un caso raro, no algo que se active a menudo.
- **Medios en sombra** (`ploutos-medios`, desde el 07/10): 24 RSS, el mismo clasificador de palabras; se juzgan una
  vez tras el veredicto de la fase 6 (`docs/diseno-medios-sombra.md` 3). Meten mucho ruido ("hackers stole 5 M$ in
  ETH" no es un hackeo de Ethereum).
- **La literatura** (`docs/estudios/recerca-trading-cripto.md`): las noticias como senyal de compra no dan ventaja a
  nuestra escala (el precio reacciona en segundos); el sentimiento sigue al precio. **Como filtro de riesgo, si.**
- **Lo que cambia con L:** opera poco (13 operaciones en el anyo USDC). **Ningun filtro de noticias se podra medir con
  numeros sobre L**: habra 0, 1 o 2 casos. Se decide por razonamiento (es un seguro), no por estadistica.

## 1. Las opciones (no se excluyen)

**A. Los anuncios de OKX en L (recomendada).** Las mismas flags que ya hay: L no compra una moneda con flag activa y,
con una critica, vende. Un deslistado obliga a salir igual; esto solo lo hace antes.
- En el papel de L, **en sombra**: cada noche el papel apunta (y avisa por Telegram) lo que el filtro HABRIA hecho,
  sin cambiar las cifras de L (que siguen siendo lo medido). Coste: ~2 h.
- En L con dinero real (si llega): activo, como en las carteras viejas.

**B. Los medios (RSS) en L.** Seguir recogiendo; el juicio previsto tras el veredicto no cambia (se hace con los
candidatos de las carteras viejas, como se fijo). Para L, solo apuntar en sombra que flags de medios habria tenido cada
moneda que compra, como informacion. **Recomendado: solo apuntar**, por el ruido.

**C. La IA lee los titulares y puede vetar una compra de L.** Cada lunes, antes de comprar, la IA lee los titulares de
la semana de las monedas que L quiere y dice "adelante" o "veto, porque...". Entiende el contexto mejor que las
palabras clave.
- **Choca con una decision del propietario (F, 22/09): la IA no lee titulares**, por seguridad: un titular es texto no
  confiable y podria intentar manipularla (inyeccion). La IA solo podria vetar (nunca empujar), lo que limita el
  danyo, pero la decision es del propietario.
- Coste: 1 llamada por semana (nada). Beneficio: no medible con tan pocos casos.
- **Recomendado: no ahora.** Si el propietario quiere, despues del veredicto de la fase 6 (D2 del dossier) y en sombra: la IA
  dice que vetaria, se apunta, no cambia nada, y se mira caso a caso.

**D. Las noticias como senyal de compra: NO** (PRD 6, la literatura y la regla de que los titulares son texto no
confiable).

## 2. La propuesta en una linea

**A en sombra en el papel de L desde ya (sin tocar sus cifras), B solo apuntar, C quiza tras el veredicto, D nunca.**

## 3. Para decidir

1. A: si / no. Si es si, desde cuando (el papel de L empieza el lunes 12/10; anyadirlo en sombra no cambia sus cifras).
2. B: solo apuntar / no.
3. C: descartada / pensarla tras el veredicto.
