"""Proxy de fotos (F1.9). Sem rede: cliente HTTP falso.

O que precisa ficar travado é o que impede o endpoint de virar SSRF: só https,
só hosts dos portais, nada de IP, nada de redirecionar para fora, só imagem.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "chave-de-teste")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from services import imagens  # noqa: E402
from services.auth import gerar_token  # noqa: E402

JPG = b"\xff\xd8\xff\xe0falso"
FOTO = "https://resizedimgs.vivareal.com/fit-in/870x653/named.images.sp/abc/foto.jpg"


class Resp:
    def __init__(self, status=200, conteudo=JPG, tipo="image/jpeg", location=None):
        self.status_code, self.content = status, conteudo
        self.headers = {"content-type": tipo}
        if location:
            self.headers["location"] = location


class Cliente:
    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []

    async def get(self, url):
        self.pedidos.append(url)
        return self.respostas.pop(0)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(imagens, "_CACHE_DIR", tmp_path)
    return tmp_path


def usar(monkeypatch, *respostas):
    falso = Cliente(respostas)
    monkeypatch.setattr(imagens, "_cliente", lambda: falso)
    return falso


def pedir(api, url, token=None):
    return api.get("/api/imagem", params={"u": url, "t": gerar_token() if token is None else token})


@pytest.fixture
def api():
    return TestClient(main.app)


@pytest.mark.parametrize("url", [
    "https://resizedimgs.vivareal.com/x.jpg", "https://img.olx.com.br/images/1.jpg",
    "https://http2.mlstatic.com/D_1.jpg", "https://www.quintoandar.com.br/img/med/original1.jpg",
])
def test_hosts_dos_portais_passam(url):
    assert imagens.url_permitida(url)


@pytest.mark.parametrize("url", [
    "http://resizedimgs.vivareal.com/x.jpg",            # sem TLS
    "https://olx.com.br.evil.com/x.jpg",                # sufixo falso
    "https://evilolx.com.br/x.jpg",                     # sem ponto antes do domínio
    "https://127.0.0.1/x.jpg", "https://[::1]/x.jpg",   # IP literal
    "https://169.254.169.254/latest/meta-data",         # metadata de nuvem
    "https://user:senha@img.olx.com.br/x.jpg",          # credencial na URL
    "https://img.olx.com.br:8443/x.jpg",                # porta estranha
    "file:///etc/passwd", "ftp://img.olx.com.br/x.jpg", "nao-e-url",
])
def test_resto_e_barrado(url):
    assert not imagens.url_permitida(url)


def test_serve_imagem_e_guarda_cache(api, cache, monkeypatch):
    falso = usar(monkeypatch, Resp())
    r = pedir(api, FOTO)
    assert r.status_code == 200 and r.content == JPG and r.headers["content-type"] == "image/jpeg"
    assert pedir(api, FOTO).status_code == 200
    assert len(falso.pedidos) == 1                       # segunda veio do cache


def test_sem_token_e_401(api, cache, monkeypatch):
    falso = usar(monkeypatch, Resp())
    assert pedir(api, FOTO, token="").status_code == 401
    assert falso.pedidos == []


def test_host_de_fora_e_400_sem_sair_para_a_rede(api, cache, monkeypatch):
    falso = usar(monkeypatch, Resp())
    assert pedir(api, "https://169.254.169.254/latest/meta-data").status_code == 400
    assert falso.pedidos == []


def test_redirecionamento_para_fora_e_barrado(api, cache, monkeypatch):
    usar(monkeypatch, Resp(status=302, location="https://169.254.169.254/x"))
    assert pedir(api, FOTO).status_code == 502


def test_redirecionamento_dentro_dos_portais_segue(api, cache, monkeypatch):
    falso = usar(monkeypatch, Resp(status=301, location="https://img.vivareal.com/outra.jpg"), Resp())
    assert pedir(api, FOTO).status_code == 200
    assert falso.pedidos[-1] == "https://img.vivareal.com/outra.jpg"


@pytest.mark.parametrize("resp", [
    Resp(status=403, conteudo=b"", tipo="text/html"),
    Resp(tipo="text/html", conteudo=b"<html>bloqueado</html>"),
    Resp(tipo="image/svg+xml", conteudo=b"<svg onload=alert(1)>"),
    Resp(conteudo=b"x" * (imagens.TAMANHO_MAX + 1)),
])
def test_resposta_que_nao_e_foto_segura_nao_passa_nem_entra_no_cache(api, cache, monkeypatch, resp):
    usar(monkeypatch, resp)
    assert pedir(api, FOTO).status_code == 502
    assert not [p for p in cache.rglob("*") if p.is_file()]
