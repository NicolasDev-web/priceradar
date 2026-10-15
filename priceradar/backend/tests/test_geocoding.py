"""Geocodificação do endereço digitado (services/geocoding.py), sem rede."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import geocoding  # noqa: E402

RESPOSTA_OSM = [{
    "lat": "-3.7461", "lon": "-38.4710", "display_name": "1000, Rua Vilebaldo Aguiar, Cocó, Fortaleza",
    "address": {"house_number": "1000", "road": "Rua Vilebaldo Aguiar", "suburb": "Cocó"},
}]


@pytest.fixture
def isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(geocoding, "_CACHE_PATH", tmp_path / "geo.json")
    monkeypatch.setattr(geocoding, "HABILITADO", True)
    monkeypatch.setattr(geocoding, "INTERVALO_MINIMO_S", 0.0)
    chamadas = []

    async def falsa(endereco, cidade):
        chamadas.append(endereco)
        return RESPOSTA_OSM

    monkeypatch.setattr(geocoding, "_consultar", falsa)
    return chamadas


def test_interpreta_resposta_com_numero():
    r = geocoding.interpretar_resposta(RESPOSTA_OSM)
    assert r["latitude"] == pytest.approx(-3.7461)
    assert r["bairro"] == "Cocó"
    assert r["precisa"] is True


def test_sem_numero_nao_e_precisa():
    sem = [{**RESPOSTA_OSM[0], "address": {"road": "Rua Vilebaldo Aguiar"}}]
    assert geocoding.interpretar_resposta(sem)["precisa"] is False


@pytest.mark.parametrize("dados", [[], None, [{"lat": "x"}], ["texto"]])
def test_resposta_invalida_vira_none(dados):
    assert geocoding.interpretar_resposta(dados) is None


def test_segunda_consulta_sai_do_cache(isolado):
    r1 = asyncio.run(geocoding.geocodificar("Rua Vilebaldo Aguiar, 1000", "Fortaleza, CE"))
    r2 = asyncio.run(geocoding.geocodificar("rua vilebaldo aguiar, 1000", "fortaleza, ce"))
    assert r1 == r2
    assert len(isolado) == 1


def test_falha_de_rede_devolve_none_e_nao_grava(isolado, monkeypatch):
    async def quebrada(endereco, cidade):
        raise OSError("sem rede")

    monkeypatch.setattr(geocoding, "_consultar", quebrada)
    assert asyncio.run(geocoding.geocodificar("Rua X, 1", "Fortaleza, CE")) is None
    assert not geocoding._CACHE_PATH.exists()


def test_desligado_nao_consulta(isolado, monkeypatch):
    monkeypatch.setattr(geocoding, "HABILITADO", False)
    assert asyncio.run(geocoding.geocodificar("Rua X, 1", "Fortaleza, CE")) is None
    assert isolado == []


def test_respeita_intervalo_minimo(isolado, monkeypatch):
    """Política do Nominatim: no máximo 1 requisição por segundo."""
    monkeypatch.setattr(geocoding, "INTERVALO_MINIMO_S", 0.2)
    esperas = []
    original = asyncio.sleep

    async def sleep_registrado(s):
        esperas.append(s)
        await original(0)

    monkeypatch.setattr(geocoding.asyncio, "sleep", sleep_registrado)

    async def duas():
        await geocoding.geocodificar("Rua A, 1", "Fortaleza, CE")
        await geocoding.geocodificar("Rua B, 2", "Fortaleza, CE")

    asyncio.run(duas())
    assert esperas and esperas[-1] > 0
