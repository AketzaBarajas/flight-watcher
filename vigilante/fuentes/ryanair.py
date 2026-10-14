"""Fuente de exploración: el buscador de tarifas de Ryanair.

A diferencia de Google Flights (una ruta y una fecha por consulta), aquí una
sola petición devuelve el ida y vuelta más barato a CADA destino de Ryanair
desde un aeropuerto, dentro de un rango de fechas. Por eso es la base del
"¿adónde puedo ir barato?".

Es una API interna de su web, sin documentar: solo vuelos de Ryanair, y puede
cambiar sin aviso.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from ..modelos import Hallazgo

URL = "https://www.ryanair.com/api/farfnd/v4/roundTripFares"
CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
# La API pagina de 20 en 20. El tope evita un bucle si cambia la paginación.
MAX_PAGINAS = 8
PAUSA = 0.7


def explorar(
    origen: str,
    salida_desde: date,
    salida_hasta: date,
    noches_min: int,
    noches_max: int,
    destino: str | None = None,
) -> list[Hallazgo]:
    """Ida y vuelta más barato a cada destino saliendo entre las dos fechas."""
    parametros = {
        "departureAirportIataCode": origen,
        "outboundDepartureDateFrom": salida_desde.isoformat(),
        "outboundDepartureDateTo": salida_hasta.isoformat(),
        "inboundDepartureDateFrom": (salida_desde + timedelta(days=noches_min)).isoformat(),
        "inboundDepartureDateTo": (salida_hasta + timedelta(days=noches_max)).isoformat(),
        "durationFrom": noches_min,
        "durationTo": noches_max,
        "market": "es-es",
        "adultPaxCount": 1,
    }
    if destino:
        parametros["arrivalAirportIataCode"] = destino

    hallazgos: dict[str, Hallazgo] = {}
    for pagina in range(MAX_PAGINAS):
        if pagina:
            time.sleep(PAUSA)
        datos = _pedir({**parametros, "pageNumber": pagina})
        for tarifa in datos.get("fares", []):
            h = _a_hallazgo(tarifa, origen)
            if h.destino not in hallazgos or h.precio < hallazgos[h.destino].precio:
                hallazgos[h.destino] = h
        if datos.get("nextPage") is None or not datos.get("fares"):
            break
    return sorted(hallazgos.values(), key=lambda h: h.precio)


def _pedir(parametros: dict) -> dict:
    url = f"{URL}?{urllib.parse.urlencode(parametros)}"
    peticion = urllib.request.Request(url, headers=CABECERAS)
    try:
        with urllib.request.urlopen(peticion, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:120]
        raise RuntimeError(f"Ryanair respondió HTTP {e.code}: {detalle}") from e


def _a_hallazgo(tarifa: dict, origen: str) -> Hallazgo:
    ida, vuelta = tarifa["outbound"], tarifa["inbound"]
    return Hallazgo(
        origen=origen,
        destino=ida["arrivalAirport"]["iataCode"],
        ida=ida["departureDate"][:10],
        vuelta=vuelta["departureDate"][:10],
        precio=float(tarifa["summary"]["price"]["value"]),
        aerolinea="Ryanair",
        fuente="ryanair",
    )
