"""Fuente: Google Flights (sin API oficial).

Usa `fast-flights` para construir la búsqueda y descargar la página, pero el
parseo es propio: la versión 3.1.0 de la librería solo lee la lista "otros
vuelos" y se deja fuera "mejores vuelos", que es donde suele estar el más
barato (comprobado el 2026-10-13: daba 84 € cuando había un directo a 55 €).

Frágil por naturaleza: los índices de abajo son la estructura interna de la
página de Google y pueden cambiar sin aviso. Si cambia, falla con un error
claro y el vigilante avisa de que no pudo consultar.
"""

import json

from fast_flights import FlightQuery, Passengers, create_query
from primp import Client
from selectolax.lexbor import LexborHTMLParser

from ..modelos import Consulta, Contexto, Oferta, Resultado

URL = "https://www.google.com/travel/flights"

# Desde la UE Google redirige a consent.google.com antes de enseñar resultados.
# Esta cookie equivale a pulsar "Rechazar todo" en ese aviso.
COOKIE_CONSENTIMIENTO = "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"

# Posiciones dentro del JSON incrustado en la página (script "ds:1").
_SECCIONES_VUELOS = (2, 3)  # "mejores vuelos" y "otros vuelos"
_SECCION_PRECIOS = 5


def consultar(consulta: Consulta) -> Resultado:
    """Solo ida en una fecha concreta."""
    payload, enlace = _buscar(
        [(consulta.fecha, consulta.origen, consulta.destino)],
        "one-way",
        consulta.adultos,
        consulta.moneda,
    )
    return Resultado(
        consulta=consulta,
        ofertas=parsear_ofertas(payload),
        enlace=enlace,
        contexto=parsear_contexto(payload),
    )


def consultar_ida_vuelta(
    origen: str, destino: str, ida: str, vuelta: str, adultos: int = 1, moneda: str = "EUR"
) -> tuple[list[Oferta], Contexto]:
    """Ida y vuelta en fechas concretas. El precio de cada oferta es el total."""
    payload, _ = _buscar(
        [(ida, origen, destino), (vuelta, destino, origen)], "round-trip", adultos, moneda
    )
    return parsear_ofertas(payload), parsear_contexto(payload)


def _buscar(
    tramos: list[tuple[str, str, str]], tipo: str, adultos: int, moneda: str
) -> tuple[list, str]:
    query = create_query(
        flights=[
            FlightQuery(date=fecha, from_airport=origen, to_airport=destino)
            for fecha, origen, destino in tramos
        ],
        seat="economy",
        trip=tipo,
        passengers=Passengers(adults=adultos),
        language="es",
        currency=moneda,
    )
    cliente = Client(
        impersonate="chrome_145",
        impersonate_os="macos",
        referer=True,
        cookie_store=True,
    )
    respuesta = cliente.get(
        URL, params=query.params(), headers={"Cookie": COOKIE_CONSENTIMIENTO}
    )
    if respuesta.status_code != 200:
        raise RuntimeError(f"Google respondió HTTP {respuesta.status_code}")
    if "consent.google" in respuesta.url:
        raise RuntimeError("Google ha devuelto el aviso de cookies en vez de vuelos")
    return extraer_payload(respuesta.text), query.url()


def extraer_payload(html: str) -> list:
    script = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if script is None:
        raise RuntimeError("La página no trae el bloque de datos de vuelos (ds:1)")
    datos = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if datos.endswith("errorHasStatus: true"):
        raise RuntimeError("Google devolvió un error en lugar de resultados")
    return json.loads(datos)


def parsear_ofertas(payload: list) -> list[Oferta]:
    ofertas: list[Oferta] = []
    for indice in _SECCIONES_VUELOS:
        seccion = payload[indice]
        for entrada in (seccion[0] if seccion and seccion[0] else []):
            oferta = _parsear_oferta(entrada)
            if oferta is not None:
                ofertas.append(oferta)
    return sorted(ofertas, key=lambda o: o.precio)


def _parsear_oferta(entrada: list) -> Oferta | None:
    vuelo, precios = entrada[0], entrada[1]
    # Algunos vuelos salen listados sin precio: no sirven para vigilar.
    if not precios or not precios[0] or precios[0][1] is None:
        return None
    tramos = vuelo[2]
    return Oferta(
        precio=float(precios[0][1]),
        aerolineas=tuple(vuelo[1]),
        vuelos=tuple(f"{t[22][0]}{t[22][1]}" for t in tramos),
        salida=_fecha_hora(vuelo[4], vuelo[5]),
        llegada=_fecha_hora(vuelo[7], vuelo[8]),
        escalas=len(tramos) - 1,
        duracion_min=int(vuelo[9]),
    )


def _fecha_hora(fecha: list[int], hora: list[int | None] | None) -> str:
    # Google omite los ceros: [8] es 08:00 y [None, 31] es 00:31.
    h, m = [*(hora or []), None, None][:2]
    return f"{fecha[0]:04d}-{fecha[1]:02d}-{fecha[2]:02d} {h or 0:02d}:{m or 0:02d}"


def parsear_contexto(payload: list) -> Contexto:
    """Precio habitual, rango típico y mínimo de 60 días según Google.

    Es un extra informativo: si la estructura no cuadra, se devuelve vacío en
    vez de tumbar la consulta.
    """
    try:
        bloque = payload[_SECCION_PRECIOS]
        historial = [punto[1] for punto in bloque[10][0]]
        return Contexto(
            precio_habitual=float(bloque[2][1]),
            rango_tipico=(float(bloque[4][1]), float(bloque[5][1])),
            minimo_60d=float(min(historial)),
        )
    except (IndexError, TypeError, ValueError):
        return Contexto()
