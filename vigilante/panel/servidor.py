"""Servidor local del panel. Solo escucha en 127.0.0.1: no es accesible desde la red.

    GET  /                     la interfaz
    GET  /api/catalogo         países y ciudades
    GET  /api/intereses        lo marcado
    PUT  /api/intereses        guardar lo marcado
    GET  /api/recomendaciones  última lectura del agente
    GET  /api/estado           si está buscando y cómo fue la última búsqueda
    POST /api/buscar           lanzar el agente ahora
"""

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import agente, historico
from .. import catalogo as mod_catalogo
from .. import intereses as mod_intereses
from ..config import cargar_config, cargar_env

HOST = "127.0.0.1"
PUERTO = 8765
URL = f"http://{HOST}:{PUERTO}/"
ESTATICOS = Path(__file__).resolve().parent / "static"
MAX_CUERPO = 1_000_000

_buscando = threading.Lock()


def buscar_ahora() -> bool:
    """Lanza el agente en segundo plano. Devuelve False si ya había una búsqueda en marcha."""
    if not _buscando.acquire(blocking=False):
        return False

    def trabajo() -> None:
        try:
            cargar_env()
            agente.correr(cargar_config().canales)
        except Exception as e:  # que quede a la vista en el panel, no en una consola oculta
            estado = historico.leer_estado()
            estado.setdefault("agente", {})["ultima"] = {
                "cuando": "",
                "hallazgos": 0,
                "consultas": 0,
                "errores": [f"{type(e).__name__}: {e}"],
            }
            historico.guardar_estado(estado)
        finally:
            _buscando.release()

    threading.Thread(target=trabajo, daemon=True).start()
    return True


class Manejador(BaseHTTPRequestHandler):
    server_version = "VigilanteVuelos"

    def log_message(self, *args) -> None:  # sin ruido en la consola
        pass

    # --- seguridad: solo peticiones hechas desde el propio panel ---

    def _es_local(self) -> bool:
        """Rechaza otras webs que intenten hablar con este servidor desde el navegador."""
        validos = {f"{HOST}:{PUERTO}", f"localhost:{PUERTO}"}
        if self.headers.get("Host") not in validos:
            return False
        origen = self.headers.get("Origin")
        return origen is None or origen in {f"http://{v}" for v in validos}

    # --- respuestas ---

    def _json(self, datos, codigo: int = HTTPStatus.OK) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self._enviar(codigo, "application/json; charset=utf-8", cuerpo)

    def _enviar(self, codigo: int, tipo: str, cuerpo: bytes) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, codigo: int, mensaje: str) -> None:
        self._json({"error": mensaje}, codigo)

    # --- rutas ---

    def do_GET(self) -> None:
        if not self._es_local():
            return self._error(HTTPStatus.FORBIDDEN, "Solo accesible desde este ordenador")
        ruta = self.path.split("?", 1)[0]
        if ruta == "/api/catalogo":
            return self._enviar(
                HTTPStatus.OK, "application/json; charset=utf-8", mod_catalogo.RUTA.read_bytes()
            )
        if ruta == "/api/intereses":
            return self._json(mod_intereses.leer(mod_catalogo.cargar()))
        if ruta == "/api/recomendaciones":
            if agente.JSON_RECOMENDACIONES.exists():
                return self._enviar(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    agente.JSON_RECOMENDACIONES.read_bytes(),
                )
            return self._json({"periodos": []})
        if ruta == "/api/estado":
            ultima = historico.leer_estado().get("agente", {}).get("ultima")
            return self._json({"buscando": _buscando.locked(), "ultima": ultima})
        self._estatico(ruta)

    def do_PUT(self) -> None:
        if not self._es_local():
            return self._error(HTTPStatus.FORBIDDEN, "Solo accesible desde este ordenador")
        if self.path != "/api/intereses":
            return self._error(HTTPStatus.NOT_FOUND, "No existe")
        try:
            largo = int(self.headers.get("Content-Length", 0))
            if not 0 < largo <= MAX_CUERPO:
                raise ValueError
            crudo = json.loads(self.rfile.read(largo).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._error(HTTPStatus.BAD_REQUEST, "No he entendido los datos enviados")
        try:
            datos = mod_intereses.validar(crudo, mod_catalogo.cargar())
        except mod_intereses.ErrorIntereses as e:
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(e))
        mod_intereses.guardar(datos)
        self._json(datos)

    def do_POST(self) -> None:
        if not self._es_local():
            return self._error(HTTPStatus.FORBIDDEN, "Solo accesible desde este ordenador")
        if self.path != "/api/buscar":
            return self._error(HTTPStatus.NOT_FOUND, "No existe")
        if buscar_ahora():
            return self._json({"buscando": True}, HTTPStatus.ACCEPTED)
        self._error(HTTPStatus.CONFLICT, "Ya hay una búsqueda en marcha")

    def _estatico(self, ruta: str) -> None:
        relativo = "index.html" if ruta in ("", "/") else ruta.lstrip("/")
        fichero = (ESTATICOS / relativo).resolve()
        if not fichero.is_relative_to(ESTATICOS) or not fichero.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "No existe")
        tipo = mimetypes.guess_type(fichero.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        self._enviar(HTTPStatus.OK, tipo, fichero.read_bytes())


def crear_servidor() -> ThreadingHTTPServer:
    """Lanza OSError si el puerto ya está ocupado (otra copia del panel abierta)."""
    return ThreadingHTTPServer((HOST, PUERTO), Manejador)


if __name__ == "__main__":
    print(f"Panel en {URL}  (Ctrl+C para cerrar)")
    crear_servidor().serve_forever()
