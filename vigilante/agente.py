"""El agente: decide en qué gastar las consultas de hoy y qué merece un aviso.

No es un modelo de lenguaje: es un bucle con reglas explícitas.

    1. Planificar  qué fechas explorar y qué muestrear en Google, con un tope
                   diario y dando prioridad a lo marcado.
    2. Percibir    lanzar esas consultas.
    3. Recordar    guardar lo visto en data/ofertas.csv (de ahí sale "lo habitual").
    4. Decidir     separar marcado / fuera de lista y aplicar reglas distintas:
                   lo marcado avisa con poco; lo no marcado, solo si es un chollo.
    5. Actuar      escribir las recomendaciones del panel y mandar el aviso.
"""

import calendar
import csv
import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from . import avisos, historico
from . import catalogo as mod_catalogo
from . import intereses as mod_intereses
from .catalogo import Catalogo, Lugar
from .config import RAIZ
from .fuentes import google_flights, ryanair
from .intereses import Interes, Intereses
from .modelos import Hallazgo

CSV_OFERTAS = RAIZ / "data" / "ofertas.csv"
JSON_RECOMENDACIONES = RAIZ / "data" / "recomendaciones.json"
COLUMNAS = ["consultado", "origen", "destino", "ida", "vuelta", "precio", "aerolinea", "fuente"]

MAX_EXPLORACIONES = 14  # tope de rangos de fechas que se piden a Ryanair por ejecución
MAX_ESCALAS_GOOGLE = 1
ANTELACION_GOOGLE = 14  # días: no muestrear vuelos para pasado mañana
HORIZONTE_DIAS = 330  # las aerolíneas no venden más allá

BAJADA_MARCADO = 0.15  # lo marcado avisa si baja un 15 % respecto a lo habitual
BAJADA_OTRO = 0.35  # lo no marcado necesita un 35 %
MIN_DIAS_HISTORIA = 5
DIAS_HISTORIA = 30

MEJORA_PARA_REPETIR = 0.10  # repetir un aviso solo si mejora un 10 %...
DIAS_PARA_REPETIR = 21  # ...o han pasado tres semanas
MAX_AVISOS_MARCADOS = 6
MAX_AVISOS_OTROS = 3
MAX_PRESENTACION = 8

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


@dataclass(frozen=True)
class Periodo:
    id: str  # AAAA-MM
    etiqueta: str
    desde: date
    hasta: date


@dataclass(frozen=True)
class Candidato:
    hallazgo: Hallazgo
    lugar: Lugar
    marcado: bool
    motivos: tuple[str, ...] = ()
    visto: str | None = None  # día de la búsqueda, si no es la de hoy

    @property
    def clave(self) -> str:
        return f"{self.hallazgo.destino}|{self.hallazgo.mes}"


@dataclass
class Informe:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    avisos_marcados: list[Candidato] = field(default_factory=list)
    avisos_otros: list[Candidato] = field(default_factory=list)
    presentacion: list[Candidato] = field(default_factory=list)
    recomendaciones: dict = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    consultas: int = 0

    @property
    def hay_aviso(self) -> bool:
        return bool(self.avisos_marcados or self.avisos_otros or self.presentacion)


# ---------------------------------------------------------------- planificar


def periodos(hoy: date, meses: int) -> list[Periodo]:
    """Lo que queda del mes actual (si son 3 días o más) y los `meses` siguientes."""
    resultado = []
    fin_mes = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
    if (fin_mes - hoy).days >= 3:
        resultado.append(_periodo(hoy.year, hoy.month, hoy + timedelta(days=1)))
    anio, mes = hoy.year, hoy.month
    for _ in range(meses):
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
        resultado.append(_periodo(anio, mes))
    return resultado


def _periodo(anio: int, mes: int, desde: date | None = None) -> Periodo:
    return Periodo(
        id=f"{anio:04d}-{mes:02d}",
        etiqueta=f"{MESES[mes - 1]} {anio}",
        desde=desde or date(anio, mes, 1),
        hasta=date(anio, mes, calendar.monthrange(anio, mes)[1]),
    )


def plan_exploracion(
    intereses: Intereses, hoy: date, lista_periodos: list[Periodo]
) -> list[tuple[date, date, int, int]]:
    """Rangos (desde, hasta, noches_min, noches_max) que pedir a la fuente de exploración.

    Primero las fechas de lo marcado y después los meses generales: si hay que
    recortar por el tope, se recorta lo general.
    """
    manana, limite = hoy + timedelta(days=1), hoy + timedelta(days=HORIZONTE_DIAS)
    plan: list[tuple[date, date, int, int]] = []

    def anadir(desde: date, hasta: date, noches: tuple[int, int]) -> None:
        desde, hasta = max(desde, manana), min(hasta, limite)
        rango = (desde, hasta, *noches)
        if desde <= hasta and rango not in plan:
            plan.append(rango)

    generales = (intereses.noches_min, intereses.noches_max)
    for interes in intereses.paises.values():
        noches = intereses.noches_de(interes)
        for v in interes.ventanas:
            anadir(v.desde, v.hasta, noches)
        if not interes.ventanas and noches != generales:
            for p in lista_periodos:
                anadir(p.desde, p.hasta, noches)
    for p in lista_periodos:
        anadir(p.desde, p.hasta, generales)
    return plan[:MAX_EXPLORACIONES]


def ciudades_marcadas(intereses: Intereses, catalogo: Catalogo) -> list[tuple[Interes, list[str]]]:
    """Cada ciudad marcada con sus aeropuertos, el principal primero (Londres: LHR, LGW...).

    Un país sin ciudades elegidas cuenta con las suyas a las que vuela Ryanair,
    igual que en el panel.
    """
    grupos: dict[tuple[str, str], tuple[Interes, list[str]]] = {}
    for iso, interes in intereses.paises.items():
        for c in catalogo.paises[iso]["ciudades"]:  # el catálogo pone primero las grandes
            elegida = c["iata"] in interes.ciudades if interes.ciudades else c.get("ry")
            if elegida:
                grupos.setdefault((iso, c["ciudad"]), (interes, []))[1].append(c["iata"])
    return list(grupos.values())


def plan_google(
    intereses: Intereses,
    catalogo: Catalogo,
    hoy: date,
    lista_periodos: list[Periodo],
    cursor: int,
    cubiertos: set[tuple[str, str]] | None = None,
    vistos: dict[tuple[str, str], str] | None = None,
) -> list[tuple[str, date, date]]:
    """Viajes (destino, ida, vuelta) que consultar hoy en Google.

    Cada ciudad marcada y mes es un hueco que llenar, para que el panel tenga
    precio de todas en todos los meses. Lo que hoy ya trae Ryanair (`cubiertos`,
    pares destino y mes) no hace falta. Del resto van primero los huecos que
    nunca se han visto y después los que llevan más tiempo sin mirarse (`vistos`:
    último día con precio de cada destino y mes), hasta el tope diario. Cada
    consulta es una fecha del mes, y el `cursor` (que avanza cada día) va
    cambiando la fecha y, a igual antigüedad, qué hueco va antes.
    """
    if intereses.consultas_google <= 0:
        return []
    cubiertos, vistos = cubiertos or set(), vistos or {}
    primer_dia = hoy + timedelta(days=ANTELACION_GOOGLE)
    ultimo_dia = hoy + timedelta(days=HORIZONTE_DIAS)

    # (último visto, vuelta, puesto, destino, días, noches). A igual antigüedad se
    # va por vueltas: un mes de cada ciudad, luego otro... para que todas tengan
    # algún precio cuanto antes. Cada ciudad empieza por un mes distinto y el
    # cursor lo va rotando, igual que la ciudad con que se empieza.
    huecos: list[tuple[str, int, int, str, list[date], int]] = []
    ciudades = ciudades_marcadas(intereses, catalogo)
    for k, (interes, aeropuertos) in enumerate(ciudades):
        noches_min, noches_max = intereses.noches_de(interes)
        de_la_ciudad = []
        for p in lista_periodos:
            if any((iata, p.id) in cubiertos for iata in aeropuertos):
                continue
            desde, hasta = max(p.desde, primer_dia), min(p.hasta, ultimo_dia)
            dias = [
                desde + timedelta(days=i)
                for i in range((hasta - desde).days + 1)
                if not interes.ventanas
                or any(v.contiene(desde + timedelta(days=i)) for v in interes.ventanas)
            ]
            if dias:
                visto = max(vistos.get((iata, p.id), "") for iata in aeropuertos)
                de_la_ciudad.append((visto, dias))
        m = len(de_la_ciudad)
        for j, (visto, dias) in enumerate(de_la_ciudad):
            puesto = (k - cursor) % len(ciudades)
            noches = (noches_min + noches_max) // 2
            huecos.append((visto, (j - cursor - k) % m, puesto, aeropuertos[0], dias, noches))

    plan = []
    for _, _, puesto, destino, dias, noches in sorted(huecos)[: intereses.consultas_google]:
        ida = dias[((cursor + puesto) * _paso(len(dias))) % len(dias)]
        plan.append((destino, ida, ida + timedelta(days=noches)))
    return plan


def _paso(n: int) -> int:
    """Un salto que no divide a n: recorrer de `paso` en `paso` visita todos los días."""
    return next((p for p in (7, 11, 13, 5, 3) if n % p), 1)


# ------------------------------------------------------------------ percibir


def percibir(
    intereses: Intereses,
    catalogo: Catalogo,
    hoy: date,
    lista_periodos: list[Periodo],
    cursor: int,
    explorar: Callable = ryanair.explorar,
    ida_vuelta: Callable = google_flights.consultar_ida_vuelta,
    pausa: float = 1.0,
    vistos: dict[tuple[str, str], str] | None = None,
) -> Informe:
    """Primero Ryanair; después Google para los huecos marcados que Ryanair no ha llenado."""
    informe = Informe()

    fallos_seguidos = 0
    for desde, hasta, noches_min, noches_max in plan_exploracion(intereses, hoy, lista_periodos):
        if informe.consultas:
            time.sleep(pausa)
        informe.consultas += 1
        try:
            informe.hallazgos += explorar(intereses.origen, desde, hasta, noches_min, noches_max)
            fallos_seguidos = 0
        except Exception as e:
            informe.errores.append(f"Ryanair {desde:%d-%m}…{hasta:%d-%m}: {e}")
            fallos_seguidos += 1
            if fallos_seguidos >= 2:  # si está caída o nos bloquea, no insistir
                informe.errores.append("Ryanair: dos fallos seguidos, dejo de explorar por hoy")
                break

    cubiertos = set()
    for h in informe.hallazgos:
        lugar = catalogo.lugar(h.destino)
        ida, vuelta = date.fromisoformat(h.ida), date.fromisoformat(h.vuelta)
        if lugar and intereses.interes_de(lugar.pais, h.destino, ida, (vuelta - ida).days):
            cubiertos.add((h.destino, h.mes))

    plan = plan_google(intereses, catalogo, hoy, lista_periodos, cursor, cubiertos, vistos)
    for destino, ida, vuelta in plan:
        time.sleep(pausa * 2)
        informe.consultas += 1
        try:
            ofertas, contexto = ida_vuelta(
                intereses.origen, destino, ida.isoformat(), vuelta.isoformat()
            )
        except Exception as e:
            informe.errores.append(f"Google {destino} {ida:%d-%m}: {e}")
            continue
        validas = [o for o in ofertas if o.escalas <= MAX_ESCALAS_GOOGLE]
        if validas:
            mejor = min(validas, key=lambda o: o.precio)
            informe.hallazgos.append(
                Hallazgo(
                    origen=intereses.origen,
                    destino=destino,
                    ida=ida.isoformat(),
                    vuelta=vuelta.isoformat(),
                    precio=mejor.precio,
                    aerolinea=mejor.aerolinea,
                    fuente="google_flights",
                    rango_tipico=contexto.rango_tipico,
                )
            )
    return informe


# ------------------------------------------------------------------ recordar


def guardar_hallazgos(hallazgos: list[Hallazgo], hoy: date, ruta: Path | None = None) -> None:
    ruta = ruta or CSV_OFERTAS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(COLUMNAS)
        for h in hallazgos:
            w.writerow(
                [hoy.isoformat(), h.origen, h.destino, h.ida, h.vuelta, f"{h.precio:g}",
                 h.aerolinea, h.fuente]  # fmt: skip
            )


def precios_habituales(hoy: date, ruta: Path | None = None) -> dict[tuple[str, str], float]:
    """Mediana del mejor precio diario de cada (destino, mes de viaje) en los últimos días.

    Solo para los que tienen días suficientes: con dos datos no hay "habitual".
    """
    ruta = ruta or CSV_OFERTAS
    if not ruta.exists():
        return {}
    desde = hoy - timedelta(days=DIAS_HISTORIA)
    minimos: dict[tuple[str, str], dict[str, float]] = {}
    with ruta.open(newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            dia = date.fromisoformat(fila["consultado"])
            if not (desde <= dia < hoy):
                continue
            por_dia = minimos.setdefault((fila["destino"], fila["ida"][:7]), {})
            precio = float(fila["precio"])
            por_dia[fila["consultado"]] = min(precio, por_dia.get(fila["consultado"], precio))
    return {
        clave: median(por_dia.values())
        for clave, por_dia in minimos.items()
        if len(por_dia) >= MIN_DIAS_HISTORIA
    }


def ultimos_vistos(
    intereses: Intereses,
    catalogo: Catalogo,
    hoy: date,
    ruta: Path | None = None,
) -> list[Candidato]:
    """Lo último que se vio de cada destino marcado y mes en los días anteriores a hoy.

    Google solo mira unas pocas fechas al día, así que muchos destinos marcados
    no tienen precio en la búsqueda de hoy; el panel enseña entonces este, con
    el día en que se vio, por viejo que sea. Cuenta solo el día más reciente:
    un mínimo de hace semanas no dice nada del precio de ahora.
    """
    ruta = ruta or CSV_OFERTAS
    if not ruta.exists():
        return []
    ultimos: dict[tuple[str, str], tuple[str, Hallazgo]] = {}
    with ruta.open(newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            dia = fila["consultado"]
            if fila["origen"] != intereses.origen or date.fromisoformat(dia) >= hoy:
                continue
            ida, vuelta = date.fromisoformat(fila["ida"]), date.fromisoformat(fila["vuelta"])
            lugar = catalogo.lugar(fila["destino"])
            if ida <= hoy or lugar is None:
                continue
            if intereses.interes_de(lugar.pais, lugar.iata, ida, (vuelta - ida).days) is None:
                continue
            h = Hallazgo(
                fila["origen"], fila["destino"], fila["ida"], fila["vuelta"],
                float(fila["precio"]), fila["aerolinea"], fila["fuente"],
            )  # fmt: skip
            actual = ultimos.get((h.destino, h.mes))
            if actual is None or (dia, -h.precio) > (actual[0], -actual[1].precio):
                ultimos[(h.destino, h.mes)] = (dia, h)
    return [
        Candidato(h, catalogo.lugar(h.destino), marcado=True, visto=dia)
        for dia, h in ultimos.values()
    ]


# ------------------------------------------------------------------- decidir


def decidir(
    informe: Informe,
    intereses: Intereses,
    catalogo: Catalogo,
    hoy: date,
    lista_periodos: list[Periodo],
    habituales: dict[tuple[str, str], float],
    estado: dict,
    anteriores: list[Candidato] | None = None,
) -> None:
    """Rellena en el informe los avisos y las recomendaciones a partir de los hallazgos.

    `anteriores` (ver `ultimos_vistos`) solo se usa en las recomendaciones del panel.
    """
    # El mejor precio de cada destino y mes, separado por si cubre un interés o no.
    mejores: dict[tuple[str, str, bool], Candidato] = {}
    for h in informe.hallazgos:
        lugar = catalogo.lugar(h.destino)
        if lugar is None:
            continue
        ida, vuelta = date.fromisoformat(h.ida), date.fromisoformat(h.vuelta)
        interes = intereses.interes_de(lugar.pais, h.destino, ida, (vuelta - ida).days)
        clave = (h.destino, h.mes, interes is not None)
        if clave not in mejores or h.precio < mejores[clave].hallazgo.precio:
            motivos = _motivos(h, interes, intereses, habituales.get((h.destino, h.mes)))
            mejores[clave] = Candidato(h, lugar, interes is not None, motivos)
    candidatos = sorted(mejores.values(), key=lambda c: c.hallazgo.precio)

    avisadas = estado.get("avisadas", {})
    novedades = [c for c in candidatos if c.motivos and _es_novedad(c, avisadas, hoy)]
    informe.avisos_marcados = [c for c in novedades if c.marcado][:MAX_AVISOS_MARCADOS]

    # De lo no marcado, un aviso por ciudad como mucho: si no, Marrakech en
    # noviembre, diciembre y enero se come los tres huecos.
    ya_avisados = {c.hallazgo.destino for c in informe.avisos_marcados}
    for c in novedades:
        if not c.marcado and c.hallazgo.destino not in ya_avisados:
            informe.avisos_otros.append(c)
            ya_avisados.add(c.hallazgo.destino)
        if len(informe.avisos_otros) >= MAX_AVISOS_OTROS:
            break

    # Primera lectura: al marcar un país, se manda una vez su mejor precio de hoy,
    # aunque no cumpla ninguna regla, para tener una referencia. Una línea por
    # país: si no, uno con muchas ciudades baratas tapa a los demás.
    ya_presentados = set(estado.get("presentados", [])) | {
        c.lugar.pais for c in informe.avisos_marcados
    }
    for c in candidatos:  # van de más barato a más caro
        if c.marcado and c.lugar.pais not in ya_presentados:
            ya_presentados.add(c.lugar.pais)
            informe.presentacion.append(c)
    informe.presentacion = informe.presentacion[:MAX_PRESENTACION]

    informe.recomendaciones = _recomendaciones(
        candidatos, anteriores or [], intereses, lista_periodos, hoy
    )


def _motivos(
    h: Hallazgo, interes, intereses: Intereses, habitual: float | None
) -> tuple[str, ...]:
    motivos = []
    if interes is not None:
        if interes.precio_max is not None and h.precio <= interes.precio_max:
            motivos.append(f"por debajo de tu máximo ({interes.precio_max:g} €)")
        if habitual and h.precio <= habitual * (1 - BAJADA_MARCADO):
            motivos.append(_texto_bajada(h.precio, habitual))
        if h.rango_tipico and h.precio < h.rango_tipico[0]:
            motivos.append(
                f"por debajo del rango típico de Google "
                f"({h.rango_tipico[0]:g}–{h.rango_tipico[1]:g} €)"
            )
    else:
        if h.precio <= intereses.chollo_max:
            motivos.append(f"chollo: no llega a {intereses.chollo_max:g} € ida y vuelta")
        if habitual and h.precio <= habitual * (1 - BAJADA_OTRO):
            motivos.append(_texto_bajada(h.precio, habitual))
    return tuple(motivos)


def _texto_bajada(precio: float, habitual: float) -> str:
    return f"{(1 - precio / habitual) * 100:.0f} % por debajo de lo habitual ({habitual:.0f} €)"


def _es_novedad(c: Candidato, avisadas: dict, hoy: date) -> bool:
    anterior = avisadas.get(c.clave)
    if anterior is None:
        return True
    if c.hallazgo.precio <= anterior["precio"] * (1 - MEJORA_PARA_REPETIR):
        return True
    return (hoy - date.fromisoformat(anterior["dia"])).days >= DIAS_PARA_REPETIR


def _recomendaciones(
    candidatos: list[Candidato],
    anteriores: list[Candidato],
    intereses: Intereses,
    lista_periodos: list[Periodo],
    hoy: date,
) -> dict:
    """Todo lo de hoy (lo mejor de cada destino y mes) para que el panel filtre y agrupe.

    Un destino marcado sin precio hoy en un mes lleva lo último que se vio de él.
    """
    meses = {p.id for p in lista_periodos}
    ofertas = [c for c in candidatos if c.hallazgo.mes in meses]
    de_hoy = {(c.hallazgo.destino, c.hallazgo.mes) for c in ofertas if c.marcado}
    ofertas += [
        c
        for c in anteriores
        if c.hallazgo.mes in meses and (c.hallazgo.destino, c.hallazgo.mes) not in de_hoy
    ]
    ofertas.sort(key=lambda c: (c.hallazgo.precio, c.hallazgo.ida))
    return {
        "generado": datetime.now().isoformat(timespec="minutes"),
        "dia": hoy.isoformat(),
        "origen": intereses.origen,
        "periodos": [{"id": p.id, "etiqueta": p.etiqueta} for p in lista_periodos],
        "ofertas": [_a_json(c, hoy) for c in ofertas],
    }


def _a_json(c: Candidato, hoy: date) -> dict:
    h = c.hallazgo
    return {
        "destino": h.destino,
        "ciudad": c.lugar.ciudad,
        "pais": c.lugar.pais,
        "pais_nombre": c.lugar.pais_nombre,
        "ida": h.ida,
        "vuelta": h.vuelta,
        "precio": h.precio,
        "aerolinea": h.aerolinea,
        "marcado": c.marcado,
        "motivos": list(c.motivos),
        "visto": c.visto or hoy.isoformat(),
        "enlace": enlace(h),
    }


def enlace(h: Hallazgo) -> str:
    """Búsqueda en Google Flights de ese viaje (sirve con cualquier aerolínea)."""
    texto = f"Flights from {h.origen} to {h.destino} on {h.ida} through {h.vuelta}"
    return f"https://www.google.com/travel/flights?hl=es&curr=EUR&q={urllib.parse.quote(texto)}"


# -------------------------------------------------------------------- actuar


def texto_candidato(c: Candidato) -> str:
    h = c.hallazgo
    ida, vuelta = date.fromisoformat(h.ida), date.fromisoformat(h.vuelta)
    linea = (
        f"{c.lugar.ciudad} ({c.lugar.pais_nombre}) · {_fecha(ida)} → {_fecha(vuelta)} · "
        f"{h.precio:.0f} € i/v · {h.aerolinea}"
    )
    if c.motivos:
        linea += "\n  → " + " y ".join(c.motivos)
    return linea


def _fecha(d: date) -> str:
    return f"{d.day} {MESES[d.month - 1][:3]}"


def componer_aviso(informe: Informe) -> tuple[str, str, str]:
    """Título, cuerpo y enlace del aviso de hoy."""
    bloques = []
    if informe.avisos_marcados:
        bloques.append(
            "TUS DESTINOS\n" + "\n".join(texto_candidato(c) for c in informe.avisos_marcados)
        )
    if informe.presentacion:
        bloques.append(
            "PRIMERA LECTURA DE LO QUE HAS MARCADO\n"
            + "\n".join(texto_candidato(c) for c in informe.presentacion)
        )
    if informe.avisos_otros:
        bloques.append(
            "FUERA DE TU LISTA\n" + "\n".join(texto_candidato(c) for c in informe.avisos_otros)
        )
    principal = (informe.avisos_marcados or informe.presentacion or informe.avisos_otros)[0]
    prefijo = "Vuelos" if principal.marcado else "Chollo fuera de tu lista"
    titulo = f"{prefijo}: {principal.lugar.ciudad} {principal.hallazgo.precio:.0f} € i/v"
    return titulo, "\n\n".join(bloques), enlace(principal.hallazgo)


def correr(canales: tuple[str, ...], dry_run: bool = False, hoy: date | None = None) -> Informe:
    """Una ejecución completa del agente, con sus ficheros y su aviso."""
    hoy = hoy or date.today()
    catalogo = mod_catalogo.cargar()
    intereses = mod_intereses.construir(mod_intereses.leer(catalogo))
    estado_total = historico.leer_estado()
    estado = estado_total.setdefault("agente", {})
    lista_periodos = periodos(hoy, intereses.meses)

    anteriores = ultimos_vistos(intereses, catalogo, hoy)
    vistos = {(c.hallazgo.destino, c.hallazgo.mes): c.visto for c in anteriores}
    informe = percibir(
        intereses, catalogo, hoy, lista_periodos, estado.get("cursor", 0), vistos=vistos
    )
    decidir(
        informe, intereses, catalogo, hoy, lista_periodos, precios_habituales(hoy), estado,
        anteriores,
    )  # fmt: skip
    if dry_run:
        return informe

    guardar_hallazgos(informe.hallazgos, hoy)
    if informe.hallazgos:  # si hoy no se ha podido consultar, se conservan las de ayer
        JSON_RECOMENDACIONES.write_text(
            json.dumps(informe.recomendaciones, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    if informe.hay_aviso:
        titulo, cuerpo, url = componer_aviso(informe)
        errores = avisos.enviar(canales, titulo, cuerpo, url, urgente=bool(informe.avisos_marcados))
        informe.errores += [f"aviso: {e}" for e in errores]
        if not errores:
            avisadas = estado.setdefault("avisadas", {})
            for c in informe.avisos_marcados + informe.avisos_otros:
                avisadas[c.clave] = {"precio": c.hallazgo.precio, "dia": hoy.isoformat()}
            estado["presentados"] = sorted(
                set(estado.get("presentados", []))
                | {c.lugar.pais for c in informe.presentacion + informe.avisos_marcados}
            )
    elif not informe.hallazgos and informe.errores:
        avisos.enviar(
            canales, "Vigilante de vuelos: el agente no pudo consultar", "\n".join(informe.errores)
        )

    # Los países que ya no están marcados se olvidan: si se vuelven a marcar,
    # tendrán otra primera lectura.
    estado["presentados"] = [p for p in estado.get("presentados", []) if p in intereses.paises]
    estado["cursor"] = estado.get("cursor", 0) + 1
    estado["ultima"] = {
        "cuando": datetime.now().isoformat(timespec="minutes"),
        "hallazgos": len(informe.hallazgos),
        "consultas": informe.consultas,
        "errores": informe.errores,
    }
    historico.guardar_estado(estado_total)
    return informe
