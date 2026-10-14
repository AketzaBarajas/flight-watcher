"""El servidor del panel, arrancado de verdad en un puerto libre."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from vigilante import agente, historico
from vigilante import intereses as mod_intereses
from vigilante.panel import servidor


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(mod_intereses, "RUTA", tmp_path / "intereses.json")
    monkeypatch.setattr(agente, "JSON_RECOMENDACIONES", tmp_path / "recomendaciones.json")
    monkeypatch.setattr(historico, "JSON_ESTADO", tmp_path / "estado.json")
    http = ThreadingHTTPServer((servidor.HOST, 0), servidor.Manejador)
    monkeypatch.setattr(servidor, "PUERTO", http.server_address[1])
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield f"http://{servidor.HOST}:{http.server_address[1]}"
    http.shutdown()
    http.server_close()


def pedir(url: str, metodo: str = "GET", cuerpo=None, cabeceras: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras or {})
    try:
        with urllib.request.urlopen(peticion, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_sirve_la_interfaz_y_el_catalogo(panel):
    codigo, cuerpo = pedir(panel + "/")
    assert codigo == 200 and b"Vigilante de vuelos" in cuerpo
    codigo, cuerpo = pedir(panel + "/api/catalogo")
    paises = json.loads(cuerpo)["paises"]
    assert codigo == 200 and any(p["iso"] == "JP" for p in paises)


def test_guardar_y_leer_lo_marcado(panel, tmp_path):
    nuevo = {"paises": {"JP": {"ciudades": ["NRT"], "precio_max": "700"}}}
    codigo, cuerpo = pedir(panel + "/api/intereses", "PUT", nuevo)
    assert codigo == 200
    assert json.loads(cuerpo)["paises"]["JP"] == {
        "ciudades": ["NRT"],
        "ventanas": [],
        "precio_max": 700.0,
        "noches": None,
    }
    assert json.loads(pedir(panel + "/api/intereses")[1])["paises"].keys() == {"JP"}
    assert (tmp_path / "intereses.json").exists()


def test_rechaza_datos_malos_sin_guardar(panel, tmp_path):
    codigo, cuerpo = pedir(panel + "/api/intereses", "PUT", {"paises": {"ZZ": {}}})
    assert codigo == 422 and "ZZ" in json.loads(cuerpo)["error"]
    assert not (tmp_path / "intereses.json").exists()


def test_recomendaciones_y_estado_vacios_al_principio(panel):
    assert json.loads(pedir(panel + "/api/recomendaciones")[1]) == {"periodos": []}
    assert json.loads(pedir(panel + "/api/estado")[1]) == {"buscando": False, "ultima": None}


def test_no_sirve_ficheros_de_fuera_de_la_interfaz(panel):
    assert pedir(panel + "/../servidor.py")[0] == 404
    assert pedir(panel + "/..%2f..%2fconfig.py")[0] == 404


@pytest.mark.parametrize(
    "cabeceras",
    [{"Host": "otra-web.example"}, {"Origin": "https://otra-web.example"}],
)
def test_solo_acepta_peticiones_del_propio_panel(panel, cabeceras):
    assert pedir(panel + "/api/intereses", cabeceras=cabeceras)[0] == 403
    assert pedir(panel + "/api/intereses", "PUT", {"paises": {}}, cabeceras)[0] == 403
    assert pedir(panel + "/api/buscar", "POST", cabeceras=cabeceras)[0] == 403
