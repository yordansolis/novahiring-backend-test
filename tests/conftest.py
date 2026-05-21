import pytest

from contracts import DiscoveryJSON


@pytest.fixture
def discovery_fixture():
    return DiscoveryJSON(
        cliente={},
        problema_negocio={},
        producto_a_construir={},
        contexto_equipo={},
        restricciones={},
        perfil_candidato={
            "habilidades_tecnicas": {"obligatorias": [], "deseables": []},
            "habilidades_blandas": {},
            "senales_de_seniority": {},
            "criterios_de_descarte": [
                {"id": "KO1", "descripcion": "WhatsApp", "razon": "x"},
                {"id": "KO2", "descripcion": "RGPD", "razon": "x"},
                {"id": "KO3", "descripcion": "Autonomy", "razon": "x"},
            ],
        },
        scorecard={
            "peso_total": 19,
            "dimensiones": [
                {"id": "D1", "nombre": "Integraciones", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D2", "nombre": "RGPD", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D3", "nombre": "Autonomía", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D4", "nombre": "Pragmatismo", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D5", "nombre": "Entrega", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D6", "nombre": "Comunicación", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D7", "nombre": "Salud", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D8", "nombre": "Stack", "peso": 1, "rubricas": {"5": "a", "3": "b", "1": "c"}},
            ],
        },
        criterios_de_exito=[],
    )
