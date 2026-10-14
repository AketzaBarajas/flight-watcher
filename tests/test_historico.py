from datetime import date, datetime

from vigilante.config import Filtros
from vigilante.historico import cumple, guardar, minimos_diarios
from vigilante.modelos import Consulta, Oferta, Resultado

CONSULTA = Consulta(trayecto="Praga → Madrid", origen="PRG", destino="MAD", fecha="2026-12-22")


def oferta(precio: float, escalas: int = 0, duracion_min: int = 185) -> Oferta:
    return Oferta(
        precio=precio,
        aerolineas=("Ryanair",),
        vuelos=("FR1",),
        salida="2026-12-22 06:10",
        llegada="2026-12-22 09:15",
        escalas=escalas,
        duracion_min=duracion_min,
    )


def test_filtros():
    assert cumple(oferta(100, escalas=2), Filtros())
    assert not cumple(oferta(100, escalas=1), Filtros(max_escalas=0))
    assert not cumple(oferta(100, duracion_min=301), Filtros(duracion_max_horas=5))
    assert cumple(oferta(100, duracion_min=300), Filtros(duracion_max_horas=5))


def test_minimos_diarios_aplica_filtros_y_ventana(tmp_path):
    csv = tmp_path / "precios.csv"
    hoy = date(2026, 10, 20)
    dias = {
        datetime(2026, 10, 12, 8): [oferta(10)],  # fuera de la ventana de 7 días
        datetime(2026, 10, 17, 8): [oferta(120), oferta(60, escalas=1)],
        datetime(2026, 10, 18, 8): [oferta(110), oferta(105)],
        datetime(2026, 10, 20, 8): [oferta(5)],  # hoy no cuenta como "previo"
    }
    for cuando, ofertas in dias.items():
        guardar(Resultado(consulta=CONSULTA, ofertas=ofertas), "prueba", cuando, ruta=csv)

    directos = minimos_diarios("PRG", "MAD", "2026-12-22", Filtros(max_escalas=0), hoy, 7, ruta=csv)
    assert directos == {date(2026, 10, 17): 120, date(2026, 10, 18): 105}

    todos = minimos_diarios("PRG", "MAD", "2026-12-22", Filtros(), hoy, 7, ruta=csv)
    assert todos[date(2026, 10, 17)] == 60

    assert minimos_diarios("PRG", "MAD", "2026-12-23", Filtros(), hoy, 7, ruta=csv) == {}
