import asyncio
import logging
import os
import random
import statistics
import time
import unicodedata
import uuid
from datetime import datetime

from models import BuscaRequest, BuscaResponse, DiagnosticoColeta, Empreendimento, ResumoBairro
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
from services.validacao import filtrar_anuncios

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("MOCK", "false").lower() == "true"

# Fontes desligadas por padrão, com o motivo medido em 29/07/2026:
#   olx          — bloqueia requisição de servidor (403)
#   mercadolivre — a página só renderiza com JS e o Playwright devolve 0
#   quintoandar  — listagem 100% client-side, sem dados no HTML inicial
#   netimoveis   — portal concentrado em MG; sem inventário fora de lá
# Ligar exige medir antes com a skill `diagnosticar-scraper`.
OLX_HABILITADO = os.getenv("HABILITAR_OLX", "false").lower() == "true"
MERCADOLIVRE_HABILITADO = os.getenv("HABILITAR_MERCADOLIVRE", "false").lower() == "true"
QUINTOANDAR_HABILITADO = os.getenv("HABILITAR_QUINTOANDAR", "false").lower() == "true"
NETIMOVEIS_HABILITADO = os.getenv("HABILITAR_NETIMOVEIS", "false").lower() == "true"

IMOVELWEB_HABILITADO = os.getenv("HABILITAR_IMOVELWEB", "true").lower() == "true"
CHAVESNAMAO_HABILITADO = os.getenv("HABILITAR_CHAVESNAMAO", "true").lower() == "true"
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
        # Gera o preço DENTRO da faixa pedida e deriva a área, para que os dados
        # fictícios passem pela validação de fronteira como um anúncio real passaria.
        preco = round(random.uniform(request.preco_min, request.preco_max), 2)
        preco_m2 = random.uniform(4500, 9000)
        area = round(max(20.0, preco / preco_m2), 2)
        preco_m2 = preco / area
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


def _resumir_por_bairro(
    empreendimentos: list[Empreendimento], bairros_pedidos: list[str]
) -> list[ResumoBairro]:
    """
    Quebra o resultado por bairro pedido, ordenado por preço/m² mediano.

    Só faz sentido com mais de um bairro: com um só, o resumo repetiria o KPI
    principal. Bairros pedidos que não trouxeram nada ficam de fora — a linha
    zerada não informa nada que o total já não diga.
    """
    if len(bairros_pedidos) < 2:
        return []

    resumos = []
    for pedido in bairros_pedidos:
        alvo = _normalizar(pedido)
        do_bairro = [e for e in empreendimentos if e.bairro and alvo in _normalizar(e.bairro)]
        if not do_bairro:
            continue
        precos = sorted(e.preco_m2 for e in do_bairro)
        resumos.append(ResumoBairro(
            bairro=pedido,
            total=len(do_bairro),
            preco_m2_mediana=round(statistics.median(precos), 2),
            preco_m2_medio=round(sum(precos) / len(precos), 2),
            preco_m2_min=precos[0],
            preco_m2_max=precos[-1],
        ))

    resumos.sort(key=lambda r: -r.preco_m2_mediana)
    return resumos


async def executar_busca(request: BuscaRequest, preco_m2_mrv: float | None = None) -> BuscaResponse:
    inicio = time.time()
    contagem_por_portal: dict[str, int] = {}
    fontes_erro: list[str] = []

    if MOCK_MODE:
        logger.info("Modo MOCK ativo")
        raw_todos = _gerar_mock_data(request)
    else:
        cidade, estado = extrair_cidade_estado(request.cidade)
        bairros_pedidos = request.lista_bairros
        # Os demais portais não filtram bairro na origem: mandamos o primeiro
        # só por compatibilidade de assinatura e filtramos tudo em memória.
        bairro = bairros_pedidos[0] if bairros_pedidos else None

        # O VivaReal filtra bairro no PATH e aceita só um por URL — então cada
        # bairro pedido vira uma tarefa própria. É o que faz a proporção de
        # anúncios do bairro certo subir de ~3% para ~85%.
        tarefas_vivareal = [
            ("vivareal", scrape_vivareal(request.cidade, request.preco_min, request.preco_max, request.quartos, b))
            for b in (bairros_pedidos or [None])
        ]

        tarefas_candidatas: list[tuple[str, object]] = [
            *tarefas_vivareal,
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

        # Reordena por prioridade histórica antes de disparar. A ordenação é
        # por PORTAL, mas pode haver várias tarefas do mesmo portal (uma por
        # bairro no VivaReal) — por isso o agrupamento em vez de um dict, que
        # colapsaria as tarefas repetidas.
        por_portal: dict[str, list] = {}
        for nome, coro in tarefas_candidatas:
            por_portal.setdefault(nome, []).append(coro)

        nomes_ordenados = ordenar_fontes_por_prioridade(
            list(por_portal), request.cidade, request.preco_min, request.preco_max, request.quartos
        )
        tarefas = [(nome, coro) for nome in nomes_ordenados for coro in por_portal[nome]]

        resultados = await asyncio.gather(*(t[1] for t in tarefas), return_exceptions=True)

        raw_todos = []
        for (portal, _), resultado in zip(tarefas, resultados):
            if isinstance(resultado, Exception):
                logger.warning(f"Scraper {portal} falhou: {resultado}")
                contagem_por_portal.setdefault(portal, 0)
                if portal not in fontes_erro:
                    fontes_erro.append(portal)
                continue
            n = len(resultado)
            # Soma: um portal pode ter rodado várias vezes (uma por bairro).
            contagem_por_portal[portal] = contagem_por_portal.get(portal, 0) + n
            logger.info(f"Scraper {portal}: {n} resultados")
            raw_todos.extend(resultado)

            # Registra resultado no histórico de fontes
            try:
                registrar_resultado(portal, request.cidade, request.preco_min, request.preco_max, request.quartos, n)
            except Exception as e:
                logger.debug(f"Histórico fontes: erro ao registrar {portal}: {e}")

        logger.info(f"Total bruto: {len(raw_todos)} | Por portal: {contagem_por_portal}")

    total_bruto = len(raw_todos)

    # Validação na fronteira: descarta locação, faixa de área, tipologia
    # divergente e valores implausíveis ANTES que contaminem o KPI.
    raw_todos, descartes = filtrar_anuncios(raw_todos, request)

    # Filtro torre × bloco. Nenhum portal filtra elevador na origem, então é
    # aplicado aqui. A contagem do que saiu vai para o diagnóstico: sem isso o
    # total cai e parece que o mercado encolheu, quando na verdade foi o filtro.
    tipo_filtro = getattr(request, 'tipo_edificacao', None)
    if tipo_filtro:
        antes = len(raw_todos)
        raw_todos = [i for i in raw_todos if i.get('tipo_edificacao') == tipo_filtro]
        removidos = antes - len(raw_todos)
        if removidos:
            descartes['outro_tipo_edificacao'] = descartes.get('outro_tipo_edificacao', 0) + removidos
            logger.info(f"Filtro tipo_edificacao={tipo_filtro}: {antes} → {len(raw_todos)}")

    # Filtro por bairro. Só o VivaReal filtra na origem; o que vem dos demais
    # portais é recortado aqui, contra o campo `bairro` já corrigido.
    bairros_filtro = request.lista_bairros
    if bairros_filtro:
        alvos = [_normalizar(b) for b in bairros_filtro]
        antes_bairro = len(raw_todos)
        raw_todos = [
            item for item in raw_todos
            if item.get('bairro') and any(a in _normalizar(item['bairro']) for a in alvos)
        ]
        fora = antes_bairro - len(raw_todos)
        if fora:
            descartes['fora_dos_bairros'] = descartes.get('fora_dos_bairros', 0) + fora

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

    diagnostico = DiagnosticoColeta(
        total_bruto=total_bruto,
        fontes_ok=sorted(p for p, n in contagem_por_portal.items() if n > 0),
        fontes_zero=sorted(p for p, n in contagem_por_portal.items() if n == 0 and p not in fontes_erro),
        fontes_erro=sorted(fontes_erro),
        descartados_por_motivo=descartes,
    )

    if not empreendimentos:
        return BuscaResponse(
            total=0, preco_m2_medio=0.0, preco_m2_mediana=0.0,
            preco_m2_min=0.0, preco_m2_max=0.0,
            preco_m2_mrv=preco_m2_mrv, empreendimentos=[], tempo_coleta_segundos=tempo,
            diagnostico=diagnostico,
        )

    precos_m2 = sorted(e.preco_m2 for e in empreendimentos)
    return BuscaResponse(
        por_bairro=_resumir_por_bairro(empreendimentos, bairros_filtro),
        total=len(empreendimentos),
        preco_m2_medio=round(sum(precos_m2) / len(precos_m2), 2),
        preco_m2_mediana=round(statistics.median(precos_m2), 2),
        preco_m2_min=precos_m2[0],
        preco_m2_max=precos_m2[-1],
        preco_m2_mrv=preco_m2_mrv,
        empreendimentos=empreendimentos,
        tempo_coleta_segundos=tempo,
        diagnostico=diagnostico,
    )
