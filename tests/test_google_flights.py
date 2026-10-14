"""Parseo contra una respuesta real de Google Flights (PRG→MAD, 22-dic-2026,
capturada el 2026-10-13 y recortada a las secciones que usa el parser)."""

import json
from pathlib import Path

import pytest

from vigilante.fuentes.google_flights import (
    extraer_payload,
    parsear_contexto,
    parsear_ofertas,
)

FIXTURE = Path(__file__).parent / "fixtures" / "payload_prg_mad_2026-12-22.json"


@pytest.fixture(scope="module")
def payload() -> list:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_lee_mejores_y_otros_vuelos(payload):
    ofertas = parsear_ofertas(payload)
    assert len(ofertas) == 9  # 4 "mejores" + 5 "otros"
    assert [o.precio for o in ofertas] == sorted(o.precio for o in ofertas)


def test_la_mas_barata_es_el_directo_de_ryanair(payload):
    mejor = parsear_ofertas(payload)[0]
    assert mejor.precio == 102
    assert mejor.aerolineas == ("Ryanair",)
    assert mejor.directo
    assert mejor.salida == "2026-12-22 06:10"
    assert mejor.llegada == "2026-12-22 09:15"
    assert mejor.duracion_min == 185
    assert mejor.vuelos[0].startswith("FR")


def test_cuenta_las_escalas(payload):
    lot = next(o for o in parsear_ofertas(payload) if o.aerolineas == ("LOT",))
    assert lot.escalas == 1 and len(lot.vuelos) == 2


def test_contexto_de_precios(payload):
    ctx = parsear_contexto(payload)
    assert ctx.precio_habitual == 120
    assert ctx.rango_tipico == (85, 185)
    assert ctx.minimo_60d is not None and ctx.minimo_60d <= 102


def test_contexto_vacio_si_cambia_la_estructura():
    ctx = parsear_contexto([None] * 10)
    assert ctx.rango_tipico is None and ctx.minimo_60d is None


def test_pagina_sin_datos_da_error_claro():
    with pytest.raises(RuntimeError, match="ds:1"):
        extraer_payload("<html><body>Antes de continuar</body></html>")
