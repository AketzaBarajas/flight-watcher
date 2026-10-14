"""Histórico de precios en CSV y estado de avisos en JSON.

El CSV guarda TODAS las ofertas de cada consulta (no solo la más barata): así,
si cambias los filtros en config.yaml, el histórico sigue sirviendo.
"""

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import RAIZ, Filtros
from .modelos import Oferta, Resultado

CSV_PRECIOS = RAIZ / "data" / "precios.csv"
JSON_ESTADO = RAIZ / "data" / "estado.json"

COLUMNAS = [
    "consultado_en",
    "trayecto",
    "origen",
    "destino",
    "fecha_vuelo",
    "precio",
    "moneda",
    "aerolinea",
    "vuelos",
    "salida",
    "llegada",
    "escalas",
    "duracion_min",
    "fuente",
]


def cumple(oferta: Oferta, filtros: Filtros) -> bool:
    if filtros.max_escalas is not None and oferta.escalas > filtros.max_escalas:
        return False
    if (
        filtros.duracion_max_horas is not None
        and oferta.duracion_min > filtros.duracion_max_horas * 60
    ):
        return False
    return True


def guardar(
    resultado: Resultado, fuente: str, ahora: datetime, ruta: Path | None = None
) -> None:
    ruta = ruta or CSV_PRECIOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    c = resultado.consulta
    with ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        for o in resultado.ofertas:
            w.writerow(
                {
                    "consultado_en": ahora.isoformat(timespec="seconds"),
                    "trayecto": c.trayecto,
                    "origen": c.origen,
                    "destino": c.destino,
                    "fecha_vuelo": c.fecha,
                    "precio": f"{o.precio:g}",
                    "moneda": c.moneda,
                    "aerolinea": o.aerolinea,
                    "vuelos": " ".join(o.vuelos),
                    "salida": o.salida,
                    "llegada": o.llegada,
                    "escalas": o.escalas,
                    "duracion_min": o.duracion_min,
                    "fuente": fuente,
                }
            )


def minimos_diarios(
    origen: str,
    destino: str,
    fecha_vuelo: str,
    filtros: Filtros,
    hoy: date,
    dias: int,
    ruta: Path | None = None,
) -> dict[date, float]:
    """Precio mínimo (con filtros) de cada uno de los `dias` anteriores a hoy."""
    ruta = ruta or CSV_PRECIOS
    if not ruta.exists():
        return {}
    desde = hoy - timedelta(days=dias)
    minimos: dict[date, float] = {}
    with ruta.open(newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if (fila["origen"], fila["destino"], fila["fecha_vuelo"]) != (
                origen,
                destino,
                fecha_vuelo,
            ):
                continue
            dia = datetime.fromisoformat(fila["consultado_en"]).date()
            if not (desde <= dia < hoy):
                continue
            oferta = Oferta(
                precio=float(fila["precio"]),
                aerolineas=(fila["aerolinea"],),
                vuelos=(),
                salida=fila["salida"],
                llegada=fila["llegada"],
                escalas=int(fila["escalas"]),
                duracion_min=int(fila["duracion_min"]),
            )
            if cumple(oferta, filtros):
                minimos[dia] = min(oferta.precio, minimos.get(dia, oferta.precio))
    return minimos


def leer_estado(ruta: Path | None = None) -> dict:
    ruta = ruta or JSON_ESTADO
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def guardar_estado(estado: dict, ruta: Path | None = None) -> None:
    ruta = ruta or JSON_ESTADO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(estado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
