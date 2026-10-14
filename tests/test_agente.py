from datetime import date

import pytest

from vigilante import agente
from vigilante.catalogo import Catalogo
from vigilante.intereses import ErrorIntereses, construir, validar
from vigilante.modelos import Contexto, Hallazgo, Oferta

HOY = date(2026, 10, 13)

CATALOGO = Catalogo(
    {
        "paises": [
            {
                "iso": "ES", "num": "724", "nombre": "España", "entrada": {"tipo": "propio"},
                "ciudades": [{"iata": "MAD", "ciudad": "Madrid", "aeropuerto": "Barajas", "tam": "L", "ry": True}],
            },
            {
                "iso": "AT", "num": "040", "nombre": "Austria", "entrada": {"tipo": "sin_visado"},
                "ciudades": [{"iata": "VIE", "ciudad": "Viena", "aeropuerto": "Schwechat", "tam": "L", "ry": True}],
            },
            {
                "iso": "MA", "num": "504", "nombre": "Marruecos", "entrada": {"tipo": "sin_visado"},
                "ciudades": [
                    {"iata": "AGA", "ciudad": "Agadir", "aeropuerto": "Al Massira", "tam": "M", "ry": True},
                    {"iata": "RAK", "ciudad": "Marrakech", "aeropuerto": "Menara", "tam": "L", "ry": True},
                ],
            },
            {
                "iso": "JP", "num": "392", "nombre": "Japón", "entrada": {"tipo": "sin_visado"},
                "ciudades": [
                    {"iata": "NRT", "ciudad": "Tokyo", "aeropuerto": "Narita", "tam": "L"},
                    {"iata": "KIX", "ciudad": "Osaka", "aeropuerto": "Kansai", "tam": "L"},
                ],
            },
        ]
    }
)  # fmt: skip


def intereses(paises: dict | None = None, **ajustes):
    return construir(validar({"paises": paises or {}, "ajustes": ajustes}, CATALOGO))


def viaje(destino: str, precio: float, ida: str = "2026-11-12", vuelta: str = "2026-11-15", **kw):
    return Hallazgo("MAD", destino, ida, vuelta, precio, "Ryanair", "ryanair", **kw)


def decidir(hallazgos, inter, habituales=None, estado=None):
    informe = agente.Informe(hallazgos=hallazgos)
    agente.decidir(
        informe, inter, CATALOGO, HOY, agente.periodos(HOY, inter.meses), habituales or {}, estado or {}
    )
    return informe


# ---- intereses ----


def test_validar_rellena_valores_por_defecto():
    datos = validar({}, CATALOGO)
    assert datos["origen"] == "MAD" and datos["ajustes"]["chollo_max"] == 25


@pytest.mark.parametrize(
    "malo",
    [
        {"origen": "XXX"},
        {"paises": {"ZZ": {}}},
        {"paises": {"AT": {"ciudades": ["NRT"]}}},
        {"paises": {"AT": {"ventanas": [{"desde": "2026-12-10", "hasta": "2026-12-01"}]}}},
        {"paises": {"AT": {"precio_max": "barato"}}},
        {"paises": {"AT": {"noches": [5, 2]}}},
        {"ajustes": {"noches_min": 6, "noches_max": 3}},
        {"ajustes": {"meses": 99}},
    ],
)
def test_validar_rechaza_datos_malos(malo):
    with pytest.raises(ErrorIntereses):
        validar(malo, CATALOGO)


# ---- planificar ----


def test_periodos_resto_del_mes_y_siguientes():
    ps = agente.periodos(HOY, 3)
    assert [p.id for p in ps] == ["2026-10", "2026-11", "2026-12", "2027-01"]
    assert ps[0].desde == date(2026, 10, 14) and ps[0].hasta == date(2026, 10, 31)
    assert ps[-1].etiqueta == "enero 2027"


def test_periodos_sin_resto_si_el_mes_se_acaba():
    assert [p.id for p in agente.periodos(date(2026, 10, 30), 1)] == ["2026-11"]


def test_plan_exploracion_pone_primero_las_fechas_marcadas():
    inter = intereses({"AT": {"ventanas": [{"desde": "2026-12-17", "hasta": "2026-12-23"}]}}, meses=2)
    plan = agente.plan_exploracion(inter, HOY, agente.periodos(HOY, 2))
    assert plan[0] == (date(2026, 12, 17), date(2026, 12, 23), 2, 5)
    assert len(plan) == 4  # la ventana + resto de octubre + noviembre + diciembre


def test_plan_exploracion_usa_las_noches_propias_del_pais():
    inter = intereses({"MA": {"noches": [7, 10]}}, meses=1)
    plan = agente.plan_exploracion(inter, HOY, agente.periodos(HOY, 1))
    assert (date(2026, 11, 1), date(2026, 11, 30), 7, 10) in plan
    assert (date(2026, 11, 1), date(2026, 11, 30), 2, 5) in plan


def test_plan_exploracion_descarta_ventanas_pasadas():
    inter = intereses({"AT": {"ventanas": [{"desde": "2026-01-01", "hasta": "2026-01-10"}]}}, meses=1)
    plan = agente.plan_exploracion(inter, HOY, agente.periodos(HOY, 1))
    assert all(desde > HOY for desde, *_ in plan)


def test_plan_google_llena_los_huecos_que_ryanair_no_cubre():
    inter = intereses(
        {"JP": {"ciudades": ["NRT"], "noches": [10, 14]}, "AT": {"ciudades": ["VIE"]}},
        consultas_google=10,
    )
    periodos = agente.periodos(HOY, 4)
    cubiertos = {("VIE", p.id) for p in periodos}
    plan = agente.plan_google(inter, CATALOGO, HOY, periodos, 0, cubiertos)
    # Octubre solo deja hueco desde el día 27 (antelación de dos semanas): cabe.
    assert sorted(ida.strftime("%Y-%m") for _, ida, _ in plan) == [p.id for p in periodos]
    assert {destino for destino, _, _ in plan} == {"NRT"}
    assert all((vuelta - ida).days == 12 for _, ida, vuelta in plan)
    assert all((ida - HOY).days >= agente.ANTELACION_GOOGLE for _, ida, _ in plan)

    # Sin Ryanair, Viena también necesita Google.
    plan = agente.plan_google(inter, CATALOGO, HOY, periodos, 0)
    assert {destino for destino, _, _ in plan} == {"NRT", "VIE"}


def test_plan_google_reparte_entre_ciudades_antes_que_entre_meses():
    inter = intereses({"JP": {"ciudades": ["NRT", "KIX"]}}, consultas_google=2)
    plan = agente.plan_google(inter, CATALOGO, HOY, agente.periodos(HOY, 4), cursor=0)
    assert {destino for destino, _, _ in plan} == {"NRT", "KIX"}


def test_plan_google_primero_lo_nunca_visto_y_luego_lo_mas_viejo():
    inter = intereses({"JP": {"ciudades": ["NRT"]}}, consultas_google=4)
    periodos = agente.periodos(HOY, 4)  # oct, nov, dic, ene, feb
    vistos = {("NRT", "2026-11"): "2026-10-10", ("NRT", "2026-12"): "2026-10-01"}
    meses = lambda plan: sorted(ida.strftime("%Y-%m") for _, ida, _ in plan)
    assert meses(agente.plan_google(inter, CATALOGO, HOY, periodos, 0, vistos=vistos)) == [
        "2026-10", "2026-12", "2027-01", "2027-02",
    ]  # fmt: skip


def test_plan_google_pais_sin_ciudades_usa_las_de_ryanair():
    inter = intereses({"MA": {}}, consultas_google=2)
    plan = agente.plan_google(inter, CATALOGO, HOY, agente.periodos(HOY, 4), 0)
    assert {destino for destino, _, _ in plan} == {"AGA", "RAK"}


def test_plan_google_cambia_de_fechas_cada_dia():
    inter = intereses({"JP": {"ciudades": ["NRT"]}}, consultas_google=2)
    ps = agente.periodos(HOY, 4)
    assert agente.plan_google(inter, CATALOGO, HOY, ps, 0) != agente.plan_google(inter, CATALOGO, HOY, ps, 1)


def test_plan_google_vacio_si_no_hay_presupuesto_o_nada_marcado():
    ps = agente.periodos(HOY, 4)
    assert agente.plan_google(intereses({"JP": {"ciudades": ["NRT"]}}, consultas_google=0), CATALOGO, HOY, ps, 0) == []
    assert agente.plan_google(intereses({"JP": {}}), CATALOGO, HOY, ps, 0) == []


# ---- percibir ----


def test_percibir_junta_exploracion_y_google():
    inter = intereses({"JP": {"ciudades": ["NRT"]}}, meses=1, consultas_google=1)

    def google(origen, destino, ida, vuelta):
        cara = Oferta(900, ("ANA",), ("NH1",), ida, ida, 0, 800)
        con_dos_escalas = Oferta(500, ("X",), ("X1",), ida, ida, 2, 2000)
        buena = Oferta(700, ("Etihad",), ("EY1",), ida, ida, 1, 1100)
        return [cara, con_dos_escalas, buena], Contexto(rango_tipico=(720, 1100))

    informe = agente.percibir(
        inter, CATALOGO, HOY, agente.periodos(HOY, 1), 0,
        explorar=lambda *a: [viaje("AGA", 31)], ida_vuelta=google, pausa=0,
    )  # fmt: skip
    japon = [h for h in informe.hallazgos if h.destino == "NRT"]
    assert len(japon) == 1 and japon[0].precio == 700 and japon[0].rango_tipico == (720, 1100)
    assert sum(h.destino == "AGA" for h in informe.hallazgos) == 2  # resto de octubre + noviembre
    assert informe.consultas == 3 and not informe.errores


def test_percibir_no_pide_a_google_lo_que_ya_trae_ryanair():
    inter = intereses({"AT": {}}, meses=1, consultas_google=5)
    pedidos = []

    def google(origen, destino, ida, vuelta):
        pedidos.append((destino, ida[:7]))
        return [], Contexto()

    agente.percibir(
        inter, CATALOGO, HOY, agente.periodos(HOY, 1), 0,
        explorar=lambda *a: [viaje("VIE", 90)], ida_vuelta=google, pausa=0,
    )  # fmt: skip
    assert pedidos == [("VIE", "2026-10")]  # noviembre ya lo trae Ryanair


def test_percibir_deja_de_explorar_tras_dos_fallos():
    llamadas = []

    def caida(*a):
        llamadas.append(a)
        raise RuntimeError("HTTP 403")

    informe = agente.percibir(
        intereses(meses=4), CATALOGO, HOY, agente.periodos(HOY, 4), 0, explorar=caida, pausa=0
    )
    assert len(llamadas) == 2 and len(informe.errores) == 3 and not informe.hallazgos


# ---- decidir ----


def test_no_marcado_solo_avisa_si_es_chollo():
    informe = decidir([viaje("AGA", 31), viaje("RAK", 60)], intereses(chollo_max=35))
    assert [c.hallazgo.destino for c in informe.avisos_otros] == ["AGA"]
    assert "chollo" in informe.avisos_otros[0].motivos[0]
    assert not informe.avisos_marcados and not informe.presentacion


def test_marcado_avisa_por_precio_maximo():
    inter = intereses({"AT": {"precio_max": 100}})
    informe = decidir([viaje("VIE", 90)], inter)
    assert [c.hallazgo.destino for c in informe.avisos_marcados] == ["VIE"]
    assert not informe.presentacion  # ya va en el aviso: no se repite como primera lectura


def test_marcado_caro_solo_se_presenta_la_primera_vez():
    inter = intereses({"AT": {"precio_max": 50}})
    primera = decidir([viaje("VIE", 90)], inter)
    assert not primera.avisos_marcados
    assert [c.hallazgo.destino for c in primera.presentacion] == ["VIE"]

    segunda = decidir([viaje("VIE", 90)], inter, estado={"presentados": ["AT"]})
    assert not segunda.hay_aviso


def test_primera_lectura_una_linea_por_pais_con_su_mejor_precio():
    inter = intereses({"MA": {}, "AT": {}})
    informe = decidir([viaje("RAK", 40), viaje("AGA", 31), viaje("VIE", 144)], inter)
    assert [c.hallazgo.destino for c in informe.presentacion] == ["AGA", "VIE"]


def test_fuera_de_las_fechas_marcadas_cuenta_como_no_marcado():
    inter = intereses({"AT": {"ventanas": [{"desde": "2026-12-17", "hasta": "2026-12-23"}], "precio_max": 200}})
    informe = decidir([viaje("VIE", 90, ida="2026-11-12", vuelta="2026-11-15")], inter)
    assert not informe.avisos_marcados and not informe.avisos_otros


def test_ciudad_no_elegida_del_pais_marcado_cuenta_como_no_marcada():
    inter = intereses({"MA": {"ciudades": ["RAK"], "precio_max": 100}})
    informe = decidir([viaje("AGA", 80), viaje("RAK", 80)], inter)
    assert [c.hallazgo.destino for c in informe.avisos_marcados] == ["RAK"]
    assert not informe.avisos_otros  # Agadir a 80 € no es chollo


def test_bajada_frente_a_lo_habitual_exige_mas_a_lo_no_marcado():
    habituales = {("VIE", "2026-11"): 100.0, ("RAK", "2026-11"): 100.0}
    informe = decidir([viaje("VIE", 84), viaje("RAK", 84)], intereses({"AT": {}}), habituales)
    assert [c.hallazgo.destino for c in informe.avisos_marcados] == ["VIE"]
    assert not informe.avisos_otros

    informe = decidir([viaje("RAK", 64)], intereses(), habituales)
    assert [c.hallazgo.destino for c in informe.avisos_otros] == ["RAK"]


def test_rango_tipico_de_google_avisa_en_lo_marcado():
    inter = intereses({"JP": {"ciudades": ["NRT"], "noches": [10, 14]}})
    h = viaje("NRT", 700, ida="2027-02-10", vuelta="2027-02-22", rango_tipico=(720, 1100))
    informe = decidir([h], inter)
    assert "rango típico" in informe.avisos_marcados[0].motivos[0]


def test_anti_ruido_solo_repite_si_mejora_o_pasa_el_tiempo():
    estado = {"avisadas": {"AGA|2026-11": {"precio": 31, "dia": "2026-10-10"}}}
    inter = intereses(chollo_max=35)
    assert not decidir([viaje("AGA", 30)], inter, estado=estado).avisos_otros
    assert decidir([viaje("AGA", 27)], inter, estado=estado).avisos_otros

    viejo = {"avisadas": {"AGA|2026-11": {"precio": 31, "dia": "2026-09-01"}}}
    assert decidir([viaje("AGA", 31)], inter, estado=viejo).avisos_otros


def test_como_mucho_tres_chollos_y_uno_por_ciudad():
    hallazgos = [viaje("AGA", 20), viaje("AGA", 21, ida="2026-12-03", vuelta="2026-12-06")]
    hallazgos += [viaje("RAK", 22), viaje("VIE", 23)]
    informe = decidir(hallazgos, intereses())
    assert [c.hallazgo.destino for c in informe.avisos_otros] == ["AGA", "RAK", "VIE"]


def test_recomendaciones_llevan_lo_mejor_de_cada_destino_y_mes():
    inter = intereses({"AT": {}}, meses=2)
    hallazgos = [
        viaje("AGA", 31),
        viaje("VIE", 144),
        viaje("VIE", 150, ida="2026-11-20", vuelta="2026-11-23"),
        viaje("RAK", 40, ida="2026-12-03", vuelta="2026-12-06"),
        viaje("RAK", 45, ida="2027-02-03", vuelta="2027-02-06"),  # fuera de los meses que se miran
    ]
    rec = decidir(hallazgos, inter).recomendaciones
    assert [p["id"] for p in rec["periodos"]] == ["2026-10", "2026-11", "2026-12"]
    assert [(o["destino"], o["precio"], o["marcado"]) for o in rec["ofertas"]] == [
        ("AGA", 31, False),
        ("RAK", 40, False),
        ("VIE", 144, True),
    ]
    vie = rec["ofertas"][2]
    assert vie["ciudad"] == "Viena" and vie["visto"] == HOY.isoformat()
    assert "google.com/travel/flights" in vie["enlace"]


def test_recomendaciones_completan_lo_marcado_con_lo_ultimo_visto():
    inter = intereses({"JP": {"ciudades": ["NRT"]}, "AT": {}}, meses=2)
    anteriores = [
        agente.Candidato(viaje("NRT", 700), CATALOGO.lugar("NRT"), True, visto="2026-10-11"),
        agente.Candidato(viaje("VIE", 90), CATALOGO.lugar("VIE"), True, visto="2026-10-12"),
    ]
    informe = agente.Informe(hallazgos=[viaje("VIE", 144)])
    agente.decidir(
        informe, inter, CATALOGO, HOY, agente.periodos(HOY, 2), {}, {}, anteriores
    )
    ofertas = informe.recomendaciones["ofertas"]
    # Viena tiene precio hoy: el de anteayer, aunque más barato, ya no vale.
    assert [(o["destino"], o["precio"], o["visto"]) for o in ofertas] == [
        ("VIE", 144, "2026-10-13"),
        ("NRT", 700, "2026-10-11"),
    ]
    # Lo visto otros días no avisa: solo sirve para el panel.
    assert "NRT" not in {c.hallazgo.destino for c in informe.avisos_marcados + informe.presentacion}


# ---- recordar ----


def test_precio_habitual_necesita_dias_suficientes(tmp_path):
    csv = tmp_path / "ofertas.csv"
    for dia, precio in enumerate([100, 110, 90, 105, 95], start=1):
        agente.guardar_hallazgos([viaje("VIE", precio), viaje("VIE", precio + 50)], date(2026, 10, dia), csv)
    agente.guardar_hallazgos([viaje("AGA", 30)], date(2026, 10, 1), csv)

    habituales = agente.precios_habituales(date(2026, 10, 13), csv)
    assert habituales == {("VIE", "2026-11"): 100}
    assert agente.precios_habituales(date(2026, 10, 13), tmp_path / "no_existe.csv") == {}


def test_ultimos_vistos_solo_lo_marcado_futuro_y_del_ultimo_dia(tmp_path):
    csv = tmp_path / "ofertas.csv"
    inter = intereses({"JP": {"ciudades": ["NRT"], "noches": [10, 14]}, "AT": {}})
    nrt = dict(ida="2027-01-10", vuelta="2027-01-22")
    agente.guardar_hallazgos([viaje("NRT", 650, **nrt)], date(2026, 10, 9), csv)
    agente.guardar_hallazgos([viaje("NRT", 720, **nrt), viaje("NRT", 700, **nrt)], date(2026, 10, 11), csv)
    agente.guardar_hallazgos([viaje("NRT", 500, **nrt)], date(2026, 9, 1), csv)  # demasiado viejo
    agente.guardar_hallazgos([viaje("NRT", 400, ida="2027-01-10", vuelta="2027-01-13")], date(2026, 10, 12), csv)  # noches
    agente.guardar_hallazgos([viaje("VIE", 30, ida="2026-10-12", vuelta="2026-10-15")], date(2026, 10, 10), csv)  # ya pasó
    agente.guardar_hallazgos([viaje("AGA", 20)], date(2026, 10, 12), csv)  # no marcado
    agente.guardar_hallazgos([viaje("VIE", 99)], HOY, csv)  # lo de hoy va por otro lado

    vistos = agente.ultimos_vistos(inter, CATALOGO, HOY, csv)
    assert [(c.hallazgo.destino, c.hallazgo.precio, c.visto, c.marcado) for c in vistos] == [
        ("NRT", 700, "2026-10-11", True)
    ]
    assert agente.ultimos_vistos(inter, CATALOGO, HOY, tmp_path / "no_existe.csv") == []


# ---- actuar ----


def test_aviso_separa_tus_destinos_de_lo_que_esta_fuera_de_tu_lista():
    inter = intereses({"AT": {"precio_max": 100}}, chollo_max=35)
    informe = decidir([viaje("VIE", 90), viaje("AGA", 31)], inter)
    titulo, cuerpo, url = agente.componer_aviso(informe)
    assert titulo == "Vuelos: Viena 90 € i/v"
    assert cuerpo.index("TUS DESTINOS") < cuerpo.index("FUERA DE TU LISTA")
    assert "Agadir (Marruecos) · 12 nov → 15 nov · 31 € i/v" in cuerpo
    assert "VIE" in url
