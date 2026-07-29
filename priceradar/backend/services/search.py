import asyncio
import logging
import os
import random
import time
import unicodedata
import uuid
from datetime import datetime

from models import BuscaRequest, BuscaResponse, Empreendimento
from scraper.ciento23imoveis import scrape_123imoveis
from scraper.chavesnamao import scrape_chavesnamao
from scraper.imovelweb import scrape_imovelweb
from scraper.mercadolivre import scrape_mercadolivre
from scraper.netimoveisagent import scrape_netimoveis
from scraper.olximoveis import scrape_olximoveis
from scraper.quintoandar import scrape_quintoandar
from scraper.vivareal import scrape_vivareal
from scraper.zapimoveis import scrape_zapimoveis
from services.deduplicador import deduplicar_cross_portal
from services.historico_fontes import ordenar_fontes_por_prioridade, registrar_resultado
from services.rf_refiner import refinar_com_random_forest

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("MOCK", "false").lower() == "true"
OLX_HABILITADO = os.getenv("HABILITAR_OLX", "true").lower() == "true"
MERCADOLIVRE_HABILITADO = os.getenv("HABILITAR_MERCADOLIVRE", "true").lower() == "true"
IMOVELWEB_HABILITADO = os.getenv("HABILITAR_IMOVELWEB", "true").lower() == "true"
CHAVESNAMAO_HABILITADO = os.getenv("HABILITAR_CHAVESNAMAO", "true").lower() == "true"
QUINTOANDAR_HABILITADO = os.getenv("HABILITAR_QUINTOANDAR", "true").lower() == "true"
NETIMOVEIS_HABILITADO = os.getenv("HABILITAR_NETIMOVEIS", "true").lower() == "true"
CIENTO23_HABILITADO = os.getenv("HABILITAR_123IMOVEIS", "true").lower() == "true"
RF_REFINER_HABILITADO = os.getenv("HABILITAR_RF_REFINER", "true").lower() == "true"
DEDUP_CROSS_PORTAL_HABILITADO = os.getenv("HABILITAR_DEDUP_CROSS_PORTAL", "true").lower() == "true"


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def extrair_cidade_estado(cidade_str: str) -> tuple[str, str]:
    partes = cidade_str.strip().split(',')
    cidade = _normalizar(partes[0]).replace(' ', '-')
    estado = _normalizar(partes[1]).strip() if len(partes) > 1 else 'sp'
    return cidade, estado


def calcular_variacao_mrv(preco_m2: float, preco_m2_mrv: float | None) -> float | None:
    if preco_m2_mrv is None or preco_m2_mrv == 0:
        return None
    return round(((preco_m2 - preco_m2_mrv) / preco_m2_mrv) * 100, 1)


def _gerar_mock_data(request: BuscaRequest) -> list[dict]:
    cidade = request.cidade.split(',')[0].strip()
    nomes = [
        "Residencial Vista Bela", "Parque das Flores", "Edifício Central Park",
        "Condomínio Sol Nascente", "Jardins do Vale", "Torre Horizon",
        "Vivace Residence", "Gran Club", "Alpha Premium", "Morada Nova",
        "Portal do Sol", "Reserva Verde",
    ]
    construtoras = ["MRV", "Cyrela", "Direcional", "Tenda", "Even", "Tegra"]
    bairros = ["Centro", "Bela Vista", "Boa Viagem", "Meireles", "Pituba", "Pinheiros"]
    portais = ["vivareal", "zapimoveis", "olx"]
    resultado = []
    for i in range(12):
        quartos = request.quartos or random.choice([1, 2, 3])
        # Gera preco_m2 diretamente em range realista para não disparar o filtro de outliers
        preco_m2 = random.uniform(4500, 9000)
        area = round(random.uniform(50, 100), 2)
        preco = round(preco_m2 * area, 2)
        resultado.append({
            'id': str(uuid.uuid4()),
            'nome_anuncio': nomes[i % len(nomes)],
            'nome_empreendimento': nomes[i % len(nomes)],
            'construtora': construtoras[i % len(construtoras)],
            'cidade': _normalizar(cidade),
            'bairro': bairros[i % len(bairros)],
            'portal': portais[i % len(portais)],
            'preco': preco,
            'area_m2': area,
            'preco_m2': round(preco_m2, 2),
            'quartos': quartos,
            'banheiros': max(1, quartos - 1),
            'vagas': random.choice([0, 1, 2]),
            'descricao': f"Apartamento de {quartos} quartos em {bairros[i % len(bairros)]}.",
            'url_anuncio': f'https://www.vivareal.com.br/imovel/{i + 1}/',
            'data_coleta': datetime.now(),
        })
    return resultado


async def executar_busca(request: BuscaRequest, preco_m2_mrv: float | None = None) -> BuscaResponse:
    inicio = time.time()

    if MOCK_MODE:
        logger.info("Modo MOCK ativo")
        raw_todos = _gerar_mock_data(request)
    else:
        cidade, estado = extrair_cidade_estado(request.cidade)
        bairro = getattr(request, 'bairro', None)

        # Monta todas as tarefas de scraping habilitadas
        tarefas_candidatas: list[tuple[str, object]] = [
            ("vivareal", scrape_vivareal(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro)),
            ("zapimoveis", scrape_zapimoveis(cidade, estado, request.preco_min, request.preco_max, request.quartos, bairro)),
        ]
        if MERCADOLIVRE_HABILITADO:
            tarefas_candidatas.append(
                ("mercadolivre", scrape_mercadolivre(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )
        if IMOVELWEB_HABILITADO:
            tarefas_candidatas.append(
                ("imovelweb", scrape_imovelweb(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )
        if NETIMOVEIS_HABILITADO:
            tarefas_candidatas.append(
                ("netimoveis", scrape_netimoveis(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )
        if CHAVESNAMAO_HABILITADO:
            tarefas_candidatas.append(
                ("chavesnamao", scrape_chavesnamao(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )
        if QUINTOANDAR_HABILITADO:
            tarefas_candidatas.append(
                ("quintoandar", scrape_quintoandar(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )
        if OLX_HABILITADO:
            tarefas_candidatas.append(
                ("olx", scrape_olximoveis(cidade, estado, request.preco_min, request.preco_max, request.quartos))
            )
        if CIENTO23_HABILITADO:
            tarefas_candidatas.append(
                ("123imoveis", scrape_123imoveis(request.cidade, request.preco_min, request.preco_max, request.quartos, bairro))
            )

        # Reordena as tarefas por prioridade histórica (RF) antes de disparar
        nomes = [t[0] for t in tarefas_candidatas]
        nomes_ordenados = ordenar_fontes_por_prioridade(nomes, request.cidade, request.preco_min, request.preco_max, request.quartos)
        mapa = {nome: coroutine for nome, coroutine in tarefas_candidatas}
        tarefas = [(nome, mapa[nome]) for nome in nomes_ordenados]

        resultados = await asyncio.gather(*(t[1] for t in tarefas), return_exceptions=True)

        raw_todos = []
        contagem_por_portal: dict[str, int] = {}
        for (portal, _), resultado in zip(tarefas, resultados):
            if isinstance(resultado, Exception):
                logger.warning(f"Scraper {portal} falhou: {resultado}")
                contagem_por_portal[portal] = 0
                continue
            n = len(resultado)
            contagem_por_portal[portal] = n
            logger.info(f"Scraper {portal}: {n} resultados")
            raw_todos.extend(resultado)

            # Registra resultado no histórico de fontes
            try:
                registrar_resultado(portal, request.cidade, request.preco_min, request.preco_max, request.quartos, n)
            except Exception as e:
                logger.debug(f"Histórico fontes: erro ao registrar {portal}: {e}")

        logger.info(f"Total bruto: {len(raw_todos)} | Por portal: {contagem_por_portal}")

    # Filtro por bairro
    bairro_filtro = getattr(request, 'bairro', None)
    if bairro_filtro:
        bairro_norm = _normalizar(bairro_filtro)
        raw_todos = [
            item for item in raw_todos
            if item.get('bairro') and bairro_norm in _normalizar(item['bairro'])
        ]

    # Deduplicação por URL (remoção de duplicatas do mesmo portal/URL)
    vistos: set[str] = set()
    raw_unicos_url = []
    for item in raw_todos:
        chave = item.get('url_anuncio', '').split('?')[0]
        if chave and chave not in vistos:
            vistos.add(chave)
            raw_unicos_url.append(item)
        elif not chave:
            raw_unicos_url.append(item)

    # Deduplicação cross-portal via RF (Agente 2)
    if DEDUP_CROSS_PORTAL_HABILITADO and len(raw_unicos_url) > 1:
        total_antes = len(raw_unicos_url)
        raw_unicos = deduplicar_cross_portal(raw_unicos_url)
        logger.info(f"Dedup cross-portal: {total_antes} → {len(raw_unicos)}")
    else:
        raw_unicos = raw_unicos_url

    # Enriquece com variação MRV
    for item in raw_unicos:
        item['preco_m2_mrv'] = preco_m2_mrv
        item['variacao_mrv_pct'] = calcular_variacao_mrv(item['preco_m2'], preco_m2_mrv)

    # Refinamento RF: imputação + remoção de outliers (Agente 3)
    if RF_REFINER_HABILITADO and raw_unicos:
        raw_unicos = refinar_com_random_forest(raw_unicos)

    # Construir Empreendimentos
    empreendimentos: list[Empreendimento] = []
    for item in raw_unicos:
        try:
            empreendimentos.append(Empreendimento(**item))
        except Exception as e:
            logger.warning(f"Erro ao construir Empreendimento: {e}")

    empreendimentos.sort(key=lambda e: e.preco_m2)
    tempo = round(time.time() - inicio, 2)

    if not empreendimentos:
        return BuscaResponse(
            total=0, preco_m2_medio=0.0, preco_m2_min=0.0, preco_m2_max=0.0,
            preco_m2_mrv=preco_m2_mrv, empreendimentos=[], tempo_coleta_segundos=tempo,
        )

    precos_m2 = [e.preco_m2 for e in empreendimentos]
    return BuscaResponse(
        total=len(empreendimentos),
        preco_m2_medio=round(sum(precos_m2) / len(precos_m2), 2),
        preco_m2_min=min(precos_m2),
        preco_m2_max=max(precos_m2),
        preco_m2_mrv=preco_m2_mrv,
        empreendimentos=empreendimentos,
        tempo_coleta_segundos=tempo,
    )
