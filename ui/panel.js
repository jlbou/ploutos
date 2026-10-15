// El panel: pinta la foto del estado (api/foto.py) que llega por el WebSocket /ws, con el aspecto de la maqueta.
// Todo el texto va con textContent y nodos de texto, nunca como HTML: lo que viene de las bases no se
// interpreta como HTML. Si el WebSocket cae, banner rojo, datos en gris y se reintenta cada 5 s.
"use strict";

const NOMBRE = { baseline: "Baseline", ai: "IA", demo: "Demo" };
const ORDEN_CARTERAS = ["ai", "baseline"];
const SERVICIO = {
  ingesta: "Ingesta de datos (OKX)", papel_ai: "Cartera IA", papel_baseline: "Cartera baseline",
  noticias: "Noticias", telegram: "Comandos de Telegram", ejecutor: "Ejecutor del demo", papel_l: "Papel de L",
  medios: "Medios (en sombra)",
};
const OCO = { viva: ["ok", "OCO viva"], sin_oco: ["mal", "SIN OCO"], vendiendo: ["aviso", "vendiendo"] };
const ESTADO = { ok: "OK", tarde: "Tarde", caido: "Caído", sin_datos: "Sin datos", retirado: "Retirado" };
const SETUP = { pullback_trend: "pullback", range_breakout: "ruptura", mean_reversion: "reversión" };
const MOTIVO = { stop: ["mal", "stop"], target: ["ok", "objetivo"], news: ["aviso", "noticia"], manual: ["aviso", "manual"],
  cancelled: ["", "cancelada"] };
const VELA_MS = 4 * 3600000;
let ultimaFoto = null;
let recibida = 0;

const $ = (id) => document.getElementById(id);

// Tras un despliegue, el navegador puede tener la pagina VIEJA guardada y pedir este script nuevo: no casan y el
// panel se quedaria en blanco. Si falta una pieza de la pagina nueva, se recarga una vez (recargar pide la pagina).
if (!$("p-bandas") || !$("p-flujo") || !$("pag-resumen") || !$("papel-l")) {
  let recargado = false;
  try { recargado = sessionStorage.getItem("ploutos-recarga") === "1"; sessionStorage.setItem("ploutos-recarga", "1"); } catch (e) { /* sin almacen */ }
  if (!recargado) location.reload();
  throw new Error("pagina vieja en la cache del navegador");
}
try { sessionStorage.removeItem("ploutos-recarga"); } catch (e) { /* sin almacen */ }

function el(tag, attrs = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const h of hijos) if (h != null) e.append(h instanceof Node ? h : document.createTextNode(h));
  return e;
}

const usd = (x, signo = false) => x == null ? "–" :
  (signo && x > 0 ? "+" : "") + x.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " $";
const num = (x, d = 2, signo = false) => x == null ? "–" :
  (signo && x > 0 ? "+" : "") + x.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
const precio = (x) => x == null ? "–" : Number(x.toPrecision(6)).toLocaleString("es-ES", { maximumFractionDigits: 8 });
const signoClase = (x) => x == null ? "gris" : x > 0 ? "pos" : x < 0 ? "neg" : "";
const base = (s) => (s || "").split("/")[0];
const hora = (ms) => ms == null ? "–" :
  new Date(ms).toLocaleString("es-ES", { timeZone: "UTC", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) + " UTC";
const soloHora = (ms) => new Date(ms).toLocaleTimeString("es-ES", { timeZone: "UTC", hour: "2-digit", minute: "2-digit" });
const soloDia = (ms) => new Date(ms).toLocaleDateString("es-ES", { timeZone: "UTC", day: "2-digit", month: "2-digit" });
function hace(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const h = Math.floor(s / 3600);
  return h < 48 ? `${h} h` : `${Math.floor(h / 24)} d ${h % 24} h`;
}
const chip = (texto, clase = "") => el("span", { class: "chip " + clase }, texto);
const chipCartera = (n) => chip(NOMBRE[n] || n, n === "ai" ? "ia" : n === "baseline" ? "base" : "");

// --- La barra de estado: una fila por cartera ---

function dato(etiqueta, valor, clase = "", extra = false, otra = "") {
  return el("div", { class: ["dato", extra ? "extra" : "", otra].join(" ").trim() }, el("span", { class: "label" }, etiqueta),
    el("span", { class: "v " + clase }, valor));
}

function filaCartera(nombre, c, f) {
  const fila = el("div", { class: "fila-c", "data-c": nombre });
  const cab = el("div", { class: "nombre" }, el("i"), NOMBRE[nombre] || nombre);
  if (!c || !c.disponible) {
    fila.append(cab, el("span", { class: "gris" }, "Sin datos"));
    return fila;
  }
  const modoClase = c.modo === "NORMAL" ? "" : c.modo === "HALTED" ? "mal" : "aviso";
  const modo = el("span", { class: "modo " + modoClase, title: "Modo efectivo: el más restrictivo de los activos" },
    c.modo === "NORMAL" ? "Normal" : c.modo.replace("CLOSE_ONLY_", "Solo cierre: ").replace("HALTED", "Parado"));
  cab.append(modo);
  if ((f.servicios[`papel_${nombre}`] || {}).estado === "retirado") cab.append(chip("Retirada el 15/10", "gris"));
  const lim = f.limites;
  fila.append(cab,
    dato("Equity (vela)", usd(c.equity_usd), "grande"),
    dato("Ahora ≈", usd(c.equity_ahora_usd), signoClase(c.equity_ahora_usd == null || c.equity_usd == null ? null
      : c.equity_ahora_usd - c.equity_usd)),
    dato("Hoy", usd(c.cambio_hoy_usd, true), signoClase(c.cambio_hoy_usd)),
    dato("Caída máx.", num(c.drawdown_max_pct, 1) + " %", "", true),
    dato("Cerradas hoy", `${c.cerradas_hoy} / ${lim.max_operaciones_dia}`, "", true),
    dato("Posiciones", `${c.posiciones.length} / ${lim.max_posiciones}`, "", false, "m-oculta"),
    dato("Llamadas IA", c.llamadas_ia == null ? "—" : `${c.llamadas_ia} / ${lim.max_llamadas_ia_dia}`,
      c.llamadas_ia == null ? "gris" : "", true));
  // La barra va del suelo (25 $) al capital inicial (50 $): lo que queda antes de CLOSE_ONLY_CAPITAL.
  const suelo = el("div", { class: "suelo" });
  if (c.equity_usd != null) {
    const rango = lim.capital_inicial_usd - lim.suelo_usd;
    const pct = Math.max(0, Math.min(100, (c.equity_usd - lim.suelo_usd) / rango * 100));
    const marca = el("i"); marca.style.left = `calc(${pct}% - 1.5px)`;
    suelo.append(
      el("span", { class: "label", style: "color:var(--brand-ink-2);font-size:10.5px" },
        `Sobre el suelo: ${usd(c.distancia_suelo_usd)}`),
      el("div", { class: "suelo-barra", role: "img", "aria-label": `${usd(c.distancia_suelo_usd)} por encima del suelo de ${lim.suelo_usd} $` }, marca),
      el("small", {}, el("span", {}, `${lim.suelo_usd}`), el("span", {}, "35"), el("span", {}, "45"),
        el("span", {}, `${lim.capital_inicial_usd}`)));
  }
  fila.append(suelo);
  return fila;
}

function pintarCarteras(f) {
  $("carteras").replaceChildren(...ORDEN_CARTERAS.filter((n) => n in f.carteras).map((n) => filaCartera(n, f.carteras[n], f)));
}

// --- Posiciones: una por decision, aunque la tengan las dos carteras ---

function posicionesAgrupadas(f) {
  const por = new Map();
  for (const n of ORDEN_CARTERAS) {
    const c = f.carteras[n];
    if (!c || !c.disponible) continue;
    for (const p of c.posiciones) {
      const clave = p.decision_id || `${n}-${p.symbol}`;
      if (!por.has(clave)) por.set(clave, { ...p, carteras: [] });
      por.get(clave).carteras.push({ n, pnl_usd: p.pnl_usd, pnl_r: p.pnl_r });
    }
  }
  return [...por.values()].sort((a, b) => a.opened_ts_ms - b.opened_ts_ms);
}

function barraRango(p) {
  const lo = p.stop_price, hi = p.target_price;
  const pos = (x) => Math.max(0, Math.min(100, (x - lo) / (hi - lo) * 100));
  const caja = el("div", { class: "rango-caja" });
  const r = el("div", { class: "rango", role: "img",
    "aria-label": `precio ${precio(p.precio)} entre el stop ${precio(lo)} y el objetivo ${precio(hi)}` });
  const pe = pos(p.entry_price);
  if (p.precio != null) {
    const pa = pos(p.precio);
    const relleno = el("span", { class: "relleno" });
    relleno.style.left = `${Math.min(pe, pa)}%`; relleno.style.width = `${Math.abs(pa - pe)}%`;
    relleno.style.background = `color-mix(in srgb, var(${p.precio >= p.entry_price ? "--good" : "--bad"}) 55%, transparent)`;
    const ahora = el("span", { class: "ahora" }); ahora.style.left = `${pa}%`;
    r.append(relleno, ahora);
  }
  const entrada = el("span", { class: "entrada" }); entrada.style.left = `${pe}%`;
  const pct = (x) => num((x / p.entry_price - 1) * 100, 1, true) + " %";
  r.append(entrada);
  caja.append(el("div", { class: "et-fila" }, el("span", {}, `stop ${precio(lo)} (${pct(lo)})`),
    el("span", {}, `objetivo ${precio(hi)} (${pct(hi)})`)), r,
  el("div", { class: "et-fila" }, el("span", {}, `entrada ${precio(p.entry_price)}`),
    el("span", {}, `ahora ${p.precio_aprox ? "≈ " : ""}${precio(p.precio)}`)));
  return caja;
}

function tarjetaPosicion(p, generado) {
  const quien = el("div", { class: "quien" }, ...p.carteras.map((c) => chipCartera(c.n)),
    p.oco ? chip((OCO[p.oco] || ["", p.oco])[1], (OCO[p.oco] || ["", p.oco])[0]) : null);
  const izq = el("div", { class: "izq" }, el("div", { class: "par" }, p.symbol,
    el("small", {}, `${SETUP[p.setup] || p.setup} · hace ${hace(generado - p.opened_ts_ms)}`)), quien);
  const res = el("div", { class: "resultado" });
  if (p.carteras.length === 1) {
    const c = p.carteras[0];
    res.append(el("b", { class: signoClase(c.pnl_usd) }, usd(c.pnl_usd, true)),
      el("small", {}, num(c.pnl_r, 2, true) + " R"));
  } else {
    for (const c of p.carteras) {
      res.append(el("div", { class: "linea" }, el("span", { class: "gris" }, (NOMBRE[c.n] || c.n) + " "),
        el("span", { class: signoClase(c.pnl_usd) }, usd(c.pnl_usd, true)), el("span", { class: "gris" }, ` · ${num(c.pnl_r, 2, true)} R`)));
    }
  }
  const clave = clavePos(p);
  const abierta = abiertas.has(clave);
  const tarjeta = el("div", { class: "posicion" + (abierta ? " abierta" : ""), role: "button", tabindex: "0",
    "aria-expanded": String(abierta), title: abierta ? "Ocultar el gráfico" : "Ver el gráfico" },
  izq, barraRango(p), res, abierta ? graficoPosicion(p) : null);
  const alternar = () => {
    if (abierta) abiertas.delete(clave); else abiertas.add(clave);
    pintarTarjetas(ultimaFoto);
  };
  tarjeta.onclick = alternar;
  tarjeta.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); alternar(); } };
  return tarjeta;
}

// --- El grafico de cada posicion abierta (el propietario, 01/10): se abre al tocarla ---
// Velas de 4 h desde dos dias antes de la entrada hasta ahora (la en curso, de las de 1 minuto), con
// tres lineas: entrada, stop y objetivo. El grafico vive en su caja y la caja se MUEVE a la tarjeta nueva
// cada vez que se repinta la foto (cada pocos segundos): asi no se rehace ni parpadea.

const abiertas = new Set();          // las posiciones desplegadas
const graficosPos = new Map();       // clave -> { caja, chart, serie, marcas, pedido }
const VELAS_CADA_MS = 60000;

function clavePos(p) {
  // La del demo lleva su prefijo: la misma decision tiene tarjeta en papel y en el demo, cada una con su grafico.
  return p.clave || p.decision_id || `${p.symbol}-${p.opened_ts_ms}`;
}

function graficoPosicion(p) {
  const k = clavePos(p);
  let g = graficosPos.get(k);
  if (!g) {
    g = { caja: el("div", { class: "pos-grafico" }), chart: null, serie: null, marcas: null, pedido: 0 };
    g.caja.onclick = (e) => e.stopPropagation();       // mover el grafico no pliega la tarjeta
    graficosPos.set(k, g);
  }
  if (typeof LightweightCharts === "undefined") {
    g.caja.textContent = "No se pudo cargar la librería de gráficos.";
    return g.caja;
  }
  if (!g.chart) {
    g.chart = LightweightCharts.createChart(g.caja, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: color("--ink-3"), fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
      grid: { vertLines: { color: color("--line") }, horzLines: { color: color("--line") } },
      rightPriceScale: { borderColor: color("--line") },
      timeScale: { borderColor: color("--line"), timeVisible: true },
      localization: { priceFormatter: (v) => precio(v) },
    });
    g.serie = g.chart.addSeries(LightweightCharts.CandlestickSeries, {
      upColor: color("--good"), downColor: color("--bad"), borderVisible: false,
      wickUpColor: color("--good"), wickDownColor: color("--bad"), priceLineVisible: false,
      // La escala incluye SIEMPRE el stop y el objetivo: si no, solo se ven cuando el precio se acerca.
      autoscaleInfoProvider: (original) => {
        const r = original();
        if (!r) return r;
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, p.stop_price),
          maxValue: Math.max(r.priceRange.maxValue, p.target_price) } };
      },
    });
    const linea = (price, variable, title, discontinua) => g.serie.createPriceLine({ price, color: color(variable), lineWidth: 1,
      lineStyle: discontinua ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title });
    linea(p.target_price, "--good", "objetivo", true);
    linea(p.entry_price, "--ink-2", "entrada", false);
    linea(p.stop_price, "--bad", "stop", true);
    g.marcas = LightweightCharts.createSeriesMarkers(g.serie, []);
    // La caja nace sin anchura (se crea antes de entrar en la pagina): al tomar su tamanyo de verdad, o al girar
    // el movil, se vuelven a encajar las velas. Sin esto, en el movil salian apretadas a la derecha.
    if (typeof ResizeObserver !== "undefined") {
      g.observador = new ResizeObserver(() => g.chart && g.chart.timeScale().fitContent());
      g.observador.observe(g.caja);
    }
  }
  if (Date.now() - g.pedido > VELAS_CADA_MS) {
    g.pedido = Date.now();
    fetch(`/api/velas?simbolo=${encodeURIComponent(p.symbol)}&desde=${p.opened_ts_ms}`).then((r) => r.json()).then((v) => {
      if (!g.serie) return;
      g.serie.setData(v.map(([t, o, h, l, c]) => ({ time: Math.floor(t / 1000), open: o, high: h, low: l, close: c })));
      g.marcas.setMarkers([{ time: Math.floor(p.opened_ts_ms / 1000), position: "belowBar", shape: "arrowUp",
        color: color("--accent"), text: "entrada" }]);
      g.chart.timeScale().fitContent();
    }).catch(() => { g.pedido = 0; });
  }
  return g.caja;
}

function limpiarGraficos(vivas) {
  // Los de posiciones cerradas o plegadas se destruyen: un grafico suelto sigue escuchando el tamanyo.
  for (const [k, g] of graficosPos) {
    if (vivas.has(k) && abiertas.has(k)) continue;
    if (g.observador) g.observador.disconnect();
    if (g.chart) g.chart.remove();
    graficosPos.delete(k);
  }
  for (const k of [...abiertas]) if (!vivas.has(k)) abiertas.delete(k);
}

function tabla(cabeceras, filas) {
  // cabeceras: [titulo, numerica, clase extra]
  if (!filas.length) return el("p", { class: "vacio" }, "Ninguna");
  const thead = el("thead", {}, el("tr", {}, ...cabeceras.map(([t, n, x]) => el("th", { class: [n ? "n" : "", x || ""].join(" ").trim() || null }, t))));
  const tbody = el("tbody", {}, ...filas.map((f) => el("tr", {}, ...f.map((celda, i) => {
    const [contenido, clase] = Array.isArray(celda) ? celda : [celda, ""];
    const clases = [cabeceras[i][1] ? "n" : "", cabeceras[i][2] || "", clase || ""].join(" ").trim();
    return el("td", { class: clases || null }, contenido);
  }))));
  return el("div", { class: "tabla-caja" }, el("table", {}, thead, tbody));
}

function pintarTarjetas(f) {
  // Papel y demo a la vez: los graficos que no esten en ninguno de los dos se destruyen.
  const vivas = new Set([...pintarPosiciones(f), ...pintarDemo(f)]);
  limpiarGraficos(vivas);
}

function pintarPosiciones(f) {
  const grupos = posicionesAgrupadas(f);
  $("posiciones").replaceChildren(...(grupos.length ? grupos.map((p) => tarjetaPosicion(p, f.generado_ms))
    : [el("p", { class: "vacio" }, "Ninguna posición abierta.")]));
  const pendientes = [];
  for (const n of ORDEN_CARTERAS) {
    const c = f.carteras[n];
    if (!c || !c.disponible) continue;
    for (const o of c.pendientes) pendientes.push([chipCartera(n), [o.symbol, "par"], SETUP[o.setup] || o.setup,
      precio(o.limit_price), precio(o.stop_price), precio(o.target_price), hora(o.created_ts_ms)]);
  }
  $("pendientes-caja").hidden = !pendientes.length;
  $("pendientes").replaceChildren(tabla([["Cartera"], ["Par"], ["Setup", 0, "m-oculta"], ["Límite", 1], ["Stop", 1, "m-oculta"],
    ["Objetivo", 1, "m-oculta"], ["Desde", 1, "m-oculta"]], pendientes));
  return grupos.map(clavePos);
}

// --- El demo de OKX (fase 4): lo que tiene el ejecutor, leido de su base ---

function pintarDemo(f) {
  const d = f.demo;
  if (!d || !d.disponible) {
    $("demo").replaceChildren(el("p", { class: "vacio" }, "El ejecutor del demo no ha arrancado."));
    return [];
  }
  const modo = d.modo === "NORMAL" ? chip("NORMAL", "ok") : chip(d.modo, "aviso");
  const c = d.conciliacion;
  const conc = !c ? chip("sin conciliar", "aviso")
    : c.cuadra ? chip(`cuadra · ${hace(f.generado_ms - c.ts_ms)}`, "ok") : chip("DESCUADRE", "mal");
  const par = (l, v, clase = "") => el("div", {}, el("span", { class: "l" }, l), el("b", { class: clase }, v));
  const cab = el("div", { class: "demo-datos" },
    par("Modo", modo), par("Equity", d.equity_usd == null ? "–" : usd(d.equity_usd) + (d.equity_fiable ? "" : " (no fiable)")),
    par("Cerradas hoy", `${d.cerradas_hoy} · ${usd(d.pnl_hoy_usd, true)}`, signoClase(d.pnl_hoy_usd)),
    par("Conciliación", conc));
  const hijos = [cab];
  if (c && !c.cuadra) hijos.push(el("p", { class: "nota" }, c.descuadres.join(" · ")));
  const tarjetas = d.posiciones.map((p) => ({ ...p, clave: "demo-" + p.decision_id,
    carteras: [{ n: "demo", pnl_usd: p.pnl_usd, pnl_r: p.pnl_r }] }));
  hijos.push(tarjetas.length
    ? el("div", { class: "posiciones" }, ...tarjetas.map((p) => tarjetaPosicion(p, f.generado_ms)))
    : el("p", { class: "vacio" }, "Ninguna posición en el demo."));
  if (d.entradas.length) {
    hijos.push(el("h3", {}, "Entradas en OKX"), tabla([["Par"], ["Límite", 1], ["Stop", 1, "m-oculta"], ["Desde", 1, "m-oculta"]],
      d.entradas.map((e) => [[e.simbolo, "par"], precio(e.limite), precio(e.stop), hora(e.creada_ms)])));
  }
  if (d.tratadas.length) {
    hijos.push(el("details", {}, el("summary", {}, "Últimas decisiones de la IA en el demo"),
      tabla([["Decisión"], ["Qué"], ["Por qué", 0, "m-oculta"]], d.tratadas.map((x) =>
        [x.decision_id, chip(x.que, x.que === "copiada" ? "ok" : ""), x.motivo]))));
  }
  hijos.push(el("p", { class: "nota" }, `50 $ virtuales desde ${hora(d.foto_ms)}: el demo tiene sus propios fondos y el bot solo cuenta lo que mueve.`
    + (tarjetas.length ? " El precio de ahora (≈) es el del mercado real; el del demo se le parece mucho pero no es el mismo." : "")));
  $("demo").replaceChildren(...hijos);
  return tarjetas.map(clavePos);
}

// --- El papel de L (10/10): un estudio que se rehace cada noche, leido de sus ficheros ---

const MOTIVO_L = { rotacion: ["", "rotación"], stop: ["mal", "stop"], objetivo: ["ok", "objetivo"] };

function pintarPapelL(f) {
  const l = f.papel_l;
  if (!l || !l.disponible) {
    $("papel-l").replaceChildren(el("p", { class: "vacio" },
      `Empieza el lunes ${l ? l.inicio.split("-").reverse().join("/") : "12/10/2026"} a las 00:00 UTC; el primer resultado, el martes a las 00:20 UTC.`));
    return;
  }
  const par = (t, v, clase = "") => el("div", {}, el("span", { class: "l" }, t), el("b", { class: clase }, v));
  const pct = (x) => num(x, 1, true) + " %";
  const corte = l.caida_max_pct > 0.8 * l.corte_pct ? "aviso" : "";
  const hijos = [el("div", { class: "demo-datos" },
    par("Equity (pasada)", usd(l.equity_usd)), par("Rendimiento", pct(l.rendimiento_pct), signoClase(l.rendimiento_pct)),
    par("Caída máx.", `${num(l.caida_max_pct, 1)} % (corte ${l.corte_pct} %)`, corte),
    ...(l.caida_velas_pct == null ? [] : [par("Caída vela a vela", `${num(l.caida_velas_pct, 1)} % · BTC ${num(l.btc_caida_velas_pct, 1)} % (informativa)`)]),
    par("BTC, mismo periodo", `${pct(l.btc_rendimiento_pct)} · caída ${num(l.btc_caida_max_pct, 1)} %`),
    par("Última pasada", hace(f.generado_ms - l.pasada_ms)))];
  if (Object.keys(l.huecos).length) {
    hijos.push(el("p", { class: "nota" }, chip("FALTAN VELAS", "mal"), " " + Object.entries(l.huecos)
      .map(([s, n]) => `${base(s)}: ${n}`).join(" · ") + ": así el papel no vale."));
  }
  hijos.push(el("h3", {}, "Posiciones"), l.posiciones.length
    ? tabla([["Par"], ["Entrada", 1], ["Ahora ≈", 1], ["Stop", 1, "m-oculta"], ["Objetivo", 1, "m-oculta"], ["Resultado ≈", 1], ["Desde", 1, "m-oculta"]],
      l.posiciones.map((p) => [[p.symbol, "par"], precio(p.entrada), precio(p.precio), precio(p.stop), precio(p.objetivo),
        [usd(p.pnl_usd, true), signoClase(p.pnl_usd)], hora(p.abierta_ms)]))
    : el("p", { class: "vacio" }, "En USDC: ninguna moneda cumple ahora."));
  if (l.ultimas.length) {
    hijos.push(el("h3", {}, `Últimas operaciones (${l.operaciones} cerradas)`),
      tabla([["Par"], ["Motivo"], ["Abierta", 1, "m-oculta"], ["Cerrada", 1], ["Neto", 1]], l.ultimas.map((o) => {
        const [clase, texto] = MOTIVO_L[o.motivo] || ["", o.motivo];
        return [[o.symbol, "par"], chip(texto, clase), soloDia(o.entrada_ms), soloDia(o.salida_ms), [usd(o.neto_usd, true), signoClase(o.neto_usd)]];
      })));
  }
  hijos.push(el("p", { class: "nota" }, "Solo papel: cada noche a las 00:20 UTC se rehace L con el mismo simulador que se midió y los precios reales. "
    + "Las posiciones se valoran con el último minuto (≈, sin la comisión de salida). Pasa si al acabar no pierde y cae como mucho 2/3 de lo que cae BTC."));
  $("papel-l").replaceChildren(...hijos);
}

// --- Sistema, noticias, bandas, agresividad y limites ---

function pintarSistema(f) {
  $("servicios").replaceChildren(...Object.entries(f.servicios).map(([k, s]) =>
    el("div", { class: "nodo e-" + (s.estado || "sin_datos") }, el("span", {}, SERVICIO[k] || k),
      el("small", {}, (ESTADO[s.estado] || s.estado) + (s.ultimo_ms ? ` · ${hace(f.generado_ms - s.ultimo_ms)}` : "")))));
  const n = f.noticias;
  const flags = Object.entries(n.flags || {});
  $("noticias").replaceChildren(!n.disponible ? el("p", { class: "vacio" }, "Sin datos del servicio de noticias.")
    : !flags.length ? el("p", { class: "vacio" }, "Sin avisos activos: ninguna moneda bloqueada.")
    : tabla([["Par"], ["Aviso"]], flags.map(([par, tipos]) => [[par, "par"], tipos.map((t) => chip(t, "aviso"))])));
}

function pintarBandas(f) {
  const m = f.manual;
  $("banda-parada").textContent = m.parada_ms ? `Parado desde ${hora(m.parada_ms)}. Solo se levanta en el VPS o desde este panel, con motivo.` : "";
  $("banda-parada").hidden = !m.parada_ms;
  $("banda-pausa").textContent = m.pausa_ms ? `En pausa desde ${hora(m.pausa_ms)}: no se abre nada nuevo. Se quita desde aquí o con /resume.` : "";
  $("banda-pausa").hidden = !m.pausa_ms;
  $("p-bandas").hidden = !m.parada_ms && !m.pausa_ms;
}

function pintarAgresividad(f) {
  const l = f.limites;
  const filas = [["Monedas", l.whitelist.map(base).join(" ")], ["Capital inicial", usd(l.capital_inicial_usd)],
    ["Suelo", usd(l.suelo_usd)], ["Posiciones a la vez", l.max_posiciones], ["Operaciones al día", l.max_operaciones_dia],
    ["Pérdida máxima del día", usd(l.perdida_diaria_max_usd)], ["Riesgo por operación", num(l.riesgo_por_operacion_pct, 1) + " %"],
    ["Llamadas a la IA al día", l.max_llamadas_ia_dia],
    ["Acceso de la IA", f.token_ia.dias == null ? "sin fecha" : `caduca en ${f.token_ia.dias} días`]];
  $("limites").replaceChildren(...filas.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))]));
  const sl = f.slider;
  const etiqueta = { 1: "prudente", 3: "normal", 5: "agresivo" };
  // Cada nivel dice su riesgo; los extremos, ademas, su nombre (antes el 1 y el 5 no decian el %).
  $("niveles").replaceChildren(...sl.niveles.map((n) => el("div", { class: n.nivel === sl.nivel ? "hoy" : null },
    el("b", {}, String(n.nivel)), el("small", {}, (n.nivel === sl.nivel ? "hoy · " : etiqueta[n.nivel] && n.nivel !== 3
      ? etiqueta[n.nivel] + " · " : "") + `${num(n.riesgo_pct, 2)} %`))));
  const hoy = sl.niveles.find((n) => n.nivel === sl.nivel);
  $("nivel-hoy").replaceChildren(...(hoy ? [["Riesgo por operación", num(hoy.riesgo_pct, 2) + " %"],
    ["Operaciones al día", `${hoy.max_operaciones} / 6`], ["Setups", hoy.setups.map((s) => SETUP[s] || s).join(", ")]] : [])
    .flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))]));
  $("slider").textContent = sl.bloqueado ? "bloqueado en el 3 hasta cerrar la fase 6" : "";
  $("slider").title = sl.bloqueado ? `Nivel ${sl.nivel}, ${sl.motivo}.` : "";
}

// --- Por moneda: donde se quedo cada una en la ultima vela, en las dos carteras ---

const ESTADO_MONEDA = {
  posicion: ["ok", "Posición abierta"], pendiente: ["ia", "Entrada pendiente"], enviada: ["ok", "Orden enviada"],
  vetada: ["mal", "Vetada por el motor"], no_abierta: ["aviso", "Candidato no abierto"],
  descartada: ["", "Descartada"], sin_senyal: ["", "Sin señal"],
};

function pintarMonedas(f) {
  const carteras = ORDEN_CARTERAS.map((n) => [n, f.carteras[n]]).filter(([, c]) => c && c.disponible && c.por_moneda);
  if (!carteras.length) { $("monedas").replaceChildren(el("p", { class: "vacio" }, "Sin datos")); return; }
  const vela = carteras[0][1].por_moneda.vela_ms;
  $("monedas-vela").textContent = vela ? `vela que cerró el ${hora(vela + VELA_MS)}` : "";
  const celda = (m) => {
    if (!m) return "–";
    const [clase, texto] = ESTADO_MONEDA[m.estado] || ["", m.estado];
    const caja = el("div", {}, chip(texto, clase));
    if (m.detalle) caja.append(el("span", { class: "moneda-estado" }, m.detalle));
    return caja;
  };
  const filas = f.limites.whitelist.map((s) => [[base(s), "par"], ...carteras.map(([, c]) => celda(c.por_moneda.monedas[s]))]);
  $("monedas").replaceChildren(tabla([["Moneda"], ...carteras.map(([n]) => [NOMBRE[n] || n])], filas));
}

// --- El flujo de la ultima vela (PRD 10: "diagrama de flujo por nodos: vista de sistema + vista por moneda") ---
// Cada paso dice cuantas monedas llegaron en la ultima vela; al elegir una moneda, se ilumina su camino hasta
// el paso donde se quedo, con el motivo. Los datos salen de la foto (`flujo` y `por_moneda` de cada cartera).

let flujoCartera = "ai";
let flujoMoneda = null;
const PARADA = { descartada: 1, sin_senyal: 2, no_abierta: 3, vetada: 4, enviada: 5, pendiente: 5, posicion: 6 };
const LLAMADA = { ok: "respondió", quota: "sin cuota", auth: "sin acceso", timeout: "no respondió a tiempo",
  error: "error", skipped_budget: "sin presupuesto", skipped_quota: "sin cuota", skipped_stale: "vela atrasada" };
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function pasosDelFlujo(f, c) {
  const x = c.flujo;
  const ing = (f.servicios.ingesta || {}).estado;
  const ll = x.llamada_ia;
  const flags = Object.keys((f.noticias || {}).flags || {}).length;
  const decisor = flujoCartera === "ai"
    ? { titulo: "La IA elige", texto: !x.candidatos ? "sin llamada: no había candidatos"
        : ll ? `${LLAMADA[ll.resultado] || ll.resultado}${ll.latencia_s ? ` en ${num(ll.latencia_s, 0)} s` : ""}` : "sin llamada",
        estado: ll && ll.resultado !== "ok" ? "mal" : null }
    : { titulo: "La regla del baseline elige", texto: x.candidatos ? "el de mejor R:R" : "nada que elegir" };
  const modo = c.modo === "NORMAL" ? "normal" : c.modo.replace("CLOSE_ONLY_", "solo cierre: ").replace("HALTED", "parado").toLowerCase();
  return [
    { titulo: "Datos de OKX", texto: `${x.monedas} monedas, velas de 4 h`, activo: true,
      estado: ing === "ok" ? null : ing === "tarde" ? "aviso" : "mal", lado: chip(ESTADO[ing] || "sin datos", ing === "ok" ? "ok" : "aviso") },
    { titulo: "Filtros", texto: `${plural(x.pasan, "pasa", "pasan")}, ${plural(x.descartadas, "descartada", "descartadas")}`,
      activo: x.pasan > 0, lado: chip(flags ? plural(flags, "aviso", "avisos") : "sin avisos", flags ? "aviso" : "") },
    { titulo: "Candidatos", texto: x.candidatos ? plural(x.candidatos, "candidato", "candidatos") : "ninguno: sin setup",
      activo: x.candidatos > 0 },
    { ...decisor, activo: x.enviadas + x.vetadas > 0 },
    { titulo: "Motor de riesgo", texto: `${plural(x.enviadas, "enviada", "enviadas")}, ${plural(x.vetadas, "vetada", "vetadas")}`,
      activo: x.enviadas > 0, lado: chip(modo, c.modo === "NORMAL" ? "ok" : "aviso") },
    { titulo: "Órdenes (en papel)", texto: x.pendientes ? plural(x.pendientes, "entrada pendiente", "entradas pendientes") : "ninguna pendiente",
      activo: x.pendientes > 0 },
    { titulo: "Posiciones", texto: `${x.posiciones} de ${x.max_posiciones}`, activo: x.posiciones > 0,
      lado: x.posiciones >= x.max_posiciones ? chip("llena", "aviso") : null },
  ];
}

function pintarFlujo(f) {
  const disponibles = ORDEN_CARTERAS.filter((n) => f.carteras[n] && f.carteras[n].disponible && f.carteras[n].flujo);
  if (!disponibles.includes(flujoCartera)) flujoCartera = disponibles[0];
  const c = f.carteras[flujoCartera];
  if (!c || !c.flujo.vela_ms) { $("flujo").replaceChildren(el("p", { class: "vacio" }, "Sin datos")); return; }
  $("flujo-vela").textContent = `vela que cerró el ${hora(c.flujo.vela_ms + VELA_MS)}`;
  const boton = (texto, activo, alPulsar) => {
    const b = el("button", { type: "button", "aria-pressed": String(activo) }, texto);
    b.onclick = alPulsar;
    return b;
  };
  $("flujo-cartera").replaceChildren(...disponibles.map((n) =>
    boton(NOMBRE[n], n === flujoCartera, () => { flujoCartera = n; pintarFlujo(ultimaFoto); })));
  $("flujo-moneda").replaceChildren(boton("todas", flujoMoneda == null, () => { flujoMoneda = null; pintarFlujo(ultimaFoto); }),
    ...f.limites.whitelist.map((s) => boton(base(s), flujoMoneda === s, () => { flujoMoneda = s; pintarFlujo(ultimaFoto); })));

  const pasos = pasosDelFlujo(f, c);
  const m = flujoMoneda && c.por_moneda.monedas[flujoMoneda];
  const parada = m ? PARADA[m.estado] : null;
  // Una posicion o una entrada de una vela ANTERIOR no ha recorrido el camino de esta: solo se marca donde esta.
  const deAntes = m && ["posicion", "pendiente"].includes(m.estado) && !(m.pasos || []).includes("submitted");
  const colorParada = m && (["vetada", "descartada"].includes(m.estado) ? "aviso"
    : ["sin_senyal", "no_abierta"].includes(m.estado) ? "quieto" : "activo");
  $("flujo").replaceChildren(...pasos.map((p, i) => {
    let clase = p.estado || (p.activo ? "activo" : "");
    if (parada != null) clase = i === parada ? colorParada : i < parada && !deAntes ? "activo" : "fuera";
    const siguiente = pasos[i + 1];
    const fluye = siguiente && (parada != null ? i < parada && !deAntes : p.activo && siguiente.activo);
    const caja = el("div", { class: `etapa ${clase}${fluye ? " fluye" : ""}` },
      el("b", {}, p.titulo), p.lado || el("span"), el("span", { class: "t" }, p.texto));
    if (parada === i) {
      const [, texto] = ESTADO_MONEDA[m.estado] || ["", m.estado];
      caja.append(el("span", { class: "motivo" }, `${base(flujoMoneda)}: ${texto.toLowerCase()}`
        + (deAntes ? ", de una vela anterior" : "") + (m.detalle ? ` (${m.detalle})` : "")));
    }
    return caja;
  }));
}

function pintar(f) {
  ultimaFoto = f;
  pintarCarteras(f);
  pintarBandas(f);
  pintarTarjetas(f);
  pintarPapelL(f);
  pintarSistema(f);
  pintarAgresividad(f);
  pintarMonedas(f);
  pintarFlujo(f);
  estadoControles(f);
}

// --- La IA: una vela por fila (candidatos, lo que dijo, lo que hizo el motor) y el detalle desplegable ---

let historialPedido = 0;
let velasIA = [];
let filtroMoneda = "*";

function chipCandidato(c) {
  const abre = c.ia && c.ia.tipo === "open";
  const partes = [base(c.simbolo), SETUP[c.setup] || c.setup || ""];
  if (c.numeros) partes.push(`R:R ${num(c.numeros.rr, 1)}`);
  let texto = partes.filter(Boolean).join(" ");
  if (abre && c.ia.multiplicador != null && c.ia.multiplicador < 1) texto += ` · ×${num(c.ia.multiplicador, 1)}`;
  const titulo = !c.ia ? "la IA no lo menciona: cuenta como saltado" : abre ? "la IA lo abre" : "la IA lo salta";
  return el("span", { class: "cand " + (abre ? "abre" : "salta"), title: titulo }, texto);
}

function veredictoMotor(c) {
  if (c.motor === "enviada") return el("div", { class: "veredicto" }, el("b", { class: "num" }, base(c.simbolo)), chip("enviada", "ok"));
  if (c.motor === "vetada") return el("div", { class: "veredicto" }, el("b", { class: "num" }, base(c.simbolo)), chip("vetada", "mal"),
    el("span", { class: "gris" }, c.veto || ""));
  return null;
}

function detalleCandidatos(v) {
  const con = v.candidatos.filter((c) => c.ia && (c.ia.motivos.length || c.ia.riesgos.length));
  if (!con.length) return null;
  const d = el("details", { class: "motivos" }, el("summary", {}, "Motivos y riesgos que escribió la IA"));
  for (const c of con) {
    const cab = el("div", {}, el("b", {}, c.simbolo), " ",
      el("span", { class: "gris" }, [c.ia.tipo === "open" ? "abre" : "salta",
        c.ia.confianza != null ? `confianza ${num(c.ia.confianza, 2)}` : null,
        c.numeros ? `entrada ${precio(c.numeros.entrada)} · stop ${num(c.numeros.stop_pct, 1)} % · objetivo ${num(c.numeros.objetivo_pct, 1, true)} %` : null]
        .filter(Boolean).join(" · ")));
    const caja = el("div", { class: "motivo-cand" }, cab);
    if (c.ia.motivos.length) caja.append(el("ul", {}, ...c.ia.motivos.map((m) => el("li", {}, m))));
    if (c.ia.riesgos.length) caja.append(el("ul", { class: "riesgos" }, ...c.ia.riesgos.map((m) => el("li", {}, "Riesgo: " + m))));
    d.append(caja);
  }
  return d;
}

function filaVela(v) {
  const cierre = v.vela_ms + VELA_MS;
  const cuando = el("time", {}, soloHora(cierre), el("small", {}, soloDia(cierre)),
    el("small", {}, v.latencia_s != null ? `${num(v.latencia_s, 0)} s` : ""));
  const pasos = el("div", { class: "pasos" });
  const paso = (etiqueta, ...contenido) => pasos.append(el("div", { class: "paso" }, el("span", { class: "label" }, etiqueta),
    el("div", {}, ...contenido)));
  paso("Candidatos", v.candidatos.length ? el("div", { class: "cands" }, ...v.candidatos.map(chipCandidato))
    : el("span", { class: "gris" }, "ninguno"));
  if (v.resultado !== "ok") paso("IA", el("div", { class: "veredicto" }, chip("sin decisión", "aviso"),
    el("span", { class: "gris" }, `${v.resultado}${v.motivo ? ": " + v.motivo : ""}`)));
  else paso("IA", v.lectura ? el("p", { class: "porque" }, `«${v.lectura}»`) : el("span", { class: "gris" }, v.motivo || ""));
  const motor = v.candidatos.map(veredictoMotor).filter(Boolean);
  paso("Motor", motor.length ? el("div", { class: "veredictos" }, ...motor) : el("span", { class: "gris" }, "nada que enviar"));
  const detalle = detalleCandidatos(v);
  if (detalle) paso("", detalle);
  return el("article", { class: "vela", "data-m": v.candidatos.map((c) => base(c.simbolo)).join(" ") }, cuando, pasos);
}

function pintarDecisiones() {
  const monedas = [...new Set(velasIA.flatMap((v) => v.candidatos.map((c) => base(c.simbolo))))].sort();
  if (filtroMoneda !== "*" && !monedas.includes(filtroMoneda)) filtroMoneda = "*";
  $("filtro").replaceChildren(...(monedas.length > 1 ? ["*", ...monedas] : []).map((m) => {
    const b = el("button", { type: "button", "aria-pressed": String(m === filtroMoneda) }, m === "*" ? "todas" : m);
    b.onclick = () => { filtroMoneda = m; pintarDecisiones(); };
    return b;
  }));
  const visibles = velasIA.filter((v) => filtroMoneda === "*" || v.candidatos.some((c) => base(c.simbolo) === filtroMoneda));
  $("decisiones").replaceChildren(...(visibles.length ? visibles.map(filaVela)
    : [el("p", { class: "vacio" }, "La IA aún no ha decidido nada: solo se la llama cuando hay candidatos.")]));
}

function pintarOperaciones(ops) {
  ops.sort((a, b) => b.closed_ts_ms - a.closed_ts_ms);
  $("operaciones").replaceChildren(ops.length ? tabla([["Cierre", 1], ["Cartera"], ["Par"], ["Setup", 0, "m-oculta"],
    ["Entrada", 1, "m-oculta"], ["Salida", 1, "m-oculta"], ["Neto", 1], ["R", 1], ["Duración", 1, "m-oculta"], ["Salida por"]],
  ops.map((o) => {
    const [clase, texto] = MOTIVO[o.reason] || ["", o.reason];
    return [hora(o.closed_ts_ms).replace(" UTC", ""), chipCartera(o.cartera), [o.symbol, "par"], SETUP[o.setup] || o.setup,
      precio(o.entry_price), precio(o.exit_price), [usd(o.net_pnl_usd, true), signoClase(o.net_pnl_usd)],
      [num(o.r_multiple, 2, true), signoClase(o.r_multiple)],
      // Entrada y salida en la misma vela de 4 h (la XRP del 07/10): "0 s" no dice nada.
      o.closed_ts_ms - o.opened_ts_ms < VELA_MS ? "misma vela" : hace(o.closed_ts_ms - o.opened_ts_ms), chip(texto, clase)];
  })) : el("p", { class: "vacio" }, "Todavía ninguna: las posiciones se cierran en su stop o en su objetivo."));
}

// --- La curva comparada (Lightweight Charts, guardado en ui/vendor) ---

let grafico = null;
const series = {};

function color(variable) {
  return getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
}

function pintarCurva(c) {
  if (typeof LightweightCharts === "undefined") {
    $("curva-nota").textContent = "No se pudo cargar la librería de gráficos.";
    return;
  }
  if (!grafico) {
    grafico = LightweightCharts.createChart($("curva"), {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: color("--ink-3"), fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
      grid: { vertLines: { color: color("--line") }, horzLines: { color: color("--line") } },
      rightPriceScale: { borderColor: color("--line") },
      timeScale: { borderColor: color("--line"), timeVisible: true, fixLeftEdge: true, fixRightEdge: true, rightOffset: 0 },
      localization: { priceFormatter: (v) => usd(v) },
    });
    const opciones = { btc: ["--hold", 1], baseline: ["--base", 2], ai: ["--ia", 3] };
    for (const [k, [v, grosor]] of Object.entries(opciones)) {
      series[k] = grafico.addSeries(LightweightCharts.LineSeries, { color: color(v), lineWidth: grosor, priceLineVisible: false });
    }
  }
  for (const k of Object.keys(series)) {
    series[k].setData((c[k] || []).map(([ts, v]) => ({ time: Math.floor(ts / 1000), value: v })));
  }
  grafico.timeScale().fitContent();
  const n = (c.ai || c.baseline || []).length;
  $("curva-nota").textContent = n < 2 ? "Aún hay pocas velas: la curva se irá dibujando cada 4 horas." : "";
}

function cargarHistorial() {
  if (Date.now() - historialPedido < 60000) return;
  historialPedido = Date.now();
  fetch("/api/decisiones?limite=20").then((r) => r.json()).then((v) => { velasIA = v; pintarDecisiones(); }).catch(() => {});
  fetch("/api/curva").then((r) => r.json()).then(pintarCurva).catch(() => {});
  Promise.all(["baseline", "ai"].map((c) => fetch(`/api/operaciones?cartera=${c}&limite=100`).then((r) => r.json())))
    .then(([a, b]) => pintarOperaciones([...a, ...b])).catch(() => {});
}

// --- Los controles: POST /api/comandos, solo desde aqui (cabecera X-Ploutos-Panel; ver api/mando.py) ---

function mandar(orden, motivo = "") {
  $("aviso-accion").textContent = "Enviando...";
  fetch("/api/comandos", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ploutos-Panel": "1" },
    body: JSON.stringify({ orden, motivo }),
  }).then(async (r) => {
    const d = await r.json().catch(() => ({}));
    $("aviso-accion").textContent = r.ok ? d.respuesta : `No se ha hecho: ${d.detail || r.status}`;
  }).catch(() => { $("aviso-accion").textContent = "No se pudo contactar con el bot."; });
}

function preparaControles() {
  $("b-pause").onclick = () => confirm("¿Pausar las dos carteras? No abrirán nada nuevo.") && mandar("pause");
  $("b-resume").onclick = () => confirm("¿Quitar la pausa? Las dos carteras volverán a abrir operaciones.") && mandar("resume");
  $("b-kill").onclick = () => confirm("¿PARAR el bot? No abrirá ni gestionará nada hasta levantar la parada.") && mandar("kill");
  $("b-levantar").onclick = () => {
    const motivo = prompt("¿Por qué se levanta la parada? (queda apuntado)");
    if (motivo && motivo.trim()) mandar("levantar_kill", motivo.trim());
  };
  // Cerrar todo: doble confirmacion, como en la maqueta (el boton, y despues marcar que se entiende).
  const caja = $("confirmar"), chk = $("entiendo"), si = $("confirmar-si");
  $("b-cerrar").onclick = () => {
    const n = ultimaFoto ? posicionesAgrupadas(ultimaFoto).length : 0;
    $("confirmar-titulo").textContent = `¿Cerrar ${n === 1 ? "la posición abierta" : `las ${n} posiciones abiertas`} a mercado?`;
    caja.hidden = false; chk.checked = false; si.disabled = true; $("aviso-accion").textContent = "";
  };
  chk.onchange = () => { si.disabled = !chk.checked; };
  $("confirmar-no").onclick = () => { caja.hidden = true; $("aviso-accion").textContent = "Cancelado: no se ha vendido nada."; };
  si.onclick = () => { caja.hidden = true; mandar("cerrar_todo"); };
}
preparaControles();

function estadoControles(f) {
  const m = f.manual;
  const hayPos = Object.values(f.carteras).some((c) => c.disponible && c.posiciones.length);
  $("b-pause").disabled = !m.disponible || !!m.pausa_ms;
  $("b-resume").disabled = !m.disponible || !m.pausa_ms;
  $("b-kill").disabled = !m.disponible || !!m.parada_ms;
  $("b-levantar").disabled = !m.disponible || !m.parada_ms;
  $("b-cerrar").disabled = !m.disponible || !hayPos;
  if ($("b-cerrar").disabled) $("confirmar").hidden = true;
}

function frescura() {
  if (!ultimaFoto) return;
  $("fresco").textContent = `actualizado hace ${hace(Date.now() - recibida)}`;
}
setInterval(frescura, 1000);

function recibir(f) {
  recibida = Date.now();
  const carga = $("carga");
  if (carga && !carga.classList.contains("fuera")) {
    carga.classList.add("fuera");                 // la primera foto: fuera la pantalla de carga
    setTimeout(() => { carga.hidden = true; }, 400);
  }
  document.body.classList.remove("sin-conexion");
  $("caido").classList.remove("visible");
  pintar(f);
  frescura();
  cargarHistorial();
}

function conectar() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onmessage = (e) => recibir(JSON.parse(e.data));
  ws.onclose = () => {
    document.body.classList.add("sin-conexion");
    $("caido").classList.add("visible");
    setTimeout(conectar, 5000);
  };
}

// --- Paginas (el propietario, 29/09): cuatro, cada una con su direccion (#resumen, #ia, #operaciones, #sistema), asi el
// "atras" del movil funciona y se pueden guardar. La barra de estado y los avisos de pausa o parada salen en todas.
// Se pintan todas las secciones siempre; solo cambia cual se ve.
const PAGINAS = ["resumen", "ia", "operaciones", "sistema"];

function irA() {
  const pedida = location.hash.slice(1);
  const pag = PAGINAS.includes(pedida) ? pedida : "resumen";
  for (const p of PAGINAS) $("pag-" + p).hidden = p !== pag;
  for (const a of document.querySelectorAll(".paginas a")) {
    if (a.dataset.pag === pag) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  // La curva se ajusto con la pagina escondida (ancho 0): se reajusta al volver a verla.
  if (pag === "resumen" && grafico) requestAnimationFrame(() => grafico.timeScale().fitContent());
}
window.addEventListener("hashchange", () => { irA(); window.scrollTo(0, 0); });
irA();

fetch("/api/foto").then((r) => r.json()).then(recibir).catch(() => {});
conectar();
