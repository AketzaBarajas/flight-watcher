"""Genera el catálogo de países y ciudades con aeropuerto que usa el panel.

No hace falta ejecutarlo en el día a día: el resultado (catalogo.json) ya está
en el repo. Sirve para refrescar los datos de vez en cuando.

Uso (necesita `pip install babel pycountry`, que no son dependencias del programa):

    python scripts/construir_catalogo.py CARPETA_CON_DESCARGAS

La carpeta debe contener:
    airports.csv            https://davidmegginson.github.io/ourairports-data/airports.csv
    passport.csv            https://raw.githubusercontent.com/ilyankou/passport-index-dataset/master/passport-index-tidy-iso2.csv
    ryanair_airports.json   https://www.ryanair.com/api/views/locate/5/airports/es/active
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

import pycountry
from babel import Locale

SALIDA = Path(__file__).resolve().parent.parent / "vigilante" / "panel" / "datos" / "catalogo.json"
PASAPORTE = "ES"
TAMANOS = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}

# Nombres que CLDR da demasiado formales para un listado.
NOMBRES = {"HK": "Hong Kong", "MO": "Macao", "PS": "Palestina", "CD": "R. D. del Congo"}


# OurAirports da el municipio en inglés o en el idioma local ("Tokyo", o "Narita"
# para el aeropuerto de Tokio). Sin esto, buscar "tokio" o "nueva york" no
# encuentra nada. Lista hecha a mano con las grandes puertas de entrada.
CIUDADES_ES = {
    # Europa
    "LHR": "Londres", "LGW": "Londres", "LCY": "Londres", "CDG": "París", "ORY": "París",
    "AMS": "Ámsterdam", "FRA": "Fráncfort", "MUC": "Múnich", "ZRH": "Zúrich", "GVA": "Ginebra",
    "MXP": "Milán", "LIN": "Milán", "FCO": "Roma", "ATH": "Atenas", "KEF": "Reikiavik",
    "SVO": "Moscú", "DME": "Moscú", "LED": "San Petersburgo", "KBP": "Kiev", "OSL": "Oslo",
    "ARN": "Estocolmo", "CPH": "Copenhague", "HEL": "Helsinki", "WAW": "Varsovia",
    "LIS": "Lisboa", "BRU": "Bruselas", "VIE": "Viena", "PRG": "Praga", "IST": "Estambul",
    "SAW": "Estambul",
    # Asia y Oriente Medio
    "NRT": "Tokio", "HND": "Tokio", "KIX": "Osaka", "ITM": "Osaka", "PEK": "Pekín",
    "PKX": "Pekín", "PVG": "Shanghái", "SHA": "Shanghái", "CAN": "Cantón", "HKG": "Hong Kong",
    "ICN": "Seúl", "GMP": "Seúl", "BKK": "Bangkok", "DMK": "Bangkok", "HKT": "Phuket",
    "SIN": "Singapur", "KUL": "Kuala Lumpur", "CGK": "Yakarta", "DPS": "Bali",
    "MNL": "Manila", "HAN": "Hanói", "SGN": "Ho Chi Minh", "DEL": "Nueva Delhi",
    "BOM": "Bombay", "MLE": "Malé", "CMB": "Colombo", "KTM": "Katmandú", "TPE": "Taipéi",
    "DXB": "Dubái", "AUH": "Abu Dabi", "DOH": "Doha", "RUH": "Riad", "JED": "Yeda",
    "TLV": "Tel Aviv", "BEY": "Beirut", "TBS": "Tiflis", "EVN": "Ereván", "GYD": "Bakú",
    "TAS": "Taskent",
    # África
    "CAI": "El Cairo", "HRG": "Hurgada", "SSH": "Sharm el-Sheij", "CMN": "Casablanca",
    "TUN": "Túnez", "ALG": "Argel", "DSS": "Dakar", "NBO": "Nairobi", "ZNZ": "Zanzíbar",
    "JNB": "Johannesburgo", "CPT": "Ciudad del Cabo", "ADD": "Adís Abeba", "MRU": "Mauricio",
    "LOS": "Lagos", "ACC": "Acra",
    # América
    "JFK": "Nueva York", "EWR": "Nueva York", "LGA": "Nueva York", "BOS": "Boston",
    "IAD": "Washington", "MIA": "Miami", "MCO": "Orlando", "ORD": "Chicago",
    "LAX": "Los Ángeles", "SFO": "San Francisco", "LAS": "Las Vegas", "YYZ": "Toronto",
    "YUL": "Montreal", "YVR": "Vancouver", "MEX": "Ciudad de México", "CUN": "Cancún",
    "HAV": "La Habana", "PUJ": "Punta Cana", "SDQ": "Santo Domingo", "SJO": "San José",
    "PTY": "Ciudad de Panamá", "BOG": "Bogotá", "MDE": "Medellín",
    "CTG": "Cartagena de Indias", "UIO": "Quito", "LIM": "Lima", "CUZ": "Cuzco",
    "SCL": "Santiago de Chile", "EZE": "Buenos Aires", "AEP": "Buenos Aires",
    "MVD": "Montevideo", "GRU": "São Paulo", "GIG": "Río de Janeiro",
    "SSA": "Salvador de Bahía", "CCS": "Caracas", "LPB": "La Paz",
    # Oceanía
    "SYD": "Sídney", "MEL": "Melbourne", "AKL": "Auckland", "PPT": "Tahití", "NAN": "Fiyi",
}  # fmt: skip


def requisito(valor: str | None) -> dict:
    """Traduce el valor del dataset de pasaportes a una categoría propia."""
    if valor is None:
        return {"tipo": "sin_dato"}
    valor = valor.strip().lower()
    if valor == "-1":
        return {"tipo": "propio"}
    if valor.isdigit():
        return {"tipo": "sin_visado", "dias": int(valor)}
    return {
        "visa free": {"tipo": "sin_visado"},
        "visa on arrival": {"tipo": "visado_llegada"},
        "eta": {"tipo": "eta"},
        "e-visa": {"tipo": "evisa"},
        "visa required": {"tipo": "visado"},
        "no admission": {"tipo": "no_admision"},
    }.get(valor, {"tipo": "sin_dato"})


def centro(puntos: list[tuple]) -> list[float]:
    """Punto para señalar el país en el mapa: su aeropuerto principal.

    No es el centro geográfico (la media de aeropuertos de un archipiélago cae
    en el mar): es un sitio que seguro está dentro del país.
    """
    lon, lat, _ = min(puntos, key=lambda p: list(TAMANOS).index(p[2]))
    return [round(lon, 2), round(lat, 2)]


def main(carpeta: Path) -> None:
    territorios = Locale("es").territories

    entrada = {}
    with (carpeta / "passport.csv").open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if fila["Passport"] == PASAPORTE:
                entrada[fila["Destination"]] = fila["Requirement"]

    ryanair = {
        a["code"]: a["city"]["name"]
        for a in json.loads((carpeta / "ryanair_airports.json").read_text(encoding="utf-8"))
    }

    ciudades: dict[str, list[dict]] = {}
    coordenadas: dict[str, list[tuple]] = {}
    with (carpeta / "airports.csv").open(encoding="utf-8", newline="") as f:
        for a in csv.DictReader(f):
            iata = a["iata_code"].strip()
            if a["type"] not in TAMANOS or a["scheduled_service"] != "yes" or len(iata) != 3:
                continue
            ciudad = (
                CIUDADES_ES.get(iata)
                or ryanair.get(iata)
                or a["municipality"].strip()
                or a["name"].strip()
            )
            aeropuerto = {
                "iata": iata,
                "ciudad": ciudad,
                "aeropuerto": a["name"].strip(),
                "tam": TAMANOS[a["type"]],
            }
            if iata in ryanair:
                aeropuerto["ry"] = True
            ciudades.setdefault(a["iso_country"], []).append(aeropuerto)
            coordenadas.setdefault(a["iso_country"], []).append(
                (float(a["longitude_deg"]), float(a["latitude_deg"]), a["type"])
            )

    paises = []
    for iso, lista in ciudades.items():
        pais = pycountry.countries.get(alpha_2=iso)
        # Primero las grandes puertas de entrada, luego por tamaño y nombre.
        lista.sort(
            key=lambda c: (c["iata"] not in CIUDADES_ES, "LMS".index(c["tam"]), c["ciudad"].casefold())
        )
        paises.append(
            {
                "iso": iso,
                "num": pais.numeric if pais else None,
                "nombre": NOMBRES.get(iso) or territorios.get(iso) or (pais.name if pais else iso),
                "entrada": requisito(entrada.get(iso)),
                "centro": centro(coordenadas[iso]),
                "ciudades": lista,
            }
        )
    paises.sort(key=lambda p: p["nombre"].casefold())

    catalogo = {
        "generado": date.today().isoformat(),
        "pasaporte": PASAPORTE,
        "fuentes": {
            "aeropuertos": "OurAirports (dominio público): aeropuertos con servicio regular y código IATA",
            "entrada": "passport-index-dataset de ilyankou (datos de Passport Index, feb-2026). Orientativo",
            "nombres_ryanair": "Nombres de ciudad en español de los aeropuertos donde opera Ryanair",
        },
        "paises": paises,
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(
        json.dumps(catalogo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    n_ciudades = sum(len(p["ciudades"]) for p in paises)
    print(f"{len(paises)} países, {n_ciudades} aeropuertos -> {SALIDA} ({SALIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
