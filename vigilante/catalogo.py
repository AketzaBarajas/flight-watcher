"""Catálogo de países y ciudades con aeropuerto (lo genera scripts/construir_catalogo.py)."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "panel" / "datos" / "catalogo.json"


@dataclass(frozen=True)
class Lugar:
    iata: str
    ciudad: str
    pais: str  # ISO de dos letras
    pais_nombre: str
    ryanair: bool


class Catalogo:
    def __init__(self, datos: dict):
        self.datos = datos
        self.paises = {p["iso"]: p for p in datos["paises"]}
        self._lugares = {
            c["iata"]: Lugar(c["iata"], c["ciudad"], p["iso"], p["nombre"], bool(c.get("ry")))
            for p in datos["paises"]
            for c in p["ciudades"]
        }

    def lugar(self, iata: str) -> Lugar | None:
        return self._lugares.get(iata)

    def existe_pais(self, iso: str) -> bool:
        return iso in self.paises

    def ciudades_de(self, iso: str) -> set[str]:
        return {c["iata"] for c in self.paises[iso]["ciudades"]}


@lru_cache(maxsize=1)
def cargar() -> Catalogo:
    return Catalogo(json.loads(RUTA.read_text(encoding="utf-8")))
