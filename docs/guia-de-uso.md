# Guía de uso (español)

Guía detallada del panel, el agente y la configuración. El resumen en inglés está en el [README](../README.md).

Vigila precios de vuelos y **solo avisa cuando merece la pena**. Hace dos trabajos:

1. **Trayectos exactos** (`config.yaml`, copiado de `config.example.yaml`): un tramo y una fecha concretos, como Madrid → Lisboa el 12-mar.
2. **Agente de destinos** (panel): marcas países, ciudades y fechas que te interesan; el agente los prioriza, y de lo que no has marcado solo te manda los chollos.

```
                 ┌─────────── panel (icono de la bandeja) ───────────┐
                 │ mapa · mis destinos · buscador · recomendaciones   │
                 └──────────────┬─────────────────────▲───────────────┘
                     data/intereses.json     data/recomendaciones.json
                                ▼                     │
[tarea diaria 08:00] → trayectos exactos → agente: planificar → consultar → recordar → decidir
                            │                              │                             │
                      Google Flights            Ryanair (explorar) + Google        aviso ntfy/correo
```

## El panel

Se abre desde el icono amarillo de la bandeja (iconos ocultos de la barra de tareas): clic izquierdo, o clic derecho → *Abrir panel*.

```powershell
scripts\abrir_bandeja.cmd                                                   # arrancar el icono ahora
powershell -ExecutionPolicy Bypass -File scripts\arranque_con_windows.ps1   # que arranque con Windows
powershell -ExecutionPolicy Bypass -File scripts\arranque_con_windows.ps1 -Quitar
```

- **Mapa**: los países marcados salen en amarillo. Clic en un país abre su ficha.
- **Mis destinos**: lo marcado, de 5 en 5.
- **Buscar destino**: por país, ciudad o código de aeropuerto. Lista 233 países y territorios con 4.008 aeropuertos con vuelos regulares, y el requisito de entrada con pasaporte español. Los que exigen visado previo están ocultos salvo que actives la casilla.
- **Ficha de país**: ciudades concretas, fechas de salida, precio máximo y noches.
- **Viajes baratos para los próximos meses**, en dos listas:
  - **Tus destinos**: todas las ciudades que has marcado, una fila por ciudad (Londres junta Stansted, Gatwick, Heathrow...) con su vuelo más barato. Si la búsqueda de hoy no trae precio de una ciudad (pasa con las que solo se miran en Google, que son pocas fechas al día), sale el último precio conocido, con *visto el…*; si nunca se ha visto, *Sin precio todavía*. Cada ciudad y mes se vuelve a mirar en unas dos semanas.
  - **Fuera de tu lista**: lo más barato de cada ciudad que no has marcado.
  - Pestañas por mes y una de **Todos los meses**, donde cada ciudad lleva su vuelo más barato de toda la temporada.
  - **Filtros**: fecha de salida (desde / hasta), precio máximo y destino (ciudad, país o código, en español o inglés). Con fechas o precio puestos, las ciudades tuyas sin vuelos que cumplan se resumen en una línea desplegable debajo de la lista.
- **Ajustes**: meses hacia delante, noches de un viaje normal, umbral de chollo y tope de consultas a Google.
- **Idioma y tema**: arriba a la derecha, **ES / EN** cambia todo el panel entre español e inglés (los avisos al móvil siguen en español), y el botón de luna / sol cambia entre tema claro y oscuro. Al principio se usa el tema de Windows; lo que elijas se recuerda en ese navegador.

El panel es una web local en `http://127.0.0.1:8765`: solo escucha en tu ordenador y rechaza peticiones que no vengan de él mismo.

## El agente

No es un modelo de lenguaje: es un bucle de reglas (`vigilante/agente.py`). En cada ejecución:

| Paso | Qué hace |
|---|---|
| Planificar | Decide qué pedir hoy con un tope: primero las fechas de lo marcado, después los meses generales. Después, Google para cada ciudad marcada y mes que Ryanair no haya cubierto hoy (también ciudades a las que Ryanair vuela, pero no desde tu aeropuerto): primero lo nunca visto y luego lo que lleva más tiempo sin precio, hasta el tope diario (25 por defecto) |
| Consultar | Ryanair devuelve el ida y vuelta más barato a cada destino en un rango de fechas; Google, una ciudad y fechas concretas |
| Recordar | Guarda todo en `data/ofertas.csv`; de ahí sale "lo que suele costar" cada destino y mes |
| Decidir | Separa marcado / fuera de lista y aplica reglas distintas (abajo) |
| Actuar | Escribe `data/recomendaciones.json` para el panel y manda un solo aviso |

Cuándo avisa:

| | Marcado | Fuera de tu lista |
|---|---|---|
| Precio | ≤ tu precio máximo, si lo pusiste | ≤ umbral de chollo (25 € por defecto) |
| Bajada | 15 % por debajo de lo habitual | 35 % por debajo de lo habitual |
| Google | por debajo de su "rango típico" | — |
| Primera lectura | al marcar un país, su mejor precio de hoy (una vez) | — |
| Tope | 6 por aviso | 3 por aviso, uno por ciudad |

"Lo habitual" es la mediana del mejor precio diario de ese destino y mes; necesita 5 días de histórico. Un aviso no se repite salvo que el precio mejore un 10 % o pasen 3 semanas.

**Límites que conviene saber:**

- Explorar "a cualquier sitio" solo cubre **la red de Ryanair** desde tu aeropuerto. No he encontrado una fuente gratuita equivalente para el resto de aerolíneas.
- Un país al que Ryanair no vuela (Japón, Tailandia…) **solo se vigila si eliges ciudades** en su ficha. Cada consulta a Google mira una fecha: con 8 al día y varias ciudades, cada una se revisa poco.
- El umbral de chollo por defecto (25 €) queda por debajo del suelo de Ryanair (2 × 14,99 €) a propósito: con 35 € llegarían avisos casi a diario de precios que son normales.

## Trayectos exactos

`config.yaml` → lista `trayectos` (origen y destino IATA, fechas, `precio_max`). Varias fechas en un trayecto = flexibilidad de días. Las fechas pasadas se ignoran solas.

| Regla | Condición |
|---|---|
| Umbral | mejor precio (con tus filtros) ≤ `precio_max` |
| Bajada | ≥ `bajada_pct` % por debajo de la media de los últimos `dias_media` días (mínimo 3 días de histórico) |
| Anti-ruido | solo repite si el precio mejora el del último aviso |
| Fallo | si la fuente no responde, avisa de "no pude consultar" |
| Resumen | el día de `resumen_semanal` manda los precios aunque no haya chollo: si no llega, está caído |

## Uso desde la terminal

```powershell
.venv\Scripts\python -m vigilante --dry-run       # ver qué haría hoy, sin guardar ni avisar
.venv\Scripts\python -m vigilante                 # ejecución real (la que se programa)
.venv\Scripts\python -m vigilante --sin-agente    # solo los trayectos de config.yaml
.venv\Scripts\python -m vigilante --resumen       # fuerza el resumen semanal
.venv\Scripts\python -m vigilante --probar-aviso  # manda un aviso de prueba
.venv\Scripts\python -m vigilante.panel.servidor  # el panel sin icono de bandeja
.venv\Scripts\python -m pytest                    # tests
```

Instalar desde cero:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pytest
copy .env.example .env               # y rellena NTFY_TOPIC
copy config.example.yaml config.yaml # y pon tus trayectos
```

## Avisos en el móvil (ntfy)

1. Instala la app **ntfy** (Android/iOS).
2. "Suscribirse a un tema" → pega el valor de `NTFY_TOPIC` de tu `.env`.
3. Comprueba: `.venv\Scripts\python -m vigilante --probar-aviso`.

El nombre del tema hace de contraseña: por eso vive en `.env` y no en el repo. Para correo, añade `email` a `avisos.canales` y rellena `EMAIL_*` en `.env`. **El canal de correo está escrito pero sin probar.**

## Programarlo

**Windows.** Al iniciar sesión (5 min después) y cada hora desde las 08:00 hasta medianoche. El programa corre con `--una-vez-al-dia`: solo la primera ejecución buena del día consulta precios y las demás salen al momento. Si fallan todas las consultas (p. ej. sin red), no cuenta y se reintenta a la hora siguiente. Así funciona aunque el PC no esté encendido a las 08:00.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\programar_windows.ps1            # desde las 08:00
powershell -ExecutionPolicy Bypass -File scripts\programar_windows.ps1 -Hora 10:00
Unregister-ScheduledTask -TaskName VigilanteVuelos -Confirm:$false                # quitarlo
```

La salida de cada ejecución se acumula en `data\ultima_ejecucion.log`. La tarea diaria no depende del icono de la bandeja: el icono es solo para abrir el panel.

**GitHub Actions.** No incluido: una ejecución programada en GitHub tendría que guardar `data/` en el repo, y aquí `data/` es personal y no se sube.

## Las fuentes de datos (lo frágil)

Ninguna es una API oficial. Las dos pueden romperse sin aviso y son zona gris de las condiciones de uso de cada web; aquí son unas 40 peticiones al día (hasta 14 a Ryanair y 25 a Google por defecto) para uso personal.

- **Google Flights** (`fuentes/google_flights.py`): lee la página de resultados. Desde la UE envía la cookie equivalente a "Rechazar todo" en el aviso de cookies. El parseo es propio porque `fast-flights 3.1.0` ignora la lista "mejores vuelos".
- **Ryanair** (`fuentes/ryanair.py`): la API interna de su buscador de tarifas. Solo vuelos de Ryanair.
- Descartadas tras probarlas el 2026-10-13: el calendario de precios de Google (devuelve error) y Amadeus Self-Service (cerró el 17-jul-2026).
- Precios **por adulto en tarifa básica**, sin maleta. El precio final se ve al reservar.

**Plan B para Google:** SerpApi (de pago, con plan gratuito de unas 250 búsquedas/mes según webs de terceros). Una fuente nueva es un módulo en `vigilante/fuentes/`.

## El catálogo de países y ciudades

`vigilante/panel/datos/catalogo.json`, generado por `scripts/construir_catalogo.py` a partir de:

- **OurAirports** (dominio público): aeropuertos con servicio regular y código IATA.
- **passport-index-dataset** (datos de Passport Index, actualizado en feb-2026): requisito de entrada con pasaporte español. **Orientativo**: los visados cambian; confirma en la web del Ministerio de Exteriores antes de comprar.
- Nombres de ciudad en español: los de Ryanair para sus aeropuertos y una lista manual para las grandes ciudades del mundo. El resto salen como en OurAirports (inglés o idioma local).
- Nombres de ciudad en inglés (campo `en`, solo cuando cambian): los de Ryanair en inglés y una lista manual para las de la lista española. Los nombres de país en inglés no se guardan: los da el navegador.

## Estructura

```
config.example.yaml        plantilla de config.yaml (trayectos exactos y canales de aviso)
.env.example               plantilla de .env (claves; .env no se sube)
vigilante/
  __main__.py              trayectos exactos y, después, el agente
  agente.py                planificar · consultar · recordar · decidir · actuar
  intereses.py             lo marcado en el panel (validación)
  catalogo.py              países y ciudades
  bandeja.py               icono de la bandeja
  panel/servidor.py        servidor local del panel
  panel/static/            interfaz (HTML, CSS, JS, textos en español e inglés, mapa, tipografía)
  fuentes/                 google_flights.py · ryanair.py
  historico.py · reglas.py · avisos.py
data/                      se crea al ejecutar; no se sube
  intereses.json           lo marcado
  ofertas.csv              todo lo que ha visto el agente
  recomendaciones.json     última lectura para el panel: lo mejor de cada destino y mes
  precios.csv              histórico de los trayectos exactos
  estado.json              últimos avisos enviados y cursor del agente
tests/                     reglas, parseo, agente, servidor y flujo completo
```
