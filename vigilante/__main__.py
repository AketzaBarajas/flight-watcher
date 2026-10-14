"""Vigilante de vuelos: consulta, guarda, evalúa y avisa.

Uso:
    python -m vigilante                 ejecución normal (la que se programa)
    python -m vigilante --dry-run       consulta y muestra, sin guardar ni avisar
    python -m vigilante --resumen       fuerza el resumen aunque no haya chollo
    python -m vigilante --probar-aviso  manda un aviso de prueba y sale
    python -m vigilante --sin-agente    solo los trayectos exactos de config.yaml
    python -m vigilante --una-vez-al-dia  no hace nada si hoy ya hubo una ejecución buena

Hace dos cosas seguidas: vigila los trayectos exactos de config.yaml y después
lanza el agente, que explora destinos según lo marcado en el panel.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime

from . import agente, avisos, fuentes, historico, reglas
from .config import DIAS_SEMANA, Config, ErrorConfig, Trayecto, cargar_config, cargar_env
from .modelos import Consulta, Contexto, Oferta

PAUSA_ENTRE_CONSULTAS = 2  # segundos; no hay prisa y evita parecer un bot agresivo
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS_ABREV = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


@dataclass
class Linea:
    """Lo que se sabe hoy de un tramo en una fecha."""

    trayecto: Trayecto
    fecha: str
    evaluacion: reglas.Evaluacion
    enlace: str
    contexto: Contexto

    @property
    def clave(self) -> str:
        return f"{self.trayecto.origen}-{self.trayecto.destino}|{self.fecha}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _argumentos()
    cargar_env()
    try:
        config = cargar_config()
    except ErrorConfig as e:
        print(f"Error de configuración: {e}")
        return 2

    if args.probar_aviso:
        errores = avisos.enviar(
            config.canales,
            "Vigilante de vuelos: prueba",
            "Si lees esto, los avisos funcionan.",
        )
        print("Aviso de prueba enviado." if not errores else f"Fallo: {errores}")
        return 1 if errores else 0

    ahora = datetime.now()
    hoy = ahora.date()
    estado = historico.leer_estado()
    if args.una_vez_al_dia and estado.get("ultima_ejecucion") == hoy.isoformat():
        print(f"Vigilante de vuelos · {ahora:%Y-%m-%d %H:%M} · hoy ya se ejecutó; nada que hacer.")
        return 0
    ultimos_avisos: dict = estado.setdefault("avisados", {})

    lineas: list[Linea] = []
    fallos: list[str] = []
    pendientes = [
        (t, f) for t in config.trayectos for f in t.fechas if date.fromisoformat(f) >= hoy
    ]
    for i, (trayecto, fecha) in enumerate(pendientes):
        if i:
            time.sleep(PAUSA_ENTRE_CONSULTAS)
        consulta = Consulta(
            trayecto=trayecto.nombre,
            origen=trayecto.origen,
            destino=trayecto.destino,
            fecha=fecha,
            adultos=config.adultos,
            moneda=config.moneda,
        )
        try:
            resultado = fuentes.consultar(config.fuente, consulta)
        except fuentes.ErrorFuente as e:
            fallos.append(f"{trayecto.nombre} {_fecha_corta(fecha)}: {e}")
            continue
        if not args.dry_run:
            historico.guardar(resultado, config.fuente, ahora)

        validas = [o for o in resultado.ofertas if historico.cumple(o, trayecto.filtros)]
        previos = historico.minimos_diarios(
            trayecto.origen, trayecto.destino, fecha, trayecto.filtros, hoy, config.dias_media
        )
        linea = Linea(
            trayecto=trayecto,
            fecha=fecha,
            evaluacion=reglas.evaluar(
                validas,
                trayecto.precio_max,
                config.bajada_pct,
                list(previos.values()),
                ultimos_avisos.get(f"{trayecto.origen}-{trayecto.destino}|{fecha}"),
            ),
            enlace=resultado.enlace,
            contexto=resultado.contexto,
        )
        lineas.append(linea)

    print(f"Vigilante de vuelos · {ahora:%Y-%m-%d %H:%M} · fuente: {config.fuente}")
    if not pendientes:
        print("No queda ningún trayecto con fecha futura en config.yaml.")
    for linea in lineas:
        print(_texto_linea(linea, config.moneda, detalle=True))
    for fallo in fallos:
        print(f"FALLO  {fallo}")

    canales = ("consola",) if args.dry_run else config.canales
    errores_envio: list[str] = []

    alertas = [l for l in lineas if l.evaluacion.avisar]
    if alertas:
        mejor = min(alertas, key=lambda l: l.evaluacion.mejor.precio)
        titulo = (
            f"Vuelo barato: {mejor.trayecto.nombre} "
            f"{_precio(mejor.evaluacion.mejor.precio, config.moneda)}"
        )
        cuerpo = "\n\n".join(_texto_linea(l, config.moneda, detalle=True) for l in alertas)
        errores = avisos.enviar(canales, titulo, cuerpo, mejor.enlace, urgente=True)
        errores_envio += errores
        if not errores:
            for l in alertas:
                ultimos_avisos[l.clave] = l.evaluacion.mejor.precio

    # Si un tramo deja de estar barato, se olvida su último aviso: cuando
    # vuelva a bajar, avisará otra vez.
    for l in lineas:
        if not l.evaluacion.motivos:
            ultimos_avisos.pop(l.clave, None)

    if fallos:
        todo = len(fallos) == len(pendientes)
        titulo = "Vigilante de vuelos: no pude consultar" + ("" if todo else " algún tramo")
        errores_envio += avisos.enviar(canales, titulo, "\n".join(fallos))

    toca_resumen = args.resumen or (
        config.resumen_semanal == DIAS_SEMANA[hoy.weekday()]
        and estado.get("ultimo_resumen") != hoy.isoformat()
    )
    if toca_resumen and not alertas:
        if lineas:
            cuerpo = "\n".join(_texto_linea(l, config.moneda, detalle=False) for l in lineas)
        elif not pendientes:
            cuerpo = "No queda ningún trayecto con fecha futura. Actualiza config.yaml."
        else:
            cuerpo = "Hoy no he podido consultar ningún tramo."
        errores = avisos.enviar(canales, "Vigilante de vuelos: resumen semanal", cuerpo)
        errores_envio += errores
        if not errores:
            estado["ultimo_resumen"] = hoy.isoformat()

    if not args.dry_run:
        # Si no salió ni una consulta (p. ej. sin red al encender), no cuenta:
        # la siguiente ejecución del día lo vuelve a intentar.
        if not (fallos and len(fallos) == len(pendientes)):
            estado["ultima_ejecucion"] = hoy.isoformat()
        historico.guardar_estado(estado)

    for e in errores_envio:
        print(f"FALLO AVISO  {e}")

    if not args.sin_agente:
        _ejecutar_agente(canales, args.dry_run)

    if errores_envio or (fallos and len(fallos) == len(pendientes)):
        return 1
    return 0


def _ejecutar_agente(canales: tuple[str, ...], dry_run: bool) -> None:
    """El agente no debe tumbar la vigilancia de trayectos: sus fallos solo se muestran."""
    print("\nAgente · destinos marcados y chollos")
    try:
        informe = agente.correr(canales, dry_run=dry_run)
    except Exception as e:
        print(f"FALLO AGENTE  {type(e).__name__}: {e}")
        return
    print(f"{informe.consultas} consultas · {len(informe.hallazgos)} viajes vistos")
    for titulo, candidatos in (
        ("Tus destinos", informe.avisos_marcados),
        ("Primera lectura de lo marcado", informe.presentacion),
        ("Fuera de tu lista", informe.avisos_otros),
    ):
        if candidatos:
            print(f"{titulo}:")
            for c in candidatos:
                print("  " + agente.texto_candidato(c).replace("\n", "\n  "))
    if not informe.hay_aviso:
        print("Nada que merezca un aviso hoy.")
    for e in informe.errores:
        print(f"FALLO AGENTE  {e}")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vigilante", description="Vigilante de precios de vuelos")
    p.add_argument("--dry-run", action="store_true", help="no guarda ni avisa; solo muestra")
    p.add_argument("--resumen", action="store_true", help="envía el resumen aunque no toque")
    p.add_argument("--probar-aviso", action="store_true", help="envía un aviso de prueba")
    p.add_argument("--sin-agente", action="store_true", help="solo los trayectos de config.yaml")
    p.add_argument(
        "--una-vez-al-dia", action="store_true", help="sale si hoy ya hubo una ejecución buena"
    )
    return p.parse_args()


def _texto_linea(linea: Linea, moneda: str, detalle: bool) -> str:
    cabecera = f"{linea.trayecto.nombre} · {_fecha_corta(linea.fecha)}"
    ev = linea.evaluacion
    if ev.mejor is None:
        return f"{cabecera}: sin vuelos que cumplan tus filtros"
    texto = f"{cabecera}: {_precio(ev.mejor.precio, moneda)} · {_texto_oferta(ev.mejor)}"
    if ev.motivos:
        texto += "\n  → " + " y ".join(ev.motivos)
    if detalle:
        if ev.media is not None:
            texto += f"\n  Media de tus últimos días: {_precio(ev.media, moneda)}"
        ctx = linea.contexto
        if ctx.rango_tipico and ctx.minimo_60d is not None:
            texto += (
                f"\n  Google (cualquier vuelo, sin tus filtros): habitual "
                f"{_precio(ctx.precio_habitual, moneda)}, rango típico "
                f"{ctx.rango_tipico[0]:g}–{_precio(ctx.rango_tipico[1], moneda)}, "
                f"mínimo 60 días {_precio(ctx.minimo_60d, moneda)}"
            )
    return texto


def _texto_oferta(o: Oferta) -> str:
    escalas = "directo" if o.directo else f"{o.escalas} escala{'s' if o.escalas > 1 else ''}"
    horas, minutos = divmod(o.duracion_min, 60)
    return (
        f"{o.aerolinea} {' '.join(o.vuelos)} · {escalas} · "
        f"{o.salida[11:]}→{o.llegada[11:]} ({horas} h {minutos:02d})"
    )


def _precio(valor: float, moneda: str) -> str:
    simbolo = "€" if moneda == "EUR" else moneda
    return f"{valor:.0f} {simbolo}"


def _fecha_corta(fecha: str) -> str:
    d = date.fromisoformat(fecha)
    return f"{DIAS_ABREV[d.weekday()]} {d.day}-{MESES[d.month - 1]}"


if __name__ == "__main__":
    sys.exit(main())
