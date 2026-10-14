/* Panel del vigilante de vuelos.
   Todo el estado vive en `E`; cada cambio de lo marcado se guarda en el servidor
   (data/intereses.json) y se vuelve a pintar. Los textos de datos externos entran
   siempre con textContent, nunca como HTML. Los textos propios salen de TEXTOS
   (textos.js), en el idioma elegido. */

const POR_PAGINA_MIOS = 5;
const POR_PAGINA_RESULTADOS = 7;
const POR_PAGINA_TUYOS = 12;
const POR_PAGINA_OTROS = 6;
const SIN_ACCESO = new Set(["visado", "no_admision"]);
const TODOS = "todos";

const E = {
  idioma: "es",
  paises: [],
  porIso: new Map(),
  lugares: new Map(), // iata -> ciudad del catálogo + iso de su país
  intereses: null,
  recomendaciones: { periodos: [], ofertas: [] },
  estado: null,
  paginaMios: 0,
  paginaResultados: 0,
  paginaTuyos: 0,
  paginaOtros: 0,
  consulta: "",
  conVisado: false,
  mes: TODOS,
  filtros: { desde: "", hasta: "", precio: null, destino: "" },
  mapa: null,
};

const $ = (id) => document.getElementById(id);

/** Crea un elemento. Los hijos de tipo texto se insertan como texto, no como HTML. */
function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (valor === false || valor == null) continue;
    if (clave === "class") nodo.className = valor;
    else if (clave.startsWith("on")) nodo.addEventListener(clave.slice(2), valor);
    else nodo.setAttribute(clave, valor === true ? "" : valor);
  }
  nodo.append(...hijos.filter((h) => h != null && h !== false));
  return nodo;
}

const normalizar = (texto) =>
  texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

// ------------------------------------------------------------ idioma y tema

/** Lo que el navegador recuerda entre visitas. Sin almacenamiento, se usa lo de siempre. */
function leerPreferencia(clave) {
  try {
    return localStorage.getItem(clave);
  } catch {
    return null;
  }
}

function guardarPreferencia(clave, valor) {
  try {
    localStorage.setItem(clave, valor);
  } catch {
    // ventana privada o almacenamiento bloqueado: vale solo para esta visita
  }
}

function t(clave, ...datos) {
  const texto = TEXTOS[E.idioma][clave] ?? TEXTOS.es[clave] ?? clave;
  return typeof texto === "function" ? texto(...datos) : texto;
}

const nombresIngles = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    return null;
  }
})();

/** Nombre del país en inglés (el catálogo solo lo tiene en español). */
function paisEnIngles(pais) {
  try {
    return nombresIngles?.of(pais.iso) || pais.nombre;
  } catch {
    return pais.nombre;
  }
}

const nombrePais = (pais) => (E.idioma === "en" ? paisEnIngles(pais) : pais.nombre);
const nombreCiudad = (ciudad) => (E.idioma === "en" && ciudad.en) || ciudad.ciudad;
const comparar = (a, b) => a.localeCompare(b, t("locale"));

function euros(precio) {
  return new Intl.NumberFormat(t("locale"), {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(Math.round(precio));
}

function fechaCorta(iso, conAnio = false) {
  const [anio, mes, dia] = iso.split("-").map(Number);
  return `${dia} ${t("mesesCortos")[mes - 1]}${conAnio ? " " + anio : ""}`;
}

/** "2026-11" -> "noviembre 2026" / "November 2026". */
function nombreMes(id) {
  const [anio, mes] = id.split("-").map(Number);
  return `${t("meses")[mes - 1]} ${anio}`;
}

function textoEntrada(entrada) {
  const base = t("entrada")[entrada.tipo] || t("entrada").sin_dato;
  return entrada.dias ? t("entrada.dias", base, entrada.dias) : base;
}

function pintarTextosFijos() {
  document.documentElement.lang = E.idioma;
  document.title = t("titulo");
  for (const nodo of document.querySelectorAll("[data-i18n]")) nodo.textContent = t(nodo.dataset.i18n);
  for (const nodo of document.querySelectorAll("[data-i18n-placeholder]")) {
    nodo.placeholder = t(nodo.dataset.i18nPlaceholder);
  }
  for (const nodo of document.querySelectorAll("[data-i18n-aria-label]")) {
    nodo.setAttribute("aria-label", t(nodo.dataset.i18nAriaLabel));
  }
  for (const boton of document.querySelectorAll("[data-idioma]")) {
    boton.setAttribute("aria-pressed", String(boton.dataset.idioma === E.idioma));
  }
}

function cambiarIdioma(idioma) {
  if (idioma === E.idioma || !TEXTOS[idioma]) return;
  E.idioma = idioma;
  guardarPreferencia("idioma", idioma);
  pintarTextosFijos();
  pintarTema();
  pintarTodo();
  pintarRecomendaciones();
  if (E.estado) pintarEstado(E.estado);
}

const temaSistema = matchMedia("(prefers-color-scheme: dark)");

/** El tema elegido en el panel, o si no el del sistema. */
const temaActual = () => document.documentElement.dataset.theme || (temaSistema.matches ? "dark" : "light");

function pintarTema() {
  const boton = $("tema");
  const oscuro = temaActual() === "dark";
  boton.classList.toggle("oscuro", oscuro);
  boton.setAttribute("aria-label", t(oscuro ? "tema.claro" : "tema.oscuro"));
  boton.title = t(oscuro ? "tema.claro" : "tema.oscuro");
}

function cambiarTema() {
  const tema = temaActual() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = tema;
  guardarPreferencia("tema", tema);
  pintarTema();
}

// ------------------------------------------------------------------ servidor

async function pedir(ruta, opciones) {
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || t("error.panel", respuesta.status));
  return datos;
}

/** Guarda lo marcado. Si el servidor lo rechaza, lanza el motivo y no cambia nada. */
async function guardar(nuevo) {
  E.intereses = await pedir("/api/intereses", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nuevo),
  });
  pintarTodo();
  pintarRecomendaciones();
}

function conPais(iso, datos) {
  const paises = { ...E.intereses.paises };
  if (datos === null) delete paises[iso];
  else paises[iso] = datos;
  return { ...E.intereses, paises };
}

const interesVacio = () => ({ ciudades: [], ventanas: [], precio_max: null, noches: null });

async function alternarPais(iso) {
  await guardar(conPais(iso, E.intereses.paises[iso] ? null : interesVacio())).catch(avisarError);
}

async function alternarCiudad(iso, iata) {
  const actual = E.intereses.paises[iso];
  if (!actual) return guardar(conPais(iso, { ...interesVacio(), ciudades: [iata] })).catch(avisarError);
  if (!actual.ciudades.length) return abrirFicha(iso); // ya entra con "todas": se afina en la ficha
  const ciudades = actual.ciudades.includes(iata)
    ? actual.ciudades.filter((c) => c !== iata)
    : [...actual.ciudades, iata];
  await guardar(conPais(iso, ciudades.length ? { ...actual, ciudades } : null)).catch(avisarError);
}

function avisarError(error) {
  const estado = $("estado");
  estado.textContent = error.message;
  estado.classList.add("mal");
}

/** Hasta oct-2026 el agente guardaba las ofertas dentro de cada mes: se aplanan. */
function leerRecomendaciones(datos) {
  const periodos = datos.periodos || [];
  const ofertas =
    datos.ofertas ||
    periodos.flatMap((p) => p.ofertas || []).map((o) => ({ visto: datos.dia, ...o }));
  return { ...datos, periodos, ofertas };
}

// --------------------------------------------------------------------- mapa

async function crearMapa() {
  const mundo = await fetch("vendor/countries-50m.json").then((r) => r.json());
  const porNum = new Map(E.paises.filter((p) => p.num).map((p) => [p.num, p.iso]));
  const formas = topojson
    .feature(mundo, mundo.objects.countries)
    .features.filter((f) => f.id !== "010") // sin la Antártida: no hay adónde volar
    .map((f) => ({ forma: f, iso: porNum.get(f.id) || (f.properties.name === "Kosovo" ? "XK" : null) }));

  const proyeccion = d3.geoNaturalEarth1().fitExtent(
    [[8, 8], [952, 462]],
    { type: "FeatureCollection", features: formas.map((f) => f.forma) },
  );
  const trazo = d3.geoPath(proyeccion);
  const svg = d3.select("#mapa");
  const lienzo = svg.append("g");
  const globo = $("globo");
  const seccion = document.querySelector(".mapa");

  const mostrarGlobo = (evento, iso) => {
    const pais = E.porIso.get(iso);
    if (!pais) return;
    globo.replaceChildren(el("strong", {}, nombrePais(pais)), textoEntrada(pais.entrada));
    if (E.intereses.paises[iso]) globo.append(el("div", {}, el("span", { class: "tuyo" }, t("en.lista"))));
    globo.hidden = false;
    const caja = seccion.getBoundingClientRect();
    const x = Math.min(evento.clientX - caja.left + 14, caja.width - globo.offsetWidth - 8);
    globo.style.left = `${Math.max(8, x)}px`;
    globo.style.top = `${evento.clientY - caja.top + 16}px`;
  };
  const ocultarGlobo = () => (globo.hidden = true);

  const paises = lienzo
    .append("g")
    .selectAll("path")
    .data(formas)
    .join("path")
    .attr("d", (d) => trazo(d.forma))
    .attr("class", (d) => (d.iso ? "pais elegible" : "pais"))
    .on("pointermove", (evento, d) => d.iso && mostrarGlobo(evento, d.iso))
    .on("pointerleave", ocultarGlobo)
    .on("click", (evento, d) => d.iso && abrirFicha(d.iso));
  const capaPuntos = lienzo.append("g");

  let escala = 1;
  const zoom = d3
    .zoom()
    .scaleExtent([1, 8])
    .translateExtent([[0, 0], [960, 470]])
    .filter((e) => e.type !== "wheel" && e.type !== "dblclick") // la rueda es para bajar por la página
    .on("zoom", (e) => {
      escala = e.transform.k;
      lienzo.attr("transform", e.transform);
      capaPuntos.selectAll("circle").attr("r", 4.5 / escala);
      ocultarGlobo();
    });
  svg.call(zoom);
  const calma = matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll("[data-zoom]").forEach((boton) =>
    boton.addEventListener("click", () => {
      const paso = svg.transition().duration(calma ? 0 : 220);
      if (boton.dataset.zoom === "todo") paso.call(zoom.transform, d3.zoomIdentity);
      else paso.call(zoom.scaleBy, boton.dataset.zoom === "acercar" ? 1.7 : 1 / 1.7);
    }),
  );

  const areas = new Map(formas.filter((f) => f.iso).map((f) => [f.iso, trazo.area(f.forma)]));

  E.mapa = {
    pintar() {
      const marcados = E.intereses.paises;
      paises.classed("marcado", (d) => Boolean(d.iso && marcados[d.iso]));
      // Los países diminutos (o que el mapa no dibuja) se señalan con un punto.
      const puntos = Object.keys(marcados)
        .map((iso) => E.porIso.get(iso))
        .filter((p) => p && p.centro && (areas.get(p.iso) ?? 0) < 60)
        .map((p) => ({ iso: p.iso, xy: proyeccion(p.centro) }));
      capaPuntos
        .selectAll("circle")
        .data(puntos, (d) => d.iso)
        .join("circle")
        .attr("class", "punto")
        .attr("cx", (d) => d.xy[0])
        .attr("cy", (d) => d.xy[1])
        .attr("r", 4.5 / escala)
        .on("pointermove", (evento, d) => mostrarGlobo(evento, d.iso))
        .on("pointerleave", ocultarGlobo)
        .on("click", (evento, d) => abrirFicha(d.iso));
    },
  };
}

function pintarLeyenda() {
  const nombres = Object.keys(E.intereses.paises)
    .map((iso) => E.porIso.get(iso))
    .filter(Boolean)
    .map(nombrePais);
  $("leyenda-texto").textContent = t("leyenda", nombres.length);
  $("mapa").setAttribute("aria-label", t("mapa.aria", nombres.sort(comparar)));
}

// ------------------------------------------------------------ listas y páginas

function pintarPaginas(nav, pagina, total, alCambiar) {
  nav.replaceChildren();
  if (total <= 1) return;
  nav.append(
    el("button", { type: "button", disabled: pagina === 0, onclick: () => alCambiar(pagina - 1) }, t("anterior")),
    el("span", { "aria-live": "polite" }, t("pagina", pagina + 1, total)),
    el("button", { type: "button", disabled: pagina >= total - 1, onclick: () => alCambiar(pagina + 1) }, t("siguiente")),
  );
}

/** Rellena con filas invisibles para que los botones de página no salten de sitio. */
function rellenar(lista, filas, porPagina, paginas) {
  if (paginas <= 1) return;
  for (let i = filas; i < porPagina; i++) lista.append(el("li", { class: "relleno", "aria-hidden": "true" }));
}

function botonMarcar(marcado, nombre, alPulsar) {
  return el(
    "button",
    {
      type: "button",
      class: "marcar",
      "aria-pressed": String(marcado),
      "aria-label": t("marcar.aria", marcado, nombre),
      onclick: alPulsar,
    },
    t(marcado ? "marcado" : "marcar"),
  );
}

function resumenInteres(interes) {
  const frases = [];
  if (interes.ciudades.length) {
    const nombres = interes.ciudades.map((c) => (E.lugares.has(c) ? nombreCiudad(E.lugares.get(c)) : c));
    frases.push([...new Set(nombres)].join(", "));
  } else {
    frases.push(t("resumen.todas"));
  }
  frases.push(
    interes.ventanas.length
      ? interes.ventanas
          .map((v) => t("resumen.ventana", fechaCorta(v.desde), fechaCorta(v.hasta, true)))
          .join(t("resumen.y"))
      : t("resumen.cualquiera"),
  );
  if (interes.precio_max) frases.push(t("resumen.precio", euros(interes.precio_max)));
  if (interes.noches) frases.push(t("resumen.noches", interes.noches[0], interes.noches[1]));
  return frases.join("; ") + ".";
}

function pintarMios() {
  const marcados = Object.entries(E.intereses.paises)
    .map(([iso, interes]) => ({ pais: E.porIso.get(iso), interes }))
    .filter((m) => m.pais)
    .sort((a, b) => comparar(nombrePais(a.pais), nombrePais(b.pais)));
  const paginas = Math.ceil(marcados.length / POR_PAGINA_MIOS);
  E.paginaMios = Math.max(0, Math.min(E.paginaMios, paginas - 1));

  $("mios-titulo").replaceChildren(t("mios.titulo"), marcados.length ? el("small", {}, ` ${marcados.length}`) : "");
  const lista = $("lista-mios");
  lista.replaceChildren();
  if (!marcados.length) {
    lista.append(el("li", { class: "vacio" }, el("strong", {}, t("mios.vacio")), t("mios.vacio.texto")));
  }
  const visibles = marcados.slice(E.paginaMios * POR_PAGINA_MIOS, (E.paginaMios + 1) * POR_PAGINA_MIOS);
  for (const { pais, interes } of visibles) {
    lista.append(
      el(
        "li",
        {},
        el(
          "div",
          { class: "datos" },
          el("button", { type: "button", class: "nombre", onclick: () => abrirFicha(pais.iso) }, nombrePais(pais)),
          el("span", { class: "detalle" }, resumenInteres(interes)),
        ),
        el("button", { type: "button", class: "boton secundario", onclick: () => abrirFicha(pais.iso) }, t("editar")),
      ),
    );
  }
  rellenar(lista, visibles.length, POR_PAGINA_MIOS, paginas);
  pintarPaginas($("paginas-mios"), E.paginaMios, paginas, (p) => {
    E.paginaMios = p;
    pintarMios();
  });
}

/** Se busca en los dos idiomas: "Alemania" y "Germany" encuentran lo mismo. */
function buscar() {
  const q = normalizar(E.consulta);
  const visibles = E.paises.filter((p) => E.conVisado || !SIN_ACCESO.has(p.entrada.tipo));
  if (!q) return visibles.map((pais) => ({ pais })).sort((a, b) => comparar(nombrePais(a.pais), nombrePais(b.pais)));

  const resultados = visibles
    .filter((p) => [p.nombre, paisEnIngles(p)].some((n) => normalizar(n).includes(q)) || p.iso.toLowerCase() === q)
    .map((pais) => ({ pais, orden: normalizar(nombrePais(pais)).startsWith(q) ? 0 : 1 }));
  if (q.length >= 2) {
    for (const pais of visibles) {
      for (const ciudad of pais.ciudades) {
        const nombres = [ciudad.ciudad, ciudad.en].filter(Boolean).map(normalizar);
        const esCodigo = ciudad.iata.toLowerCase() === q;
        if (
          esCodigo ||
          nombres.some((n) => n.includes(q)) ||
          (q.length >= 4 && normalizar(ciudad.aeropuerto).includes(q))
        ) {
          const peso = esCodigo ? 0 : nombres.some((n) => n.startsWith(q)) ? 2 : 3;
          resultados.push({ pais, ciudad, orden: peso + "LMS".indexOf(ciudad.tam) / 10 });
        }
      }
    }
  }
  return resultados.sort((a, b) => a.orden - b.orden);
}

function pintarResultados() {
  const resultados = buscar();
  const paginas = Math.ceil(resultados.length / POR_PAGINA_RESULTADOS);
  E.paginaResultados = Math.max(0, Math.min(E.paginaResultados, paginas - 1));
  const lista = $("resultados");
  lista.replaceChildren();
  if (!resultados.length) {
    lista.append(
      el(
        "li",
        { class: "vacio" },
        el("strong", {}, t("resultados.nada", E.consulta)),
        t(E.conVisado ? "resultados.prueba.visado" : "resultados.prueba"),
      ),
    );
  }
  const inicio = E.paginaResultados * POR_PAGINA_RESULTADOS;
  const visibles = resultados.slice(inicio, inicio + POR_PAGINA_RESULTADOS);
  for (const { pais, ciudad } of visibles) {
    const interes = E.intereses.paises[pais.iso];
    if (ciudad) {
      const marcada = Boolean(interes && (!interes.ciudades.length || interes.ciudades.includes(ciudad.iata)));
      lista.append(
        el(
          "li",
          {},
          el(
            "div",
            { class: "datos" },
            el(
              "button",
              { type: "button", class: "nombre", onclick: () => abrirFicha(pais.iso) },
              `${nombreCiudad(ciudad)} `,
              el("span", { class: "codigo" }, ciudad.iata),
            ),
            el("span", { class: "detalle" }, `${ciudad.aeropuerto}, ${nombrePais(pais)}`),
          ),
          botonMarcar(marcada, `${nombreCiudad(ciudad)} (${ciudad.iata})`, () => alternarCiudad(pais.iso, ciudad.iata)),
        ),
      );
    } else {
      lista.append(
        el(
          "li",
          {},
          el(
            "div",
            { class: "datos" },
            el("button", { type: "button", class: "nombre", onclick: () => abrirFicha(pais.iso) }, nombrePais(pais)),
            el("span", { class: "detalle" }, `${textoEntrada(pais.entrada)}. ${t("aeropuertos", pais.ciudades.length)}.`),
          ),
          botonMarcar(Boolean(interes), nombrePais(pais), () => alternarPais(pais.iso)),
        ),
      );
    }
  }
  rellenar(lista, visibles.length, POR_PAGINA_RESULTADOS, paginas);
  pintarPaginas($("paginas-resultados"), E.paginaResultados, paginas, (p) => {
    E.paginaResultados = p;
    pintarResultados();
  });
}

// ---------------------------------------------------------- recomendaciones

/** Las ciudades marcadas, una por nombre: Londres junta LHR, LGW, STN... */
function misCiudades() {
  const grupos = new Map();
  for (const [iso, interes] of Object.entries(E.intereses.paises)) {
    const pais = E.porIso.get(iso);
    if (!pais) continue;
    // Sin ciudades elegidas, el agente vigila las del país a las que vuela Ryanair.
    const ciudades = interes.ciudades.length
      ? pais.ciudades.filter((c) => interes.ciudades.includes(c.iata))
      : pais.ciudades.filter((c) => c.ry);
    for (const ciudad of ciudades) {
      const clave = `${iso}|${ciudad.ciudad}`;
      if (!grupos.has(clave)) grupos.set(clave, { clave, pais, ciudad, aeropuertos: new Set() });
      grupos.get(clave).aeropuertos.add(ciudad.iata);
    }
  }
  return [...grupos.values()];
}

/** ¿Encaja con lo escrito en el filtro de destino? Se mira en los dos idiomas. */
function coincide(q, ciudad, pais, aeropuertos) {
  if (!q) return true;
  const textos = [ciudad.ciudad, ciudad.en, pais.nombre, paisEnIngles(pais)].filter(Boolean).map(normalizar);
  return textos.some((texto) => texto.includes(q)) || aeropuertos.some((iata) => iata.toLowerCase() === q);
}

const hayFiltroDeViaje = () => Boolean(E.filtros.desde || E.filtros.hasta || E.filtros.precio);

/** Las ofertas del mes elegido que cumplen las fechas y el precio. */
function ofertasVisibles() {
  const { desde, hasta, precio } = E.filtros;
  return E.recomendaciones.ofertas.filter(
    (o) =>
      (E.mes === TODOS || o.ida.startsWith(E.mes)) &&
      (!desde || o.ida >= desde) &&
      (!hasta || o.ida <= hasta) &&
      (!precio || o.precio <= precio),
  );
}

function filaOferta(o, tuya) {
  const lugar = E.lugares.get(o.destino);
  const pais = E.porIso.get(o.pais);
  const noches = Math.round((new Date(o.vuelta) - new Date(o.ida)) / 86400000);
  const deOtroDia = o.visto && o.visto !== E.recomendaciones.dia;
  return el(
    "a",
    { class: tuya ? "oferta tuya" : "oferta", href: o.enlace, target: "_blank", rel: "noopener" },
    el("span", { class: "banda" }),
    el(
      "span",
      {},
      el("span", { class: "ciudad" }, lugar ? nombreCiudad(lugar) : o.ciudad),
      el("span", { class: "pais" }, `${pais ? nombrePais(pais) : o.pais_nombre} · ${o.destino}`),
    ),
    el(
      "span",
      {},
      el("span", { class: "fechas" }, `${fechaCorta(o.ida)} – ${fechaCorta(o.vuelta)}`),
      el("span", { class: "noches" }, t("noches", noches)),
    ),
    el("span", { class: "aerolinea" }, o.aerolinea),
    el(
      "span",
      { class: "precio" },
      euros(o.precio),
      el("small", {}, t("iv")),
      deOtroDia ? el("small", { class: "visto" }, t("visto", fechaCorta(o.visto))) : null,
    ),
  );
}

function filaSinPrecio(grupo) {
  return el(
    "div",
    { class: "oferta tuya sin-precio" },
    el("span", { class: "banda" }),
    el(
      "span",
      {},
      el("span", { class: "ciudad" }, nombreCiudad(grupo.ciudad)),
      el("span", { class: "pais" }, `${nombrePais(grupo.pais)} · ${[...grupo.aeropuertos].sort().join(" ")}`),
    ),
    el("span", { class: "falta" }, E.mes === TODOS ? t("sin.todavia") : t("sin.mes", nombreMes(E.mes))),
  );
}

/** Un bloque con título, filas y páginas. `filas` ya viene ordenado. */
function bloque({ titulo, ayuda, filas, pagina, porPagina, etiquetaPaginas, alCambiar, vacio, extra }) {
  const paginas = Math.ceil(filas.length / porPagina);
  const actual = Math.max(0, Math.min(pagina, paginas - 1));
  const lista = el("div", { class: "lista-ofertas" }, ...filas.slice(actual * porPagina, (actual + 1) * porPagina));
  if (!filas.length && vacio) lista.append(el("p", { class: "sin-ofertas" }, vacio));
  const nav = el("nav", { class: "paginas", "aria-label": etiquetaPaginas });
  pintarPaginas(nav, actual, paginas, alCambiar);
  return el("section", { class: "grupo" }, el("h3", {}, ...titulo), el("p", { class: "ayuda" }, ayuda), lista, extra, nav);
}

function pintarMeses() {
  const meses = $("meses");
  const pestanas = [
    { id: TODOS, etiqueta: t("rec.todos") },
    ...E.recomendaciones.periodos.map((p) => ({ id: p.id, etiqueta: nombreMes(p.id) })),
  ];
  meses.replaceChildren(
    ...pestanas.map((p) =>
      el(
        "button",
        {
          type: "button",
          role: "tab",
          "aria-selected": String(p.id === E.mes),
          onclick: () => {
            E.mes = p.id;
            E.paginaTuyos = E.paginaOtros = 0;
            pintarRecomendaciones();
          },
        },
        p.etiqueta,
      ),
    ),
  );
}

function pintarRecomendaciones() {
  const rec = E.recomendaciones;
  const panel = $("ofertas");
  panel.replaceChildren();
  $("rec-nota").textContent = "";
  $("f-limpiar").hidden = !(hayFiltroDeViaje() || E.filtros.destino);

  if (!rec.ofertas.length) {
    $("meses").hidden = $("filtros").hidden = true;
    panel.append(el("p", { class: "sin-ofertas" }, el("strong", {}, t("rec.vacio")), t("rec.vacio.texto")));
    return;
  }
  $("meses").hidden = $("filtros").hidden = false;
  if (!rec.periodos.some((p) => p.id === E.mes)) E.mes = TODOS;
  pintarMeses();

  const ofertas = ofertasVisibles();
  const q = normalizar(E.filtros.destino);
  const filtrando = hayFiltroDeViaje();

  // Tus destinos: siempre todas las ciudades marcadas, con su vuelo más barato.
  const mias = misCiudades();
  const conPrecio = [];
  const sinPrecio = [];
  for (const grupo of mias) {
    if (!coincide(q, grupo.ciudad, grupo.pais, [...grupo.aeropuertos])) continue;
    let mejor = null;
    for (const o of ofertas) {
      if (o.marcado && grupo.aeropuertos.has(o.destino) && (!mejor || o.precio < mejor.precio)) mejor = o;
    }
    if (mejor) conPrecio.push({ grupo, oferta: mejor });
    else sinPrecio.push(grupo);
  }
  conPrecio.sort((a, b) => a.oferta.precio - b.oferta.precio || a.oferta.ida.localeCompare(b.oferta.ida));
  sinPrecio.sort((a, b) => comparar(nombreCiudad(a.ciudad), nombreCiudad(b.ciudad)));

  // Con fechas o precio puestos, lo que no tiene vuelos se resume aparte en vez
  // de ocupar media lista; sin ellos, va al final con su "sin precio".
  const filasTuyas = conPrecio.map(({ oferta }) => filaOferta(oferta, true));
  let resumen = null;
  if (filtrando && sinPrecio.length) {
    resumen = el(
      "details",
      { class: "sin-vuelos" },
      el("summary", {}, t("sin.filtros", sinPrecio.length)),
      el("p", {}, sinPrecio.map((g) => nombreCiudad(g.ciudad)).join(", ")),
    );
  } else {
    filasTuyas.push(...sinPrecio.map(filaSinPrecio));
  }
  let vacioTuyo = null;
  if (!mias.length) vacioTuyo = t("rec.tuyos.ninguno");
  else if (!conPrecio.length && !sinPrecio.length) vacioTuyo = t("rec.tuyos.nada", E.filtros.destino);

  // Fuera de tu lista: lo más barato de cada ciudad que no has marcado.
  const misClaves = new Set(mias.map((g) => g.clave));
  const otras = new Map();
  for (const o of ofertas) {
    const lugar = E.lugares.get(o.destino);
    const pais = E.porIso.get(o.pais);
    if (o.marcado || !lugar || !pais) continue;
    const clave = `${lugar.pais}|${lugar.ciudad}`;
    if (misClaves.has(clave) || !coincide(q, lugar, pais, [o.destino])) continue;
    if (!otras.has(clave) || o.precio < otras.get(clave).precio) otras.set(clave, o);
  }
  const filasOtras = [...otras.values()]
    .sort((a, b) => a.precio - b.precio || a.ida.localeCompare(b.ida))
    .map((o) => filaOferta(o, false));

  panel.append(
    bloque({
      titulo: [t("rec.tuyos"), mias.length ? el("small", {}, ` ${conPrecio.length + sinPrecio.length}`) : null],
      ayuda: t("rec.tuyos.ayuda"),
      filas: filasTuyas,
      pagina: E.paginaTuyos,
      porPagina: POR_PAGINA_TUYOS,
      etiquetaPaginas: t("rec.paginas.tuyos"),
      alCambiar: (p) => {
        E.paginaTuyos = p;
        pintarRecomendaciones();
      },
      vacio: vacioTuyo,
      extra: resumen,
    }),
    bloque({
      titulo: [t("rec.otros")],
      ayuda: t("rec.otros.ayuda"),
      filas: filasOtras,
      pagina: E.paginaOtros,
      porPagina: POR_PAGINA_OTROS,
      etiquetaPaginas: t("rec.paginas.otros"),
      alCambiar: (p) => {
        E.paginaOtros = p;
        pintarRecomendaciones();
      },
      vacio: t("rec.otros.nada"),
    }),
  );

  const [dia, hora] = (rec.generado || "").split("T");
  const hayAntiguos = conPrecio.some(({ oferta }) => oferta.visto && oferta.visto !== rec.dia);
  $("rec-nota").textContent =
    t("rec.nota", rec.origen) +
    (dia ? t("rec.nota.cuando", fechaCorta(dia), hora) : "") +
    (hayAntiguos ? t("rec.nota.antiguos") : "") +
    t("rec.nota.enlace");
}

/** Los límites de las fechas del filtro: de mañana al final del último mes que se mira. */
function limitarFechasFiltro() {
  const periodos = E.recomendaciones.periodos;
  if (!periodos.length) return;
  const [anio, mes] = periodos.at(-1).id.split("-").map(Number);
  const ultimo = `${periodos.at(-1).id}-${String(new Date(anio, mes, 0).getDate()).padStart(2, "0")}`;
  for (const id of ["f-desde", "f-hasta"]) {
    $(id).min = E.recomendaciones.dia || "";
    $(id).max = ultimo;
  }
}

function prepararFiltros() {
  const alCambiar = () => {
    const precio = Number($("f-precio").value);
    E.filtros = {
      desde: $("f-desde").value,
      hasta: $("f-hasta").value,
      precio: precio > 0 ? precio : null,
      destino: $("f-destino").value,
    };
    E.paginaTuyos = E.paginaOtros = 0;
    pintarRecomendaciones();
  };
  for (const id of ["f-desde", "f-hasta", "f-precio", "f-destino"]) $(id).addEventListener("input", alCambiar);
  $("f-limpiar").addEventListener("click", () => {
    for (const id of ["f-desde", "f-hasta", "f-precio", "f-destino"]) $(id).value = "";
    alCambiar();
    $("f-desde").focus();
  });
}

// --------------------------------------------------------------- ficha de país

const ficha = { iso: null, borrador: null, esNuevo: false, elegidasAlAbrir: new Set() };

function abrirFicha(iso) {
  const pais = E.porIso.get(iso);
  if (!pais) return;
  const actual = E.intereses.paises[iso];
  ficha.iso = iso;
  ficha.esNuevo = !actual;
  ficha.borrador = structuredClone(actual || interesVacio());
  ficha.elegidasAlAbrir = new Set(ficha.borrador.ciudades);

  $("ficha-titulo").textContent = nombrePais(pais);
  $("ficha-entrada").textContent = textoEntrada(pais.entrada) + ".";
  $("ficha-guardar").textContent = t(ficha.esNuevo ? "ficha.marcar" : "ficha.guardar");
  $("ficha-quitar").hidden = ficha.esNuevo;
  $("ficha-error").hidden = true;
  $("ficha-filtro").value = "";
  $("ficha-filtro").hidden = pais.ciudades.length < 9;
  $("ficha-precio").value = ficha.borrador.precio_max ?? "";
  $("ficha-noches-min").value = ficha.borrador.noches?.[0] ?? "";
  $("ficha-noches-max").value = ficha.borrador.noches?.[1] ?? "";
  $("ficha-noches-min").placeholder = E.intereses.ajustes.noches_min;
  $("ficha-noches-max").placeholder = E.intereses.ajustes.noches_max;
  $("ficha-ciudades-ayuda").textContent = t(
    pais.ciudades.some((c) => c.ry) ? "ficha.ayuda.ryanair" : "ficha.ayuda.google",
  );

  pintarCiudadesFicha();
  pintarVentanasFicha();
  $("ficha").showModal();
}

function pintarCiudadesFicha() {
  const pais = E.porIso.get(ficha.iso);
  const filtro = normalizar($("ficha-filtro").value);
  const lista = $("ficha-ciudades");
  lista.replaceChildren();
  // Las que ya estaban elegidas al abrir van arriba (no se reordena mientras marcas).
  const visibles = pais.ciudades
    .filter((c) => !filtro || normalizar(`${c.ciudad} ${c.en || ""} ${c.aeropuerto} ${c.iata}`).includes(filtro))
    .sort((a, b) => ficha.elegidasAlAbrir.has(b.iata) - ficha.elegidasAlAbrir.has(a.iata));
  if (!visibles.length) lista.append(el("li", { class: "nada" }, t("ficha.nada")));
  for (const c of visibles) {
    const casilla = el("input", { type: "checkbox", checked: ficha.borrador.ciudades.includes(c.iata) });
    casilla.addEventListener("change", () => {
      const elegidas = new Set(ficha.borrador.ciudades);
      casilla.checked ? elegidas.add(c.iata) : elegidas.delete(c.iata);
      ficha.borrador.ciudades = [...elegidas];
    });
    lista.append(
      el(
        "li",
        {},
        el(
          "label",
          {},
          casilla,
          el("span", { class: "codigo" }, c.iata),
          el("span", { class: "lugar" }, nombreCiudad(c), el("span", { class: "aeropuerto" }, c.aeropuerto)),
          c.ry ? el("span", { class: "ryanair" }, "Ryanair") : null,
        ),
      ),
    );
  }
}

function pintarVentanasFicha() {
  const lista = $("ficha-ventanas");
  lista.replaceChildren();
  ficha.borrador.ventanas.forEach((ventana, i) => {
    const desde = el("input", { type: "date", value: ventana.desde, "aria-label": t("ficha.desde") });
    const hasta = el("input", { type: "date", value: ventana.hasta, "aria-label": t("ficha.hasta") });
    desde.addEventListener("change", () => (ventana.desde = desde.value));
    hasta.addEventListener("change", () => (ventana.hasta = hasta.value));
    lista.append(
      el(
        "li",
        {},
        t("ficha.del"),
        desde,
        t("ficha.al"),
        hasta,
        el(
          "button",
          {
            type: "button",
            class: "boton peligro",
            onclick: () => {
              ficha.borrador.ventanas.splice(i, 1);
              pintarVentanasFicha();
            },
          },
          t("ficha.quitar.fechas"),
        ),
      ),
    );
  });
}

function mostrarError(id, mensaje) {
  $(id).textContent = mensaje;
  $(id).hidden = false;
}

async function guardarFicha(evento) {
  evento.preventDefault();
  const b = ficha.borrador;
  const nMin = $("ficha-noches-min").value;
  const nMax = $("ficha-noches-max").value;
  if (Boolean(nMin) !== Boolean(nMax)) return mostrarError("ficha-error", t("ficha.error.noches"));
  const datos = {
    ciudades: b.ciudades,
    ventanas: b.ventanas.filter((v) => v.desde || v.hasta),
    precio_max: $("ficha-precio").value || null,
    noches: nMin ? [Number(nMin), Number(nMax)] : null,
  };
  try {
    await guardar(conPais(ficha.iso, datos));
    $("ficha").close();
  } catch (error) {
    mostrarError("ficha-error", error.message);
  }
}

// ------------------------------------------------------------------- ajustes

function abrirAjustes() {
  const a = E.intereses.ajustes;
  $("aj-meses").value = a.meses;
  $("aj-noches-min").value = a.noches_min;
  $("aj-noches-max").value = a.noches_max;
  $("aj-chollo").value = a.chollo_max;
  $("aj-google").value = a.consultas_google;
  $("ajustes-error").hidden = true;
  $("ajustes").showModal();
}

async function guardarAjustes(evento) {
  evento.preventDefault();
  const ajustes = {
    meses: $("aj-meses").value,
    noches_min: $("aj-noches-min").value,
    noches_max: $("aj-noches-max").value,
    chollo_max: $("aj-chollo").value,
    consultas_google: $("aj-google").value,
  };
  try {
    await guardar({ ...E.intereses, ajustes });
    $("ajustes").close();
  } catch (error) {
    mostrarError("ajustes-error", error.message);
  }
}

// ------------------------------------------------------- estado y búsqueda

function pintarOrigen() {
  $("origen").value = E.intereses.origen;
  const lugar = E.lugares.get(E.intereses.origen);
  $("origen-ciudad").textContent = lugar ? nombreCiudad(lugar) : "";
}

async function cambiarOrigen() {
  const nuevo = $("origen").value.trim().toUpperCase();
  if (nuevo === E.intereses.origen) return pintarOrigen();
  try {
    await guardar({ ...E.intereses, origen: nuevo });
    $("estado").classList.remove("mal");
    $("estado").textContent = t("estado.origen", nuevo);
  } catch (error) {
    pintarOrigen();
    avisarError(error);
  }
}

function pintarEstado(estado) {
  E.estado = estado;
  const linea = $("estado");
  const boton = $("buscar");
  boton.disabled = estado.buscando;
  boton.textContent = t(estado.buscando ? "buscando" : "buscar");
  linea.classList.remove("mal");
  if (estado.buscando) {
    linea.textContent = t("estado.buscando");
  } else if (!estado.ultima) {
    linea.textContent = t("estado.nunca");
  } else if (estado.ultima.errores?.length) {
    linea.classList.add("mal");
    linea.textContent = t("estado.fallos", estado.ultima.errores[0]);
  } else {
    const [dia, hora] = estado.ultima.cuando.split("T");
    linea.textContent = t("estado.ultima", fechaCorta(dia), hora, estado.ultima.hallazgos);
  }
}

async function seguirBusqueda() {
  const estado = await pedir("/api/estado");
  pintarEstado(estado);
  if (estado.buscando) return setTimeout(seguirBusqueda, 2000);
  E.recomendaciones = leerRecomendaciones(await pedir("/api/recomendaciones"));
  limitarFechasFiltro();
  pintarRecomendaciones();
}

async function buscarAhora() {
  try {
    await pedir("/api/buscar", { method: "POST" });
  } catch (error) {
    // Si ya había una en marcha, basta con seguirla.
  }
  seguirBusqueda();
}

// -------------------------------------------------------------------- inicio

function pintarTodo() {
  pintarOrigen();
  pintarLeyenda();
  E.mapa?.pintar();
  pintarMios();
  pintarResultados();
}

async function iniciar() {
  const [catalogo, intereses, recomendaciones, estado] = await Promise.all([
    pedir("/api/catalogo"),
    pedir("/api/intereses"),
    pedir("/api/recomendaciones"),
    pedir("/api/estado"),
  ]);
  E.paises = catalogo.paises;
  E.porIso = new Map(catalogo.paises.map((p) => [p.iso, p]));
  for (const p of catalogo.paises) for (const c of p.ciudades) E.lugares.set(c.iata, { ...c, pais: p.iso });
  E.intereses = intereses;
  E.recomendaciones = leerRecomendaciones(recomendaciones);

  $("consulta").addEventListener("input", (e) => {
    E.consulta = e.target.value;
    E.paginaResultados = 0;
    pintarResultados();
  });
  $("con-visado").addEventListener("change", (e) => {
    E.conVisado = e.target.checked;
    E.paginaResultados = 0;
    pintarResultados();
  });
  $("origen").addEventListener("change", cambiarOrigen);
  $("buscar").addEventListener("click", buscarAhora);
  $("abrir-ajustes").addEventListener("click", abrirAjustes);
  $("ajustes-form").addEventListener("submit", guardarAjustes);
  $("ajustes-cancelar").addEventListener("click", () => $("ajustes").close());
  $("ficha-form").addEventListener("submit", guardarFicha);
  $("ficha-cancelar").addEventListener("click", () => $("ficha").close());
  $("ficha-filtro").addEventListener("input", pintarCiudadesFicha);
  $("ficha-nueva-ventana").addEventListener("click", () => {
    ficha.borrador.ventanas.push({ desde: "", hasta: "" });
    pintarVentanasFicha();
  });
  $("ficha-quitar").addEventListener("click", async () => {
    await guardar(conPais(ficha.iso, null)).catch(avisarError);
    $("ficha").close();
  });
  prepararFiltros();
  limitarFechasFiltro();

  pintarTodo();
  pintarRecomendaciones();
  pintarEstado(estado);
  if (estado.buscando) seguirBusqueda();
  await crearMapa();
  E.mapa.pintar();
}

// El idioma y el tema van antes de pedir nada, para que la espera ya salga bien.
E.idioma = TEXTOS[leerPreferencia("idioma")] ? leerPreferencia("idioma") : "es";
pintarTextosFijos();
pintarTema();
$("tema").addEventListener("click", cambiarTema);
temaSistema.addEventListener("change", pintarTema);
for (const boton of document.querySelectorAll("[data-idioma]")) {
  boton.addEventListener("click", () => cambiarIdioma(boton.dataset.idioma));
}

iniciar().catch((error) => {
  document.body.prepend(el("p", { class: "error", role: "alert" }, t("error.carga", error.message)));
});
