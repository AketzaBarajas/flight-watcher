"""Lo que le interesa a Ake: destinos marcados, fechas y ajustes del agente.

Vive en data/intereses.json y lo edita el panel. Todo lo que entra (del panel o
del fichero) pasa por `validar`, que devuelve la versión normalizada.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .catalogo import Catalogo
from .config import RAIZ

RUTA = RAIZ / "data" / "intereses.json"

POR_DEFECTO = {
    "origen": "MAD",
    "ajustes": {
        "meses": 4,  # meses que mira hacia delante
        "noches_min": 2,
        "noches_max": 5,
        # Ida y vuelta por debajo de esto = chollo aunque no esté marcado. Va por
        # debajo del suelo de Ryanair (2 x 14,99 €): con 35 € avisaría casi a diario
        # de precios que son normales. Lo no marcado avisa sobre todo por bajada.
        "chollo_max": 25,
        # Tope diario de consultas a Google para las ciudades y meses marcados que
        # Ryanair no cubre. Con 25, unas 45 ciudades x 7 meses se renuevan cada dos semanas.
        "consultas_google": 25,
    },
    "paises": {},
}
LIMITES = {
    "meses": (1, 10),
    "noches_min": (1, 30),
    "noches_max": (1, 30),
    "chollo_max": (1, 5000),
    "consultas_google": (0, 40),
}


class ErrorIntereses(ValueError):
    pass


@dataclass(frozen=True)
class Ventana:
    desde: date
    hasta: date

    def contiene(self, dia: date) -> bool:
        return self.desde <= dia <= self.hasta


@dataclass(frozen=True)
class Interes:
    pais: str
    ciudades: frozenset[str]  # vacío = cualquier ciudad del país
    ventanas: tuple[Ventana, ...]  # vacío = cualquier fecha
    precio_max: float | None
    noches: tuple[int, int] | None  # None = las noches generales


@dataclass(frozen=True)
class Intereses:
    origen: str
    meses: int
    noches_min: int
    noches_max: int
    chollo_max: float
    consultas_google: int
    paises: dict[str, Interes] = field(default_factory=dict)

    def noches_de(self, interes: Interes) -> tuple[int, int]:
        return interes.noches or (self.noches_min, self.noches_max)

    def interes_de(self, pais: str, ciudad: str, ida: date, noches: int) -> Interes | None:
        """El interés que cubre este viaje, o None si no está marcado."""
        interes = self.paises.get(pais)
        if interes is None:
            return None
        if interes.ciudades and ciudad not in interes.ciudades:
            return None
        if interes.ventanas and not any(v.contiene(ida) for v in interes.ventanas):
            return None
        minimo, maximo = self.noches_de(interes)
        if not minimo <= noches <= maximo:
            return None
        return interes


def validar(crudo: dict, catalogo: Catalogo) -> dict:
    """Comprueba y normaliza. Lanza ErrorIntereses con un mensaje para el usuario."""
    if not isinstance(crudo, dict):
        raise ErrorIntereses("El contenido no es un objeto")

    origen = str(crudo.get("origen") or POR_DEFECTO["origen"]).strip().upper()
    if catalogo.lugar(origen) is None:
        raise ErrorIntereses(f"No conozco el aeropuerto de origen '{origen}'")

    ajustes = {**POR_DEFECTO["ajustes"]}
    for clave, valor in (crudo.get("ajustes") or {}).items():
        if clave not in LIMITES:
            continue
        minimo, maximo = LIMITES[clave]
        try:
            numero = float(valor) if clave == "chollo_max" else int(valor)
        except (TypeError, ValueError):
            raise ErrorIntereses(f"'{clave}' tiene que ser un número") from None
        if not minimo <= numero <= maximo:
            raise ErrorIntereses(f"'{clave}' tiene que estar entre {minimo} y {maximo}")
        ajustes[clave] = numero
    if ajustes["noches_min"] > ajustes["noches_max"]:
        raise ErrorIntereses("Las noches mínimas no pueden superar a las máximas")

    paises = {}
    for iso, datos in (crudo.get("paises") or {}).items():
        if not catalogo.existe_pais(iso):
            raise ErrorIntereses(f"País desconocido: '{iso}'")
        datos = datos or {}
        nombre = catalogo.paises[iso]["nombre"]

        ciudades = sorted(set(datos.get("ciudades") or []))
        ajenas = set(ciudades) - catalogo.ciudades_de(iso)
        if ajenas:
            raise ErrorIntereses(f"{nombre}: aeropuertos que no son de ese país: {sorted(ajenas)}")

        ventanas = []
        for v in datos.get("ventanas") or []:
            try:
                desde = date.fromisoformat(str(v["desde"]))
                hasta = date.fromisoformat(str(v["hasta"]))
            except (KeyError, TypeError, ValueError):
                raise ErrorIntereses(f"{nombre}: hay una fecha vacía o mal escrita") from None
            if hasta < desde:
                raise ErrorIntereses(f"{nombre}: la fecha final es anterior a la inicial")
            ventanas.append({"desde": desde.isoformat(), "hasta": hasta.isoformat()})

        precio_max = datos.get("precio_max")
        if precio_max in ("", None):
            precio_max = None
        else:
            try:
                precio_max = float(precio_max)
            except (TypeError, ValueError):
                raise ErrorIntereses(f"{nombre}: el precio máximo no es un número") from None
            if precio_max <= 0:
                raise ErrorIntereses(f"{nombre}: el precio máximo tiene que ser positivo")

        noches = datos.get("noches") or None
        if noches is not None:
            try:
                noches = [int(noches[0]), int(noches[1])]
            except (TypeError, ValueError, IndexError):
                raise ErrorIntereses(f"{nombre}: las noches tienen que ser dos números") from None
            if not 1 <= noches[0] <= noches[1] <= 60:
                raise ErrorIntereses(f"{nombre}: noches fuera de rango (1 a 60, mínimo ≤ máximo)")

        paises[iso] = {
            "ciudades": ciudades,
            "ventanas": ventanas,
            "precio_max": precio_max,
            "noches": noches,
        }

    return {"origen": origen, "ajustes": ajustes, "paises": paises}


def leer(catalogo: Catalogo, ruta: Path | None = None) -> dict:
    ruta = ruta or RUTA
    if not ruta.exists():
        return validar({}, catalogo)
    return validar(json.loads(ruta.read_text(encoding="utf-8")), catalogo)


def guardar(datos: dict, ruta: Path | None = None) -> None:
    ruta = ruta or RUTA
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def construir(datos: dict) -> Intereses:
    """Pasa el diccionario ya validado a objetos cómodos para el agente."""
    a = datos["ajustes"]
    return Intereses(
        origen=datos["origen"],
        meses=a["meses"],
        noches_min=a["noches_min"],
        noches_max=a["noches_max"],
        chollo_max=a["chollo_max"],
        consultas_google=a["consultas_google"],
        paises={
            iso: Interes(
                pais=iso,
                ciudades=frozenset(p["ciudades"]),
                ventanas=tuple(
                    Ventana(date.fromisoformat(v["desde"]), date.fromisoformat(v["hasta"]))
                    for v in p["ventanas"]
                ),
                precio_max=p["precio_max"],
                noches=tuple(p["noches"]) if p.get("noches") else None,
            )
            for iso, p in datos["paises"].items()
        },
    )
