"""Testes do proxy de tiles do mapa.

Sem rede: o cliente HTTP é substituído por um falso que registra as chamadas.
O que importa travar:
- coordenada fora da grade nunca vira requisição para fora;
- sem chave, 503 (é o sinal para o mapa cair no provedor sem chave);
- o cache evita a segunda ida à CARTO;
- resposta que não é imagem não entra no cache.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from services import tiles  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfalso"


class RespostaFalsa:
    def __init__(self, status=200, conteudo=PNG, tipo="image/png"):
        self.status_code = status
        self.content = conteudo
        self.headers = {"content-type": tipo}


class ClienteFalso:
    def __init__(self, resposta=None):
        self.resposta = resposta or RespostaFalsa()
        self.chamadas = []

    async def get(self, url, params=None):
        self.chamadas.append((url, params))
        return self.resposta


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles, "_CACHE_DIR", tmp_path)
    monkeypatch.setenv("CARTO_API_KEY", "chave-carto")
    falso = ClienteFalso()
    monkeypatch.setattr(tiles, "_cliente", lambda: falso)
    return falso


@pytest.fixture
def api():
    return TestClient(main.app)


def url(z=3, x=4, y=3, r=""):
    return f"/api/tiles/{z}/{x}/{y}.png?r={r}"


def test_serve_tile_e_repassa_chave(api, cliente_http):
    resp = api.get(url())
    assert resp.status_code == 200
    assert resp.content == PNG
    assert resp.headers["content-type"] == "image/png"
    [(chamada, params)] = cliente_http.chamadas
    assert chamada.endswith("/dark_all/3/4/3.png")
    assert params == {"key": "chave-carto"}


def test_retina_pede_tile_2x(api, cliente_http):
    assert api.get(url(r="@2x")).status_code == 200
    assert cliente_http.chamadas[0][0].endswith("/3/4/3@2x.png")


def test_segunda_vez_sai_do_cache(api, cliente_http):
    api.get(url())
    api.get(url())
    assert len(cliente_http.chamadas) == 1


@pytest.mark.parametrize("z,x,y", [(21, 0, 0), (3, 8, 0), (3, 0, 8), (2, -1, 0)])
def test_coordenada_fora_da_grade_nao_sai_para_a_rede(api, cliente_http, z, x, y):
    assert api.get(url(z, x, y)).status_code in (400, 404, 422)
    assert cliente_http.chamadas == []


def test_sem_chave_responde_503(api, cliente_http, monkeypatch):
    monkeypatch.delenv("CARTO_API_KEY")
    assert api.get(url()).status_code == 503
    assert cliente_http.chamadas == []


def test_resposta_que_nao_e_imagem_nao_entra_no_cache(api, cliente_http, tmp_path):
    cliente_http.resposta = RespostaFalsa(status=401, conteudo=b"{}", tipo="application/json")
    assert api.get(url()).status_code == 503
    assert not list(tmp_path.rglob("*.png"))
