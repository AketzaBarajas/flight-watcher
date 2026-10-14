from vigilante.modelos import Oferta
from vigilante.reglas import evaluar


def oferta(precio: float) -> Oferta:
    return Oferta(
        precio=precio,
        aerolineas=("Ryanair",),
        vuelos=("FR690",),
        salida="2026-12-17 17:40",
        llegada="2026-12-17 20:40",
        escalas=0,
        duracion_min=180,
    )


def test_sin_ofertas_no_avisa():
    ev = evaluar([], precio_max=50, bajada_pct=15, minimos_previos=[], ultimo_avisado=None)
    assert ev.mejor is None and not ev.avisar


def test_elige_la_mas_barata():
    ev = evaluar([oferta(80), oferta(55)], None, 15, [], None)
    assert ev.mejor.precio == 55


def test_por_encima_del_umbral_no_avisa():
    ev = evaluar([oferta(55)], precio_max=50, bajada_pct=15, minimos_previos=[], ultimo_avisado=None)
    assert not ev.motivos and not ev.avisar


def test_umbral_incluye_el_precio_exacto():
    ev = evaluar([oferta(50)], precio_max=50, bajada_pct=15, minimos_previos=[], ultimo_avisado=None)
    assert ev.avisar and "máximo" in ev.motivos[0]


def test_bajada_frente_a_la_media():
    # media 100 -> con 15 % avisa a 85 o menos
    assert evaluar([oferta(85)], None, 15, [100, 100, 100], None).avisar
    assert not evaluar([oferta(86)], None, 15, [100, 100, 100], None).avisar


def test_con_pocos_dias_no_hay_media():
    ev = evaluar([oferta(10)], None, 15, [100, 100], None)
    assert ev.media is None and not ev.avisar


def test_no_repite_el_mismo_aviso():
    ev = evaluar([oferta(45)], precio_max=50, bajada_pct=15, minimos_previos=[], ultimo_avisado=45)
    assert ev.motivos and not ev.avisar


def test_vuelve_a_avisar_si_mejora():
    ev = evaluar([oferta(40)], precio_max=50, bajada_pct=15, minimos_previos=[], ultimo_avisado=45)
    assert ev.avisar
