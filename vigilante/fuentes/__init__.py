"""Fuentes de precios.

Cada fuente es una función `consultar(Consulta) -> Resultado`. Es la pieza que
más se rompe, así que vive aislada: para cambiarla, añade un módulo aquí,
regístralo en FUENTES y pon su nombre en `fuente:` de config.yaml.
"""

from collections.abc import Callable

from ..modelos import Consulta, Resultado
from . import google_flights


class ErrorFuente(Exception):
    """La fuente no ha podido dar precios (bloqueo, cambio de formato, red...)."""


FUENTES: dict[str, Callable[[Consulta], Resultado]] = {
    "google_flights": google_flights.consultar,
}


def consultar(nombre: str, consulta: Consulta) -> Resultado:
    try:
        fuente = FUENTES[nombre]
    except KeyError:
        raise ErrorFuente(
            f"Fuente desconocida '{nombre}'. Disponibles: {', '.join(FUENTES)}"
        ) from None
    try:
        return fuente(consulta)
    except ErrorFuente:
        raise
    except Exception as e:  # cualquier fallo de la fuente es un "no pude consultar"
        raise ErrorFuente(f"{type(e).__name__}: {e}") from e
