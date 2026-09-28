"""Evolução do preço/m² por bairro ao longo das semanas.

Parte das observações já deduplicadas por `observacoes_por_periodo` (um anúncio
por semana) e agrupa em Python — o SQLite não tem MEDIAN, e o volume de linhas
de uma cidade é pequeno o bastante para isso não pesar.
"""
import statistics
from collections import Counter

from services.texto import normalizar

# Abaixo disso a média de um bairro numa semana é quase anedota: um anúncio
# caro vira "o bairro subiu 20%". O ponto sai, mas marcado como pouco confiável.
MIN_AMOSTRA_PONTO = 3

# Quantos bairros o gráfico mostra quando a busca não escolheu nenhum. Mais que
# isso vira um novelo de linhas ilegível.
MAX_BAIRROS_PADRAO = 6


def ler_lista_bairros(valores: list[str] | None) -> list[str]:
    """
    Bairros pedidos na query string. Aceita os dois formatos que um cliente
    manda com naturalidade: `bairros=Aldeota,Meireles` e
    `bairros=Aldeota&bairros=Meireles` (ou os dois misturados). Nome de bairro
    não tem vírgula, então ela é um separador seguro.
    """
    saida: list[str] = []
    vistos: set[str] = set()
    for valor in valores or []:
        for parte in valor.split(","):
            nome = parte.strip()
            chave = normalizar(nome)
            if chave and chave not in vistos:
                vistos.add(chave)
                saida.append(nome)
    return saida


def _ponto(semana: str, precos: list[float]) -> dict:
    return {
        "semana": semana,
        # Média é a métrica principal — a mesma dos cards e do Excel, para o
        # gráfico não contradizer o número que o usuário já viu na tela.
        "preco_m2_medio": round(sum(precos) / len(precos), 2),
        "preco_m2_mediana": round(statistics.median(precos), 2),
        "n": len(precos),
        "pouco_confiavel": len(precos) < MIN_AMOSTRA_PONTO,
    }


def serie_por_bairro(
    observacoes: list[dict],
    bairros: list[str] | None = None,
    limite: int = MAX_BAIRROS_PADRAO,
) -> dict:
    """
    Agrupa as observações por bairro normalizado e semana.

    - `bairros` informado: devolve exatamente esses, na ordem de volume; um
      bairro sem nenhum anúncio no histórico volta com série vazia, para a
      tela dizer "sem dados" em vez de sumir com ele calado.
    - Sem `bairros`: os `limite` de maior volume.

    Volume = anúncios distintos (URL) no histórico todo, não soma de pontos: um
    anúncio parado no ar por 10 semanas não deve valer mais que 10 anúncios.
    Anúncio sem bairro fica fora (continua valendo na série da cidade).
    """
    grafias: dict[str, Counter] = {}
    precos: dict[str, dict[str, list[float]]] = {}
    urls: dict[str, set[str]] = {}
    semanas: set[str] = set()

    for o in observacoes:
        nome = (o.get("bairro") or "").strip()
        chave = normalizar(nome)
        if not chave:
            continue
        semanas.add(o["semana"])
        grafias.setdefault(chave, Counter())[nome] += 1
        precos.setdefault(chave, {}).setdefault(o["semana"], []).append(o["preco_m2"])
        urls.setdefault(chave, set()).add(o["url"])

    def exibicao(chave: str) -> str:
        # Nome mais frequente; empate vai para o que tem acento/maiúscula
        # ("Aldeota" antes de "aldeota"), que é o que o usuário espera ler.
        return max(grafias[chave].items(), key=lambda kv: (kv[1], kv[0] != normalizar(kv[0]), kv[0]))[0]

    disponiveis = sorted(urls, key=lambda c: (-len(urls[c]), exibicao(c)))

    pedidos: dict[str, str] = {}
    if bairros:
        pedidos = {normalizar(b): b.strip() for b in bairros if normalizar(b)}
        escolhidos = sorted(pedidos, key=lambda c: (-len(urls.get(c, ())), c))
    else:
        escolhidos = disponiveis[:max(limite, 0)]

    return {
        "min_amostra": MIN_AMOSTRA_PONTO,
        "periodos": sorted(semanas),
        "disponiveis": [{"bairro": exibicao(c), "total": len(urls[c])} for c in disponiveis],
        "bairros": [
            {
                "bairro": exibicao(c) if c in grafias else pedidos[c],
                "total": len(urls.get(c, ())),
                "serie": [_ponto(s, v) for s, v in sorted(precos.get(c, {}).items())],
            }
            for c in escolhidos
        ],
    }
