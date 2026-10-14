"""Tipos de datos compartidos por todas las piezas."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Consulta:
    """Lo que se le pide a una fuente: un tramo solo ida en una fecha."""

    trayecto: str
    origen: str
    destino: str
    fecha: str  # AAAA-MM-DD
    adultos: int = 1
    moneda: str = "EUR"


@dataclass(frozen=True)
class Oferta:
    """Un vuelo concreto con su precio, tal y como lo devuelve la fuente."""

    precio: float
    aerolineas: tuple[str, ...]
    vuelos: tuple[str, ...]  # p. ej. ("FR690",)
    salida: str  # AAAA-MM-DD HH:MM (hora local del aeropuerto)
    llegada: str
    escalas: int
    duracion_min: int

    @property
    def aerolinea(self) -> str:
        return " + ".join(self.aerolineas)

    @property
    def directo(self) -> bool:
        return self.escalas == 0


@dataclass(frozen=True)
class Contexto:
    """Datos extra de la fuente sobre el precio (opcionales, solo informativos).

    Se refieren al vuelo más barato SIN filtros (con escalas incluidas), así que
    sirven de referencia en el aviso pero no para decidir si se avisa.
    """

    precio_habitual: float | None = None
    rango_tipico: tuple[float, float] | None = None
    minimo_60d: float | None = None


@dataclass
class Resultado:
    """Respuesta de una fuente a una consulta."""

    consulta: Consulta
    ofertas: list[Oferta] = field(default_factory=list)
    enlace: str = ""
    contexto: Contexto = field(default_factory=Contexto)


@dataclass(frozen=True)
class Hallazgo:
    """Un viaje de ida y vuelta que ha encontrado el agente."""

    origen: str
    destino: str  # código IATA
    ida: str  # AAAA-MM-DD
    vuelta: str
    precio: float
    aerolinea: str
    fuente: str
    rango_tipico: tuple[float, float] | None = None  # solo si la fuente lo da

    @property
    def mes(self) -> str:
        return self.ida[:7]
