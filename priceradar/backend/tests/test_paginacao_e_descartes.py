"""Paginação em lotes (F4.3) e contagem de tudo o que sai da busca (F4.6).

Sem rede: as páginas são funções falsas que registram quais foram pedidas.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.paginacao import paginar  # noqa: E402
from services.rf_refiner import _filtrar_preco_entrada, refinar_com_random_forest  # noqa: E402


def _anuncios(pagina, n=3):
    return [{"url_anuncio": f"https://portal/imovel/{pagina}-{i}"} for i in range(n)]


def _rodar(inventario: dict[int, list], max_paginas, lote=3):
    pedidas = []

    async def buscar(p):
        pedidas.append(p)
        valor = inventario.get(p, [])
        if isinstance(valor, Exception):
            raise valor
        return valor

    resultado = asyncio.run(paginar(buscar, max_paginas, "Teste", tamanho_lote=lote))
    return resultado, sorted(pedidas)


def test_para_quando_um_lote_inteiro_nao_traz_nada_novo():
    # Inventário acaba na página 4; o teto é 12 (o do ChavesNaMão).
    inventario = {p: _anuncios(p) for p in range(1, 5)}
    resultado, pedidas = _rodar(inventario, 12)
    assert len(resultado) == 12
    assert pedidas == [1, 2, 3, 4, 5, 6, 7, 8, 9]   # lote 7-9 veio vazio → para; 10-12 não saem


def test_pagina_sem_valido_no_meio_nao_interrompe():
    # A página 2 veio toda filtrada (preço/quartos), mas a 4 ainda tem anúncio.
    inventario = {1: _anuncios(1), 2: [], 3: [], 4: _anuncios(4)}
    resultado, _ = _rodar(inventario, 6)
    assert len(resultado) == 6


def test_portal_que_repete_a_pagina_1_depois_do_fim():
    repetida = _anuncios(1)
    inventario = {1: repetida, 2: _anuncios(2), 3: _anuncios(3), 4: repetida, 5: repetida, 6: repetida}
    resultado, pedidas = _rodar(inventario, 9)
    assert len(resultado) == 9
    assert pedidas == [1, 2, 3, 4, 5, 6]


def test_erro_numa_pagina_nao_derruba_as_outras():
    inventario = {1: _anuncios(1), 2: RuntimeError("403"), 3: _anuncios(3)}
    resultado, _ = _rodar(inventario, 3)
    assert len(resultado) == 6


def test_teto_menor_que_o_lote_e_ordem_das_paginas():
    inventario = {1: _anuncios(1, 2), 2: _anuncios(2, 2)}
    resultado, pedidas = _rodar(inventario, 2)
    assert pedidas == [1, 2]
    assert [r["url_anuncio"] for r in resultado][:2] == ["https://portal/imovel/1-0", "https://portal/imovel/1-1"]


def test_sem_url_nao_e_deduplicado():
    inventario = {1: [{"url_anuncio": ""}, {"url_anuncio": ""}]}
    resultado, _ = _rodar(inventario, 1)
    assert len(resultado) == 2


# ── Descartes do refinador entram no diagnóstico ─────────────────────────────

def _item(preco_m2, nome="Apartamento 2 quartos"):
    return {"cidade": "fortaleza", "quartos": 2, "preco_m2": preco_m2, "nome_anuncio": nome}


def test_blindagem_conta_por_motivo():
    itens = [_item(7000), _item(7200), _item(7100), _item(6900), _item(7300),
             _item(2500), _item(18414), _item(7000, "R$ 440.000")]
    motivos: dict[str, int] = {}
    _, removidos = _filtrar_preco_entrada(itens, motivos)
    assert removidos == 3
    assert motivos == {"preco_m2_fora_do_grupo": 2, "titulo_e_preco": 1}


def test_refinador_soma_no_dict_de_descartes():
    itens = [
        {**_item(7000 + i * 10), "preco": 400_000, "area_m2": 60, "portal": "vivareal",
         "banheiros": 2, "vagas": 1}
        for i in range(12)
    ] + [{**_item(2000), "preco": 120_000, "area_m2": 60, "portal": "vivareal", "banheiros": 2, "vagas": 1}]
    descartes = {"tipologia_divergente": 1}
    aprovados = refinar_com_random_forest(itens, descartes=descartes)
    assert descartes["tipologia_divergente"] == 1          # não apaga o que já havia
    assert descartes["preco_m2_fora_do_grupo"] == 1
    assert len(aprovados) + sum(v for k, v in descartes.items() if k != "tipologia_divergente") == len(itens)
