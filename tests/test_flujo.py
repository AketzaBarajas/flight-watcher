"""Flujo completo de `python -m vigilante` con fuente y canal falsos."""

import json
from datetime import date, timedelta

import pytest

from vigilante import __main__ as app
from vigilante import avisos, fuentes, historico
from vigilante.config import DIAS_SEMANA, Config, Filtros, Trayecto
from vigilante.modelos import Oferta, Resultado

FECHA = (date.today() + timedelta(days=60)).isoformat()


def oferta(precio: float, escalas: int = 0) -> Oferta:
    return Oferta(
        precio=precio,
        aerolineas=("Ryanair",),
        vuelos=("FR690",),
        salida=f"{FECHA} 17:40",
        llegada=f"{FECHA} 20:40",
        escalas=escalas,
        duracion_min=180,
    )


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Prepara rutas temporales, una fuente falsa y un canal que solo apunta."""
    e = {"ofertas": [oferta(55)], "enviados": [], "resumen": None, "fechas": (FECHA,)}

    def config_falsa() -> Config:
        return Config(
            fuente="falsa",
            moneda="EUR",
            adultos=1,
            bajada_pct=15,
            dias_media=7,
            canales=("espia",),
            resumen_semanal=e["resumen"],
            trayectos=(
                Trayecto("Madrid → Viena", "MAD", "VIE", e["fechas"], 50, Filtros(max_escalas=0)),
            ),
        )

    def fuente_falsa(consulta):
        if e["ofertas"] is None:
            raise RuntimeError("Google ha cambiado la página")
        return Resultado(consulta=consulta, ofertas=e["ofertas"], enlace="https://ejemplo.test")

    monkeypatch.setattr(app, "cargar_config", config_falsa)
    monkeypatch.setattr(app, "cargar_env", lambda: None)
    monkeypatch.setattr(app, "PAUSA_ENTRE_CONSULTAS", 0)
    monkeypatch.setattr(historico, "CSV_PRECIOS", tmp_path / "precios.csv")
    monkeypatch.setattr(historico, "JSON_ESTADO", tmp_path / "estado.json")
    monkeypatch.setitem(fuentes.FUENTES, "falsa", fuente_falsa)
    monkeypatch.setitem(
        avisos.CANALES, "espia", lambda t, c, enlace, urgente: e["enviados"].append((t, c))
    )
    e["tmp"] = tmp_path
    return e


def ejecutar(monkeypatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["vigilante", "--sin-agente", *args])
    return app.main()


def test_precio_normal_guarda_pero_no_avisa(entorno, monkeypatch):
    assert ejecutar(monkeypatch) == 0
    assert entorno["enviados"] == []
    assert "55" in (entorno["tmp"] / "precios.csv").read_text(encoding="utf-8")


def test_chollo_avisa_una_sola_vez_y_repite_si_mejora(entorno, monkeypatch):
    entorno["ofertas"] = [oferta(45)]
    ejecutar(monkeypatch)
    ejecutar(monkeypatch)
    assert len(entorno["enviados"]) == 1
    titulo, cuerpo = entorno["enviados"][0]
    assert "Madrid → Viena" in titulo and "45 €" in titulo
    assert "máximo" in cuerpo

    entorno["ofertas"] = [oferta(40)]
    ejecutar(monkeypatch)
    assert len(entorno["enviados"]) == 2


def test_vuelve_a_avisar_tras_subir_y_bajar(entorno, monkeypatch):
    for precio in (45, 70, 45):
        entorno["ofertas"] = [oferta(precio)]
        ejecutar(monkeypatch)
    assert len(entorno["enviados"]) == 2


def test_los_filtros_descartan_el_barato_con_escala(entorno, monkeypatch):
    entorno["ofertas"] = [oferta(20, escalas=1), oferta(55)]
    ejecutar(monkeypatch)
    assert entorno["enviados"] == []


def test_fallo_de_la_fuente_avisa_y_devuelve_error(entorno, monkeypatch):
    entorno["ofertas"] = None
    assert ejecutar(monkeypatch) == 1
    titulo, cuerpo = entorno["enviados"][0]
    assert "no pude consultar" in titulo
    assert "Google ha cambiado la página" in cuerpo


def test_dry_run_no_guarda_ni_avisa(entorno, monkeypatch):
    entorno["ofertas"] = [oferta(45)]
    assert ejecutar(monkeypatch, "--dry-run") == 0
    assert entorno["enviados"] == []
    assert not (entorno["tmp"] / "precios.csv").exists()
    assert not (entorno["tmp"] / "estado.json").exists()


def test_resumen_semanal_una_vez_al_dia(entorno, monkeypatch):
    entorno["resumen"] = DIAS_SEMANA[date.today().weekday()]
    ejecutar(monkeypatch)
    ejecutar(monkeypatch)
    assert len(entorno["enviados"]) == 1
    assert "resumen" in entorno["enviados"][0][0]
    estado = json.loads((entorno["tmp"] / "estado.json").read_text(encoding="utf-8"))
    assert estado["ultimo_resumen"] == date.today().isoformat()


def test_fechas_pasadas_no_se_consultan(entorno, monkeypatch):
    entorno["fechas"] = ("2020-01-01",)
    entorno["ofertas"] = None  # si consultara, fallaría
    assert ejecutar(monkeypatch) == 0
    assert entorno["enviados"] == []


def test_una_vez_al_dia_no_repite(entorno, monkeypatch):
    entorno["ofertas"] = [oferta(45)]
    ejecutar(monkeypatch, "--una-vez-al-dia")
    entorno["ofertas"] = [oferta(40)]  # aunque mejore, hoy ya se ejecutó
    assert ejecutar(monkeypatch, "--una-vez-al-dia") == 0
    assert len(entorno["enviados"]) == 1
    assert len((entorno["tmp"] / "precios.csv").read_text(encoding="utf-8").splitlines()) == 2


def test_una_vez_al_dia_reintenta_si_todo_fallo(entorno, monkeypatch):
    entorno["ofertas"] = None
    ejecutar(monkeypatch, "--una-vez-al-dia")
    entorno["ofertas"] = [oferta(45)]
    ejecutar(monkeypatch, "--una-vez-al-dia")
    assert any("Madrid → Viena" in t for t, _ in entorno["enviados"])
