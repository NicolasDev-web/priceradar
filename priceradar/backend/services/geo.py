"""Posiciona no mapa os anúncios que vieram sem coordenada.

VivaReal e Zap publicam a coordenada de cada anúncio. ChavesNaMão e ImovelWeb
não publicam nenhuma — e o ChavesNaMão é a segunda maior fonte, então deixá-lo
fora do mapa esconderia cerca de um terço dos anúncios.

A saída é usar o que a própria busca já coletou: se dez anúncios do Meireles
vieram com coordenada, o centro deles é uma estimativa honesta de "Meireles".
Não é o endereço do imóvel, e a UI diz isso — `origem_coordenada` fica
`centroide_bairro`, o pino é desenhado tracejado e o popup avisa.

Por que não geocodificar: ChavesNaMão e ImovelWeb quase não trazem logradouro,
então um geocoder externo cairia no centro do bairro do mesmo jeito — só que
com uma dependência de rede, limite de requisições e mais um cache para manter.
"""
from __future__ import annotations

import logging

from services.texto import normalizar

logger = logging.getLogger(__name__)

# Um bairro representado por um único anúncio dá um "centro" que é aquele
# anúncio. Com dois já há alguma média. Abaixo disso o pino sugere uma precisão
# que não existe, e é melhor declarar o anúncio como sem localização.
MINIMO_PARA_CENTROIDE = 2


def calcular_centroides(itens: list[dict]) -> dict[str, tuple[float, float]]:
    """Bairro normalizado → (lat, lng) médio dos anúncios que têm coordenada."""
    acumulado: dict[str, list[tuple[float, float]]] = {}
    for item in itens:
        bairro = item.get("bairro")
        lat, lng = item.get("latitude"), item.get("longitude")
        if bairro and lat is not None and lng is not None:
            acumulado.setdefault(normalizar(bairro), []).append((lat, lng))

    return {
        bairro: (sum(p[0] for p in pontos) / len(pontos), sum(p[1] for p in pontos) / len(pontos))
        for bairro, pontos in acumulado.items()
        if len(pontos) >= MINIMO_PARA_CENTROIDE
    }


def aplicar_centroide_bairro(itens: list[dict]) -> int:
    """
    Dá coordenada a quem não tem, usando o centro do próprio bairro.

    Devolve quantos anúncios continuaram sem posição — porque não têm bairro,
    ou porque o bairro deles não tem coordenada real suficiente nesta busca.
    """
    centroides = calcular_centroides(itens)

    posicionados = 0
    sem_posicao = 0
    for item in itens:
        if item.get("latitude") is not None:
            continue
        bairro = item.get("bairro")
        centro = centroides.get(normalizar(bairro)) if bairro else None
        if centro is None:
            sem_posicao += 1
            continue
        item["latitude"], item["longitude"] = centro
        item["origem_coordenada"] = "centroide_bairro"
        posicionados += 1

    if posicionados or sem_posicao:
        logger.info(
            f"Localização: {posicionados} posicionados pelo centro do bairro, "
            f"{sem_posicao} sem posição ({len(centroides)} bairros com centro)"
        )
    return sem_posicao
