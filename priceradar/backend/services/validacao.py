"""Validação na fronteira do pipeline.

Todo anúncio coletado passa por aqui ANTES da deduplicação e do refino.
O objetivo é impedir que dado estruturalmente inválido chegue ao KPI —
não é filtro de qualidade nem de gosto, é contrato de sanidade.

Motivo de existir: os scrapers devolvem dict cru e o schema Pydantic só
é construído no fim do pipeline, validando tipo mas não sanidade. Sem esta
camada, anúncio de aluguel, faixa de área ("38 - 61 m²") e tipologia errada
atravessam tudo e contaminam o preço/m² médio.

Princípio: descartar apenas com evidência clara. Na dúvida, manter — o
refino posterior (rf_refiner) ainda tem chance de pegar o caso.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Limites de sanidade absoluta ─────────────────────────────────────────────
# Não são limites de mercado, são limites do que pode ser um apartamento.
AREA_MIN_M2 = 15.0
AREA_MAX_M2 = 500.0
PRECO_M2_MIN = 1_000.0
PRECO_M2_MAX = 40_000.0

# Abaixo disso, o "preço" é quase certamente valor mensal de aluguel,
# parcela de financiamento ou valor de entrada — não o valor total do imóvel.
PRECO_TOTAL_MINIMO = 20_000.0

# Tolerância na faixa de preço pedida: os portais aplicam o filtro de forma
# aproximada e anúncios na borda são legítimos. 10% evita descarte em excesso.
TOLERANCIA_FAIXA_PRECO = 0.10

# ── Padrões de detecção ──────────────────────────────────────────────────────

# Locação: o anúncio é de aluguel, não de venda.
_RE_LOCACAO = re.compile(r'\b(alugar|aluguel|loca[çc][ãa]o|para\s+alugar)\b', re.IGNORECASE)

# Faixa de área ("38 - 61 m²", "38 a 61 m2"): o anúncio agrega várias plantas
# de um mesmo empreendimento. O preço exibido não corresponde a nenhuma área
# específica, então qualquer preco_m2 calculado é ficção. É a origem dos
# outliers de 14.000–26.000/m² observados na base.
_RE_FAIXA_AREA = re.compile(r'\d+\s*(?:-|a|até)\s*\d+\s*m[²2]', re.IGNORECASE)

# Título que é apenas um valor monetário ("R$ 440.000") — dado inválido do scraper.
_RE_TITULO_SO_PRECO = re.compile(r'^\s*R?\$?\s*[\d.,]+\s*(mil|k|M)?\s*$', re.IGNORECASE)


def validar_anuncio(item: dict, request=None) -> tuple[bool, str | None]:
    """
    Decide se um anúncio pode entrar no pipeline.

    Retorna (True, None) se válido, ou (False, motivo) se deve ser descartado.
    O motivo é uma chave curta e estável, usada para agregar estatística de
    descarte no diagnóstico da busca.
    """
    titulo = str(item.get('nome_anuncio') or '')
    descricao = str(item.get('descricao') or '')
    url = str(item.get('url_anuncio') or '')

    # ── 1. Locação disfarçada de venda ───────────────────────────────────────
    if _RE_LOCACAO.search(titulo) or _RE_LOCACAO.search(url):
        return False, 'locacao'

    preco = _float_ou_none(item.get('preco'))
    if preco is None or preco <= 0:
        return False, 'sem_preco'

    # Valor baixo demais para ser o total de um apartamento — provável
    # aluguel mensal, parcela ou entrada.
    if preco < PRECO_TOTAL_MINIMO:
        return False, 'preco_nao_e_total'

    # ── 2. Faixa de área — preço não corresponde a nenhuma unidade ───────────
    if _RE_FAIXA_AREA.search(titulo) or _RE_FAIXA_AREA.search(descricao[:300]):
        return False, 'faixa_de_area'

    # ── 3. Título inválido produzido pelo scraper ────────────────────────────
    if _RE_TITULO_SO_PRECO.match(titulo):
        return False, 'titulo_invalido'

    # ── 4. Sanidade de área ──────────────────────────────────────────────────
    area = _float_ou_none(item.get('area_m2'))
    if area is None or area <= 0:
        return False, 'sem_area'
    if not (AREA_MIN_M2 <= area <= AREA_MAX_M2):
        return False, 'area_implausivel'

    # ── 5. Sanidade de preço/m² ──────────────────────────────────────────────
    preco_m2 = _float_ou_none(item.get('preco_m2')) or (preco / area)
    if not (PRECO_M2_MIN <= preco_m2 <= PRECO_M2_MAX):
        return False, 'preco_m2_implausivel'

    # ── 6. Coerência com o que foi pedido ────────────────────────────────────
    if request is not None:
        quartos_pedido = getattr(request, 'quartos', None)
        quartos_item = item.get('quartos')
        # Só descarta quando o anúncio declara a tipologia e ela diverge.
        # Anúncio sem quartos informado segue para imputação no rf_refiner.
        if quartos_pedido and quartos_item is not None and int(quartos_item) != int(quartos_pedido):
            return False, 'tipologia_divergente'

        preco_min = getattr(request, 'preco_min', None)
        preco_max = getattr(request, 'preco_max', None)
        if preco_min and preco < preco_min * (1 - TOLERANCIA_FAIXA_PRECO):
            return False, 'fora_da_faixa_preco'
        if preco_max and preco > preco_max * (1 + TOLERANCIA_FAIXA_PRECO):
            return False, 'fora_da_faixa_preco'

    return True, None


def filtrar_anuncios(itens: list[dict], request=None) -> tuple[list[dict], dict[str, int]]:
    """
    Aplica validar_anuncio a uma lista e devolve (válidos, contagem por motivo).

    A contagem alimenta o diagnóstico devolvido pela API — descarte silencioso
    é o que fez o problema passar despercebido até agora.
    """
    validos: list[dict] = []
    descartes: dict[str, int] = {}

    for item in itens:
        ok, motivo = validar_anuncio(item, request)
        if ok:
            validos.append(item)
        else:
            descartes[motivo] = descartes.get(motivo, 0) + 1
            logger.debug(
                f"Descartado [{motivo}]: {item.get('nome_anuncio')} "
                f"preco={item.get('preco')} area={item.get('area_m2')} "
                f"preco_m2={item.get('preco_m2')}"
            )

    if descartes:
        resumo = ', '.join(f'{m}={n}' for m, n in sorted(descartes.items(), key=lambda x: -x[1]))
        logger.info(f"Validação: {len(itens)} → {len(validos)} válidos ({resumo})")

    return validos, descartes


def _float_ou_none(valor) -> float | None:
    try:
        if valor is None:
            return None
        return float(valor)
    except (TypeError, ValueError):
        return None
