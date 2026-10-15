"""Agrupamento de anúncios por empreendimento (services/agrupamento.py).

Os casos vêm do banco local (15/10/2026): o prédio da Rua Vilebaldo Aguiar com
vários anúncios na mesma coordenada, a mesma coordenada com bairros diferentes,
a mesma unidade anunciada duas vezes no VivaReal, e os condomínios da OLX que
só o nome identifica.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import BuscaResponse, Empreendimento  # noqa: E402
from services.agrupamento import (  # noqa: E402
    agrupar,
    chave_grupo,
    colapsar_unidades,
    distancia_m,
    mediana_por_empreendimento,
    normalizar_nome,
    normalizar_rua,
)
from services.search import aplicar_agrupamento  # noqa: E402

_seq = iter(range(10_000))


def anuncio(
    preco=800_000, area=100, quartos=2, *, lat=None, lng=None, origem='exata', endereco=None,
    nome=None, bairro='Cocó', portal='vivareal', cidade='fortaleza', url=None,
):
    n = next(_seq)
    return {
        'id': str(n), 'url_anuncio': url or f'https://x/{n}', 'nome_anuncio': f'Apto {n}',
        'nome_empreendimento': nome, 'cidade': cidade, 'bairro': bairro, 'endereco': endereco,
        'latitude': lat, 'longitude': lng, 'origem_coordenada': origem if lat is not None else None,
        'portal': portal, 'preco': float(preco), 'area_m2': float(area),
        'preco_m2': round(preco / area, 2), 'quartos': quartos,
    }


# ── Normalização ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('entrada,esperado', [
    ('Rua Vilebaldo Aguiar, 1000', ('rua vilebaldo aguiar', '1000')),
    ('R. Vilebaldo Aguiar, nº 1000 - Cocó', ('rua vilebaldo aguiar', '1000')),
    ('Av. da Universidade, 2853', ('avenida universidade', '2853')),
    ('Avenida Universidade', ('avenida universidade', None)),
    ('Rua Dr. José Lourenço, 870', ('rua doutor jose lourenco', '870')),
    ('Rua 25 de Março', ('rua 25 marco', None)),        # número no nome não é porta
    ('Rua Andrade Furtado 1100', ('rua andrade furtado', '1100')),
    ('Rua X, S/N', ('rua x', None)),
    ('Rua X, 0', ('rua x', None)),
    ('', (None, None)),
    (None, (None, None)),
])
def test_normalizar_rua(entrada, esperado):
    assert normalizar_rua(entrada) == esperado


@pytest.mark.parametrize('entrada,esperado', [
    ('Edifício Beach Class Unique', 'beach class unique'),
    ('Residencial Villa Roma', 'villa roma'),
    ('Cond. Atlântico Sul', 'atlantico sul'),
    ('Condomínio Parque', None),                       # nada distintivo
    ('Edifício Sol', None),                            # 3 letras não bastam
    ('Apartamento 2 quartos à venda no Cocó', 'coco'),  # título: só sobra o bairro
    (None, None),
])
def test_normalizar_nome(entrada, esperado):
    assert normalizar_nome(entrada) == esperado


def test_distancia_m_aproximada():
    # 0,001° de latitude ≈ 111 m
    assert distancia_m(-3.746, -38.471, -3.747, -38.471) == pytest.approx(111, abs=2)


# ── R2: coordenada exata ─────────────────────────────────────────────────────

def test_mesma_coordenada_e_mesma_rua_agrupa():
    """O prédio da Vilebaldo Aguiar: várias unidades no mesmo ponto."""
    itens = [
        anuncio(990_000, 100, 2, lat=-3.7461, lng=-38.4710, endereco='Rua Vilebaldo Aguiar'),
        anuncio(780_000, 80, 2, lat=-3.7461, lng=-38.4710, endereco='Rua Vilebaldo Aguiar'),
        anuncio(860_000, 100, 3, lat=-3.74612, lng=-38.47101, endereco='Rua Vilebaldo Aguiar'),
    ]
    grupos = agrupar(itens)
    assert len(grupos) == 1
    assert grupos[0]['n_anuncios'] == 3
    assert grupos[0]['confianca'] == 'alta'
    assert grupos[0]['sinais'] == ['coordenada']
    assert len({i['grupo_id'] for i in itens}) == 1


def test_bairro_divergente_na_mesma_coordenada_ainda_agrupa():
    """Benfica × Fátima no mesmo ponto da Av. dos Expedicionários: bairro não é condição."""
    itens = [
        anuncio(670_000, 67, 3, lat=-3.7479, lng=-38.5364, endereco='Avenida dos Expedicionários', bairro='Benfica'),
        anuncio(700_000, 67, 3, lat=-3.7479, lng=-38.5364, endereco='Avenida dos Expedicionários', bairro='Fátima'),
    ]
    assert len(agrupar(itens)) == 1


def test_coordenadas_distantes_nao_agrupam():
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A'),
        anuncio(lat=-3.7470, lng=-38.4710, endereco='Rua A'),  # ~100 m
    ]
    assert agrupar(itens) == []
    assert all(i['grupo_id'] is None for i in itens)


def test_coordenada_de_centroide_nao_agrupa():
    """Centro do bairro não é endereço: juntaria o bairro inteiro num prédio."""
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, origem='centroide_bairro'),
        anuncio(lat=-3.7461, lng=-38.4710, origem='centroide_bairro'),
    ]
    assert agrupar(itens) == []


def test_mesmo_ponto_ruas_diferentes_nao_agrupa():
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A'),
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua B'),
    ]
    assert agrupar(itens) == []


def test_mesmo_ponto_com_preco_m2_muito_diferente_nao_agrupa():
    """Centro da rua geocodificado: R$ 3.200 e R$ 7.000/m² não são o mesmo prédio."""
    itens = [
        anuncio(440_000, 138, lat=-3.75, lng=-38.53, endereco='Rua Graciliano Ramos'),
        anuncio(450_000, 138, lat=-3.75, lng=-38.53, endereco='Rua Graciliano Ramos'),
        anuncio(450_000, 61, lat=-3.75, lng=-38.53, endereco='Rua Graciliano Ramos'),
        anuncio(425_000, 66, lat=-3.75, lng=-38.53, endereco='Rua Graciliano Ramos'),
    ]
    grupos = agrupar(itens)
    assert sorted(g['n_anuncios'] for g in grupos) == [2, 2]


# ── R1: endereço com número ──────────────────────────────────────────────────

def test_mesmo_endereco_com_numero_agrupa_sem_coordenada():
    itens = [
        anuncio(endereco='Rua Andrade Furtado, 1100', portal='vivareal'),
        anuncio(endereco='R. Andrade Furtado, 1100', portal='chavesnamao'),
    ]
    grupos = agrupar(itens)
    assert len(grupos) == 1
    assert grupos[0]['sinais'] == ['endereco']
    assert grupos[0]['chave'] == 'end:fortaleza|rua andrade furtado|1100'


def test_mesma_rua_numeros_diferentes_nao_agrupa_nem_pela_coordenada():
    """Vizinhos geocodificados no mesmo ponto: o número desempata."""
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A, 100'),
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A, 120'),
    ]
    assert agrupar(itens) == []


def test_rua_sem_numero_sozinha_nao_agrupa():
    """Uma avenida tem dezenas de prédios."""
    itens = [anuncio(endereco='Avenida Santos Dumont'), anuncio(endereco='Avenida Santos Dumont')]
    assert agrupar(itens) == []


# ── R3: nome ─────────────────────────────────────────────────────────────────

def test_mesmo_nome_no_mesmo_bairro_agrupa_sem_endereco():
    """OLX: sem rua nem coordenada, o nome é o único sinal."""
    itens = [
        anuncio(270_000, 46, nome='Condomínio Reserva Árvoredo', bairro='Barroso', portal='olx'),
        anuncio(287_000, 50, nome='condomínio Reserva Arvoredo', bairro='Barroso', portal='olx'),
        anuncio(280_000, 46, nome='Residencial Reserva Arvoredo', bairro='Barroso', portal='olx'),
    ]
    grupos = agrupar(itens)
    assert len(grupos) == 1
    assert grupos[0]['confianca'] == 'media'
    assert grupos[0]['nome'] in ('Condomínio Reserva Árvoredo', 'condomínio Reserva Arvoredo', 'Residencial Reserva Arvoredo')


def test_mesmo_nome_em_bairros_diferentes_nao_agrupa():
    itens = [
        anuncio(nome='Residencial Villa Roma', bairro='Messejana', portal='olx'),
        anuncio(nome='Residencial Villa Roma', bairro='Aldeota', portal='olx'),
    ]
    assert agrupar(itens) == []


def test_nome_generico_nao_agrupa():
    itens = [
        anuncio(nome='Condomínio Parque', bairro='Cocó', portal='olx'),
        anuncio(nome='Condomínio Parque', bairro='Cocó', portal='olx'),
    ]
    assert agrupar(itens) == []


def test_nomes_diferentes_no_mesmo_ponto_nao_agrupam():
    """Trava de conflito: dois prédios nomeados que caíram na mesma coordenada."""
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A', nome='Edifício Goya'),
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A', nome='Edifício Ilha Verde'),
    ]
    assert agrupar(itens) == []


def test_nome_liga_anuncio_sem_coordenada_ao_grupo_da_coordenada():
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A', nome='Edifício Beach Class'),
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A'),
        anuncio(nome='Edifício Beach Class', bairro='Cocó', portal='olx'),
    ]
    grupos = agrupar(itens)
    assert len(grupos) == 1
    assert grupos[0]['n_anuncios'] == 3
    assert set(grupos[0]['sinais']) == {'coordenada', 'nome'}


# ── Estatística ──────────────────────────────────────────────────────────────

def test_mesma_unidade_duas_vezes_conta_uma_vez():
    """VivaReal: 100 m², R$ 670 mil, dois corretores — uma unidade só."""
    itens = [
        anuncio(670_000, 100, 3, lat=-3.7481, lng=-38.5241, endereco='Avenida Aguanambi'),
        anuncio(670_000, 100, 3, lat=-3.7481, lng=-38.5241, endereco='Avenida Aguanambi'),
        anuncio(800_000, 100, 3, lat=-3.7481, lng=-38.5241, endereco='Avenida Aguanambi'),
    ]
    grupo = agrupar(itens)[0]
    assert grupo['n_anuncios'] == 3
    assert grupo['n_unidades'] == 2
    # Mediana sobre as 2 unidades (6.700 e 8.000), não sobre os 3 anúncios.
    assert grupo['preco_m2_mediana'] == pytest.approx(7_350)


def test_colapsar_unidades_respeita_quartos():
    a = anuncio(500_000, 60, 2)
    b = anuncio(500_000, 60, 3)
    assert len(colapsar_unidades([a, b])) == 2


def test_grupo_id_estavel_entre_execucoes():
    def montar():
        return [
            anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua Vilebaldo Aguiar'),
            anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua Vilebaldo Aguiar'),
        ]
    assert agrupar(montar())[0]['grupo_id'] == agrupar(montar())[0]['grupo_id']


def test_chave_prefere_endereco_com_numero():
    itens = [anuncio(endereco='Rua A, 10', nome='Edifício Goya'), anuncio(endereco='Rua A')]
    assert chave_grupo('fortaleza', itens) == 'end:fortaleza|rua a|10'


def test_lancamento_basta_um_anuncio_dizer():
    itens = [anuncio(endereco='Rua A, 10'), anuncio(endereco='Rua A, 10')]
    itens[0]['eh_lancamento'] = True
    itens[1]['eh_lancamento'] = None
    assert agrupar(itens)[0]['eh_lancamento'] is True


def test_mediana_por_empreendimento_conta_cada_predio_uma_vez():
    # Um prédio caro com 5 anúncios e 4 anúncios baratos soltos.
    predio = [anuncio(1_000_000, 100, lat=-3.7, lng=-38.5, endereco='Rua A') for _ in range(5)]
    soltos = [anuncio(500_000, 100, bairro=f'B{i}', portal='olx') for i in range(4)]
    itens = predio + soltos
    grupos = agrupar(itens)
    # Por anúncio: mediana de [5000×4, 10000×5] = 10000. Por prédio: [5000×4, 10000] = 5000.
    assert mediana_por_empreendimento(itens, grupos) == 5_000


# ── Integração com a resposta da busca ───────────────────────────────────────

def test_aplicar_agrupamento_preenche_resposta():
    itens = [
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A'),
        anuncio(lat=-3.7461, lng=-38.4710, endereco='Rua A'),
        anuncio(bairro='Centro', portal='olx'),
    ]
    from datetime import datetime
    emps = [
        Empreendimento(**{**i, 'construtora': None, 'banheiros': None, 'vagas': None,
                          'descricao': None, 'data_coleta': datetime(2026, 10, 15)})
        for i in itens
    ]
    resp = BuscaResponse(
        total=3, preco_m2_medio=8000, preco_m2_min=8000, preco_m2_max=8000,
        empreendimentos=emps, tempo_coleta_segundos=0,
    )
    aplicar_agrupamento(resp)
    assert len(resp.grupos) == 1
    assert resp.empreendimentos[0].grupo_id == resp.grupos[0].grupo_id
    assert resp.empreendimentos[2].grupo_id is None
    assert resp.preco_m2_mediana_por_empreendimento == 8000


def test_cache_com_titulo_gravado_como_nome_nao_agrupa():
    """Linhas antigas: o título inteiro gravado como nome. Agrupar por ele
    juntava o bairro todo ("… - Meireles - Fortaleza/CE")."""
    from datetime import datetime
    titulos = [
        'Apartamento com 3 dormitórios à venda, 188 m² por R$ 990.000,00 - Meireles - Fortaleza/CE',
        'Apartamento com 2 dormitórios à venda, 70 m² por R$ 600.000,00 - Meireles - Fortaleza/CE',
    ]
    emps = [
        Empreendimento(**{**anuncio(bairro='Meireles', portal='olx'), 'nome_anuncio': t,
                          'nome_empreendimento': t, 'construtora': None, 'banheiros': None,
                          'vagas': None, 'descricao': None, 'data_coleta': datetime(2026, 10, 1)})
        for t in titulos
    ]
    resp = BuscaResponse(total=2, preco_m2_medio=1, preco_m2_min=1, preco_m2_max=1,
                         empreendimentos=emps, tempo_coleta_segundos=0)
    aplicar_agrupamento(resp)
    assert resp.grupos == []
    assert all(e.nome_empreendimento is None for e in resp.empreendimentos)


def test_nome_longo_demais_e_frase():
    assert normalizar_nome('Edifício Alfa Beta Gama Delta Épsilon Zeta') is None
