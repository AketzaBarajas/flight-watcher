/* Panel del vigilante de vuelos.
   Todo el estado vive en `E`; cada cambio de lo marcado se guarda en el servidor
   (data/intereses.json) y se vuelve a pintar. Los textos de datos externos entran
   siempre con textContent, nunca como HTML. */

const POR_PAGINA_MIOS = 5;
const POR_PAGINA_RESULTADOS = 7;
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const ENTRADA = {
  propio: "Tu país",
  sin_visado: "Sin visado",
  visado_llegada: "Visado a la llegada",
  eta: "Autorización electrónica previa (tipo ESTA)",
  evisa: "Visado electrónico previo",
  visado: "Exige visado previo",
  no_admision: "No admite pasaporte español",
  sin_dato: "Sin dato de entrada (territorio dependiente)",
};
const SIN_ACCESO = new Set(["visado", "no_admision"]);

const E = {
  paises: [],
  porIso: new Map(),
  lugares: new Map(), // iata -> {ciudad, pais}
  intereses: null,
  recomendaciones: { periodos: [] },
  paginaMios: 0,
  paginaResultados: 0,
  consulta: "",
  conVisado: false,
  mes: null,
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

function fechaCorta(iso, conAnio = false) {
  const [anio, mes, dia] = iso.split("-").map(Number);
  return `${dia} ${MESES[mes - 1]}${conAnio ? " " + anio : ""}`;
}

function textoEntrada(entrada) {
  const base = ENTRADA[entrada.tipo] || ENTRADA.sin_dato;
  return entrada.dias ? `${base}, hasta ${entrada.dias} días` : base;
}

function plural(n, uno, varios) {
  return `${n} ${n === 1 ? uno : varios}`;
}

// ------------------------------------------------------------------ servidor

async function pedir(ruta, opciones) {
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || `El panel respondió ${respuesta.status}`);
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
    globo.replaceChildren(el("strong", {}, pais.nombre), textoEntrada(pais.entrada));
    if (E.intereses.paises[iso]) globo.append(el("div", {}, el("span", { class: "tuyo" }, "En tu lista")));
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
      const t = svg.transition().duration(calma ? 0 : 220);
      if (boton.dataset.zoom === "todo") t.call(zoom.transform, d3.zoomIdentity);
      else t.call(zoom.scaleBy, boton.dataset.zoom === "acercar" ? 1.7 : 1 / 1.7);
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
  const nombres = Object.keys(E.intereses.paises).map((iso) => E.porIso.get(iso)?.nombre).filter(Boolean);
  $("leyenda-texto").textContent = nombres.length
    ? plural(nombres.length, "país marcado", "países marcados")
    : "Ningún país marcado. Pulsa uno en el mapa o búscalo más abajo.";
  $("mapa").setAttribute(
    "aria-label",
    nombres.length ? `Mapa del mundo. Marcados: ${nombres.sort().join(", ")}.` : "Mapa del mundo. Ningún país marcado.",
  );
}

// ------------------------------------------------------------ listas y páginas

function pintarPaginas(nav, pagina, total, alCambiar) {
  nav.replaceChildren();
  if (total <= 1) return;
  nav.append(
    el("button", { type: "button", disabled: pagina === 0, onclick: () => alCambiar(pagina - 1) }, "Anterior"),
    el("span", { "aria-live": "polite" }, `Página ${pagina + 1} de ${total}`),
    el("button", { type: "button", disabled: pagina >= total - 1, onclick: () => alCambiar(pagina + 1) }, "Siguiente"),
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
      "aria-label": `${marcado ? "Quitar" : "Marcar"} ${nombre}`,
      onclick: alPulsar,
    },
    marcado ? "Marcado" : "Marcar",
  );
}

function resumenInteres(iso, interes) {
  const frases = [];
  if (interes.ciudades.length) {
    const nombres = [...new Set(interes.ciudades.map((c) => E.lugares.get(c)?.ciudad || c))];
    frases.push(nombres.join(", "));
  } else {
    frases.push("Todas las ciudades");
  }
  frases.push(
    interes.ventanas.length
      ? interes.ventanas.map((v) => `del ${fechaCorta(v.desde)} al ${fechaCorta(v.hasta, true)}`).join(" y ")
      : "cualquier fecha",
  );
  if (interes.precio_max) frases.push(`menos de ${interes.precio_max} €`);
  if (interes.noches) frases.push(`${interes.noches[0]} a ${interes.noches[1]} noches`);
  return frases.join("; ") + ".";
}

function pintarMios() {
  const marcados = Object.entries(E.intereses.paises)
    .map(([iso, interes]) => ({ pais: E.porIso.get(iso), interes }))
    .filter((m) => m.pais)
    .sort((a, b) => a.pais.nombre.localeCompare(b.pais.nombre, "es"));
  const paginas = Math.ceil(marcados.length / POR_PAGINA_MIOS);
  E.paginaMios = Math.max(0, Math.min(E.paginaMios, paginas - 1));

  $("mios-titulo").replaceChildren("Mis destinos", marcados.length ? el("small", {}, ` ${marcados.length}`) : "");
  const lista = $("lista-mios");
  lista.replaceChildren();
  if (!marcados.length) {
    lista.append(
      el(
        "li",
        { class: "vacio" },
        el("strong", {}, "Todavía no has marcado ningún destino."),
        "Búscalo a la derecha o púlsalo en el mapa. Lo marcado se vigila a diario; del resto solo te llegan los chollos.",
      ),
    );
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
          el("button", { type: "button", class: "nombre", onclick: () => abrirFicha(pais.iso) }, pais.nombre),
          el("span", { class: "detalle" }, resumenInteres(pais.iso, interes)),
        ),
        el("button", { type: "button", class: "boton secundario", onclick: () => abrirFicha(pais.iso) }, "Editar"),
      ),
    );
  }
  rellenar(lista, visibles.length, POR_PAGINA_MIOS, paginas);
  pintarPaginas($("paginas-mios"), E.paginaMios, paginas, (p) => {
    E.paginaMios = p;
    pintarMios();
  });
}

function buscar() {
  const q = normalizar(E.consulta);
  const visibles = E.paises.filter((p) => E.conVisado || !SIN_ACCESO.has(p.entrada.tipo));
  if (!q) return visibles.map((pais) => ({ pais }));

  const resultados = visibles
    .filter((p) => normalizar(p.nombre).includes(q) || p.iso.toLowerCase() === q)
    .map((pais) => ({ pais, orden: normalizar(pais.nombre).startsWith(q) ? 0 : 1 }));
  if (q.length >= 2) {
    for (const pais of visibles) {
      for (const ciudad of pais.ciudades) {
        const nombre = normalizar(ciudad.ciudad);
        const esCodigo = ciudad.iata.toLowerCase() === q;
        if (esCodigo || nombre.includes(q) || (q.length >= 4 && normalizar(ciudad.aeropuerto).includes(q))) {
          const peso = esCodigo ? 0 : nombre.startsWith(q) ? 2 : 3;
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
        el("strong", {}, `Nada con «${E.consulta}».`),
        E.conVisado
          ? "Prueba con el nombre del país, la ciudad o el código de tres letras del aeropuerto."
          : "Prueba con otro nombre, o activa los países que exigen visado previo.",
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
              `${ciudad.ciudad} `,
              el("span", { class: "codigo" }, ciudad.iata),
            ),
            el("span", { class: "detalle" }, `${ciudad.aeropuerto}, ${pais.nombre}`),
          ),
          botonMarcar(marcada, `${ciudad.ciudad} (${ciudad.iata})`, () => alternarCiudad(pais.iso, ciudad.iata)),
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
            el("button", { type: "button", class: "nombre", onclick: () => abrirFicha(pais.iso) }, pais.nombre),
            el(
              "span",
              { class: "detalle" },
              `${textoEntrada(pais.entrada)}. ${plural(pais.ciudades.length, "aeropuerto", "aeropuertos")}.`,
            ),
          ),
          botonMarcar(Boolean(interes), pais.nombre, () => alternarPais(pais.iso)),
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

function pintarRecomendaciones() {
  const periodos = E.recomendaciones.periodos || [];
  const meses = $("meses");
  const panel = $("ofertas");
  meses.replaceChildren();
  panel.replaceChildren();
  $("rec-nota").textContent = "";

  if (!periodos.some((p) => p.ofertas.length)) {
    meses.hidden = true;
    panel.append(
      el(
        "p",
        { class: "sin-ofertas" },
        el("strong", {}, "Todavía no hay ninguna búsqueda."),
        "Pulsa «Buscar vuelos ahora», arriba. Tarda medio minuto y después se repite sola cada día.",
      ),
    );
    return;
  }
  meses.hidden = false;
  if (!periodos.some((p) => p.id === E.mes)) E.mes = periodos.find((p) => p.ofertas.length).id;

  for (const p of periodos) {
    meses.append(
      el(
        "button",
        {
          type: "button",
          role: "tab",
          "aria-selected": String(p.id === E.mes),
          onclick: () => {
            E.mes = p.id;
            pintarRecomendaciones();
          },
        },
        p.etiqueta,
      ),
    );
  }

  const activo = periodos.find((p) => p.id === E.mes);
  if (!activo.ofertas.length) {
    panel.append(el("p", { class: "sin-ofertas" }, `La última búsqueda no encontró viajes para ${activo.etiqueta}.`));
  }
  for (const o of activo.ofertas) {
    const noches = Math.round((new Date(o.vuelta) - new Date(o.ida)) / 86400000);
    panel.append(
      el(
        "a",
        { class: o.marcado ? "oferta tuya" : "oferta", href: o.enlace, target: "_blank", rel: "noopener" },
        el("span", { class: "banda" }),
        el(
          "span",
          {},
          el("span", { class: "ciudad" }, o.ciudad),
          o.marcado ? el("span", { class: "etiqueta" }, "En tu lista") : null,
          el("span", { class: "pais" }, o.pais_nombre),
        ),
        el(
          "span",
          {},
          el("span", { class: "fechas" }, `${fechaCorta(o.ida)} – ${fechaCorta(o.vuelta)}`),
          el("span", { class: "noches" }, plural(noches, "noche", "noches")),
        ),
        el("span", { class: "aerolinea" }, o.aerolinea),
        el("span", { class: "precio" }, `${Math.round(o.precio)} €`, el("small", {}, "ida y vuelta")),
      ),
    );
  }

  const [dia, hora] = (E.recomendaciones.generado || "").split("T");
  $("rec-nota").textContent =
    `Precios por persona en tarifa básica, sin maleta, saliendo de ${E.recomendaciones.origen}. ` +
    (dia ? `Vistos el ${fechaCorta(dia)} a las ${hora}. ` : "") +
    "Cada fila abre esa búsqueda en Google Flights para comparar antes de comprar.";
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

  $("ficha-titulo").textContent = pais.nombre;
  $("ficha-entrada").textContent = textoEntrada(pais.entrada) + ".";
  $("ficha-guardar").textContent = ficha.esNuevo ? "Marcar país" : "Guardar cambios";
  $("ficha-quitar").hidden = ficha.esNuevo;
  $("ficha-error").hidden = true;
  $("ficha-filtro").value = "";
  $("ficha-filtro").hidden = pais.ciudades.length < 9;
  $("ficha-precio").value = ficha.borrador.precio_max ?? "";
  $("ficha-noches-min").value = ficha.borrador.noches?.[0] ?? "";
  $("ficha-noches-max").value = ficha.borrador.noches?.[1] ?? "";
  $("ficha-noches-min").placeholder = E.intereses.ajustes.noches_min;
  $("ficha-noches-max").placeholder = E.intereses.ajustes.noches_max;
  $("ficha-ciudades-ayuda").textContent = pais.ciudades.some((c) => c.ry)
    ? "Sin elegir ninguna, vigilo todas las ciudades del país a las que vuela Ryanair. Las demás solo se miran si las eliges aquí."
    : "Ryanair no vuela a este país: elige las ciudades que quieres que mire en Google. Sin ciudades elegidas no puedo vigilarlo.";

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
    .filter((c) => !filtro || normalizar(`${c.ciudad} ${c.aeropuerto} ${c.iata}`).includes(filtro))
    .sort((a, b) => ficha.elegidasAlAbrir.has(b.iata) - ficha.elegidasAlAbrir.has(a.iata));
  if (!visibles.length) lista.append(el("li", { class: "nada" }, "Ninguna ciudad coincide con el filtro."));
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
          el("span", { class: "lugar" }, c.ciudad, el("span", { class: "aeropuerto" }, c.aeropuerto)),
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
    const desde = el("input", { type: "date", value: ventana.desde, "aria-label": "Desde" });
    const hasta = el("input", { type: "date", value: ventana.hasta, "aria-label": "Hasta" });
    desde.addEventListener("change", () => (ventana.desde = desde.value));
    hasta.addEventListener("change", () => (ventana.hasta = hasta.value));
    lista.append(
      el(
        "li",
        {},
        "Del",
        desde,
        "al",
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
          "Quitar fechas",
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
  if (Boolean(nMin) !== Boolean(nMax)) {
    return mostrarError("ficha-error", "Rellena las dos casillas de noches, o deja las dos vacías.");
  }
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
  $("origen-ciudad").textContent = E.lugares.get(E.intereses.origen)?.ciudad || "";
}

async function cambiarOrigen() {
  const nuevo = $("origen").value.trim().toUpperCase();
  if (nuevo === E.intereses.origen) return pintarOrigen();
  try {
    await guardar({ ...E.intereses, origen: nuevo });
    $("estado").classList.remove("mal");
    $("estado").textContent = `Ahora busco saliendo de ${nuevo}. Pulsa «Buscar vuelos ahora» para actualizar.`;
  } catch (error) {
    pintarOrigen();
    avisarError(error);
  }
}

function pintarEstado(estado) {
  const linea = $("estado");
  const boton = $("buscar");
  boton.disabled = estado.buscando;
  boton.textContent = estado.buscando ? "Buscando…" : "Buscar vuelos ahora";
  linea.classList.remove("mal");
  if (estado.buscando) {
    linea.textContent = "Buscando vuelos. Suele tardar medio minuto.";
  } else if (!estado.ultima) {
    linea.textContent = "Aún no se ha hecho ninguna búsqueda.";
  } else if (estado.ultima.errores?.length) {
    linea.classList.add("mal");
    linea.textContent = `La última búsqueda tuvo fallos: ${estado.ultima.errores[0]}`;
  } else {
    const [dia, hora] = estado.ultima.cuando.split("T");
    linea.textContent = `Última búsqueda: ${fechaCorta(dia)} a las ${hora}, ${estado.ultima.hallazgos} viajes vistos.`;
  }
}

async function seguirBusqueda() {
  const estado = await pedir("/api/estado");
  pintarEstado(estado);
  if (estado.buscando) return setTimeout(seguirBusqueda, 2000);
  E.recomendaciones = await pedir("/api/recomendaciones");
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
  for (const p of catalogo.paises) for (const c of p.ciudades) E.lugares.set(c.iata, { ciudad: c.ciudad, pais: p.iso });
  E.intereses = intereses;
  E.recomendaciones = recomendaciones;

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

  pintarTodo();
  pintarRecomendaciones();
  pintarEstado(estado);
  if (estado.buscando) seguirBusqueda();
  await crearMapa();
  E.mapa.pintar();
}

iniciar().catch((error) => {
  document.body.prepend(
    el("p", { class: "error", role: "alert" }, `No he podido cargar el panel: ${error.message}`),
  );
});
