"""Icono en la bandeja del sistema (los "iconos ocultos" de la barra de tareas).

Arranca el servidor del panel y deja un icono desde el que abrirlo. Se lanza con
pythonw para que no aparezca ninguna consola:

    .venv\\Scripts\\pythonw.exe -m vigilante.bandeja
"""

import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from .panel import servidor

RUTAS_EDGE = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def abrir_panel(*_) -> None:
    """Abre el panel como ventana propia (Edge en modo aplicación) o, si no hay Edge, en el navegador."""
    edge = next((r for r in RUTAS_EDGE if r.exists()), None) or shutil.which("msedge")
    if edge:
        subprocess.Popen([str(edge), f"--app={servidor.URL}", "--window-size=1200,900"])
    else:
        webbrowser.open(servidor.URL)


def dibujar_icono(lado: int = 64) -> Image.Image:
    """Cuadrado amarillo con un avión de papel azul marino, como el icono del panel."""
    imagen = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(imagen)
    lapiz.rounded_rectangle((0, 0, lado - 1, lado - 1), radius=lado // 5, fill="#FFD21F")
    u = lado / 32
    lapiz.polygon([(6 * u, 18 * u), (26 * u, 9 * u), (19 * u, 25 * u), (16 * u, 19 * u)], fill="#10233A")
    return imagen


def main() -> None:
    try:
        http = servidor.crear_servidor()
    except OSError:
        # El puerto está ocupado: ya hay un vigilante en la bandeja. Basta con abrir su panel.
        abrir_panel()
        return
    threading.Thread(target=http.serve_forever, daemon=True).start()

    def salir(icono: pystray.Icon, _) -> None:
        http.shutdown()
        icono.stop()

    icono = pystray.Icon(
        "vigilante-vuelos",
        dibujar_icono(),
        "Vigilante de vuelos",
        menu=pystray.Menu(
            pystray.MenuItem("Abrir panel", abrir_panel, default=True),  # también con clic izquierdo
            pystray.MenuItem("Buscar vuelos ahora", lambda *_: servidor.buscar_ahora()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", salir),
        ),
    )
    icono.run()


if __name__ == "__main__":
    main()
