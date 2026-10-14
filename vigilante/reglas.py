"""Reglas de alerta. Funciones puras: no leen ficheros ni llaman a la red."""

from dataclasses import dataclass
from statistics import mean

from .modelos import Oferta

# Con menos días de histórico propio la media no significa nada.
MIN_DIAS_PARA_MEDIA = 3


@dataclass(frozen=True)
class Evaluacion:
    mejor: Oferta | None
    motivos: tuple[str, ...]  # por qué es buen precio (vacío = no lo es)
    avisar: bool  # buen precio Y novedad respecto al último aviso
    media: float | None  # media de los días anteriores, si hay datos suficientes


def evaluar(
    ofertas: list[Oferta],
    precio_max: float | None,
    bajada_pct: float,
    minimos_previos: list[float],
    ultimo_avisado: float | None,
) -> Evaluacion:
    """Decide si el mejor precio de hoy merece un aviso.

    - Umbral: precio <= precio_max.
    - Bajada: precio al menos `bajada_pct` % por debajo de la media de los
      mínimos de los días anteriores.
    - Anti-ruido: si ya se avisó de este tramo, solo se repite si el precio
      mejora al del último aviso.
    """
    if not ofertas:
        return Evaluacion(mejor=None, motivos=(), avisar=False, media=None)

    mejor = min(ofertas, key=lambda o: o.precio)
    media = (
        mean(minimos_previos) if len(minimos_previos) >= MIN_DIAS_PARA_MEDIA else None
    )

    motivos = []
    if precio_max is not None and mejor.precio <= precio_max:
        motivos.append(f"por debajo de tu máximo ({precio_max:g})")
    if media is not None and mejor.precio <= media * (1 - bajada_pct / 100):
        bajada = (1 - mejor.precio / media) * 100
        motivos.append(f"{bajada:.0f} % más barato que la media reciente ({media:.0f})")

    novedad = ultimo_avisado is None or mejor.precio < ultimo_avisado
    return Evaluacion(
        mejor=mejor,
        motivos=tuple(motivos),
        avisar=bool(motivos) and novedad,
        media=media,
    )
