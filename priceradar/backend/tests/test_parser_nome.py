"""Nome do empreendimento e fase da obra (scraper/parser.py).

Os casos de "ruído" são textos reais gravados no banco antes da correção: o
regex pegava o nome e continuava pela frase.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.parser import (  # noqa: E402
    completar_empreendimento,
    eh_anuncio_lancamento,
    extrair_nome_do_slug_lancamento,
    extrair_nome_empreendimento,
)


@pytest.mark.parametrize('descricao,esperado', [
    ('Edifício Beach Class Unique localizado Meireles', 'Edifício Beach Class Unique'),
    ('Condomínio Vidal Vasconcelos oferece segurança', 'Condomínio Vidal Vasconcelos'),
    ('Condomínio Reserva Arvoredo 02 Quartos com 02 vagas', 'Condomínio Reserva Arvoredo'),
    ('Residencial Villa Venezia 65 m² | Coração da Messejana', 'Residencial Villa Venezia'),
    ('Edifício Solar das Águas', 'Edifício Solar das Águas'),
])
def test_corta_o_nome_onde_a_frase_continua(descricao, esperado):
    assert extrair_nome_empreendimento(descricao) == esperado


@pytest.mark.parametrize('descricao', [
    'CONDOMÍNIO MAIS ACOLHEDOR DO MEIRELESLocalizado no 12',   # slogan, palavra grudada
    'Condomínio Clube com lazer completo',                     # genérico
    'CONDOMÍNIO FECHADO COM PISCINA',
])
def test_recusa_slogan(descricao):
    assert extrair_nome_empreendimento(descricao) is None


@pytest.mark.parametrize('url,esperado', [
    ('https://www.vivareal.com.br/imoveis-lancamentos/monte-roraima-id-2864813095/', 'Monte Roraima'),
    ('https://www.zapimoveis.com.br/lancamentos/villa-lobos-id-2889406440/', 'Villa Lobos'),
    ('https://www.chavesnamao.com.br/lancamento/lancamento-mood-guararapes/id-45658693/', 'Mood Guararapes'),
    ('https://www.chavesnamao.com.br/lancamento/lancamento-wind-no-meireles-powered-by-porsche-consulting-/id-40162185/', 'Wind'),
    ('https://www.vivareal.com.br/imovel/apartamento-2-quartos-coco-fortaleza-com-garagem-70m2-venda-RS577000-id-2889641816/', None),
    (None, None),
])
def test_nome_pelo_slug_de_lancamento(url, esperado):
    assert extrair_nome_do_slug_lancamento(url) == esperado


@pytest.mark.parametrize('url,texto,esperado', [
    ('https://www.vivareal.com.br/imoveis-lancamentos/monte-roraima-id-1/', '', True),
    ('https://x/imovel/1', 'Apartamento na planta, entrega em 2027', True),
    ('https://x/imovel/1', 'Pronto para morar, reformado', False),
    ('https://x/imovel/1', 'Apartamento 2 quartos', None),   # não diz ≠ usado
])
def test_eh_anuncio_lancamento(url, texto, esperado):
    assert eh_anuncio_lancamento(url, texto) is esperado


def test_completar_nao_usa_o_titulo_como_nome():
    item = {
        'url_anuncio': 'https://www.olx.com.br/x/1', 'nome_anuncio': 'Apartamento 2 quartos no Cocó',
        'nome_empreendimento': 'Apartamento 2 quartos no Cocó', 'descricao': 'Ótimo apartamento',
    }
    completar_empreendimento(item)
    assert item['nome_empreendimento'] is None


def test_completar_extrai_do_titulo_quando_ha_padrao():
    item = {
        'url_anuncio': 'https://www.olx.com.br/x/1', 'nome_anuncio': 'Apto no Condomínio Stay One',
        'nome_empreendimento': None, 'descricao': '',
    }
    completar_empreendimento(item)
    assert item['nome_empreendimento'] == 'Condomínio Stay One'


def test_completar_prefere_o_slug_de_lancamento():
    item = {
        'url_anuncio': 'https://www.zapimoveis.com.br/lancamentos/villa-lobos-id-2889406440/',
        'nome_anuncio': 'Apartamento', 'nome_empreendimento': 'Residencial Outro Nome', 'descricao': '',
    }
    completar_empreendimento(item)
    assert item['nome_empreendimento'] == 'Villa Lobos'
    assert item['eh_lancamento'] is True
