"""Carga y valida config.yaml y las variables de .env."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


class ErrorConfig(Exception):
    pass


@dataclass(frozen=True)
class Filtros:
    max_escalas: int | None = None
    duracion_max_horas: float | None = None


@dataclass(frozen=True)
class Trayecto:
    nombre: str
    origen: str
    destino: str
    fechas: tuple[str, ...]
    precio_max: float | None
    filtros: Filtros


@dataclass(frozen=True)
class Config:
    fuente: str
    moneda: str
    adultos: int
    bajada_pct: float
    dias_media: int
    canales: tuple[str, ...]
    resumen_semanal: str | None
    trayectos: tuple[Trayecto, ...]


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Lee CLAVE=valor de .env sin pisar variables ya definidas en el entorno."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip("\"'"))


def cargar_config(ruta: Path = RAIZ / "config.yaml") -> Config:
    try:
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ErrorConfig(f"No existe {ruta}") from None
    except yaml.YAMLError as e:
        raise ErrorConfig(f"config.yaml mal escrito: {e}") from e

    filtros_globales = crudo.get("filtros") or {}
    alerta = crudo.get("alerta") or {}
    avisos = crudo.get("avisos") or {}

    trayectos = []
    for i, t in enumerate(crudo.get("trayectos") or [], start=1):
        faltan = [c for c in ("nombre", "origen", "destino", "fechas") if not t.get(c)]
        if faltan:
            raise ErrorConfig(f"Trayecto nº {i}: faltan {', '.join(faltan)}")
        fechas = []
        for f in t["fechas"]:
            try:
                fechas.append(date.fromisoformat(str(f)).isoformat())
            except ValueError:
                raise ErrorConfig(
                    f"Trayecto '{t['nombre']}': fecha '{f}' no es AAAA-MM-DD"
                ) from None
        filtros = {**filtros_globales, **(t.get("filtros") or {})}
        trayectos.append(
            Trayecto(
                nombre=str(t["nombre"]),
                origen=str(t["origen"]).upper(),
                destino=str(t["destino"]).upper(),
                fechas=tuple(fechas),
                precio_max=_numero(t.get("precio_max")),
                filtros=Filtros(
                    max_escalas=filtros.get("max_escalas"),
                    duracion_max_horas=_numero(filtros.get("duracion_max_horas")),
                ),
            )
        )
    if not trayectos:
        raise ErrorConfig("config.yaml no tiene ningún trayecto")

    resumen = avisos.get("resumen_semanal")
    if resumen is not None and resumen not in DIAS_SEMANA:
        raise ErrorConfig(
            f"resumen_semanal: '{resumen}' no vale. Usa uno de {DIAS_SEMANA} o null"
        )

    return Config(
        fuente=crudo.get("fuente", "google_flights"),
        moneda=crudo.get("moneda", "EUR"),
        adultos=int(crudo.get("adultos", 1)),
        bajada_pct=float(alerta.get("bajada_pct", 15)),
        dias_media=int(alerta.get("dias_media", 7)),
        canales=tuple(avisos.get("canales") or ["consola"]),
        resumen_semanal=resumen,
        trayectos=tuple(trayectos),
    )


def _numero(valor) -> float | None:
    return None if valor is None else float(valor)
