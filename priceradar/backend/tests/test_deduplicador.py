"""Testes da deduplicação cross-portal.

A versão anterior removia 70% dos anúncios (109 → 33 medido numa busca real),
tratando como duplicata qualquer par com preço e área parecidos. Numa busca já
filtrada por cidade, tipologia e faixa de preço, isso descreve dezenas de
apartamentos distintos.

Os testes travam os dois modos de falha: fundir demais e fundir de menos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.deduplicador import deduplicar_cross_portal  # noqa: E402


def anuncio(portal, preco, area, bairro, nome="Apartamento 2 quartos", quartos=2):
    return {
        "nome_anuncio": nome,
        "portal": portal,
        "preco": float(preco),
        "area_m2": float(area),
        "preco_m2": round(preco / area, 2),
        "quartos": quartos,
        "bairro": bairro,
        "url_anuncio": f"https://{portal}.com/{preco}-{area}",
    }


def test_nao_funde_imoveis_distintos_com_preco_e_area_parecidos():
    """O bug que destruía 70% dos resultados: mesma faixa, bairros diferentes."""
    itens = [
        anuncio("vivareal", 400_000, 60, "Meireles"),
        anuncio("zapimoveis", 402_000, 61, "Aldeota"),
        anuncio("imovelweb", 398_000, 60, "Papicu"),
    ]
    assert len(deduplicar_cross_portal(itens)) == 3


def test_funde_o_mesmo_imovel_em_portais_diferentes():
    itens = [
        anuncio("vivareal", 400_000, 60, "Meireles", "Apto Residencial Vista Bela"),
        anuncio("zapimoveis", 400_000, 60, "Meireles", "Apto Residencial Vista Bela"),
    ]
    resultado = deduplicar_cross_portal(itens)
    assert len(resultado) == 1
    assert resultado[0].get("portais_duplicados")


def test_nunca_funde_dentro_do_mesmo_portal():
    """O portal já deduplica internamente; anúncios distintos ali são imóveis distintos."""
    itens = [
        anuncio("vivareal", 400_000, 60, "Meireles"),
        anuncio("vivareal", 400_000, 60, "Meireles"),
    ]
    assert len(deduplicar_cross_portal(itens)) == 2


def test_nao_funde_tipologias_diferentes():
    itens = [
        anuncio("vivareal", 400_000, 60, "Meireles", quartos=2),
        anuncio("zapimoveis", 400_000, 60, "Meireles", quartos=3),
    ]
    assert len(deduplicar_cross_portal(itens)) == 2


def test_nao_funde_sem_informacao_de_localizacao():
    """Sem bairro em um dos lados não há evidência suficiente — erra para manter."""
    itens = [
        anuncio("vivareal", 400_000, 60, "Meireles"),
        anuncio("zapimoveis", 400_000, 60, None),
    ]
    assert len(deduplicar_cross_portal(itens)) == 2


def test_preserva_o_representante_mais_completo():
    completo = anuncio("zapimoveis", 400_000, 60, "Meireles")
    completo["banheiros"] = 2
    completo["vagas"] = 1
    itens = [anuncio("vivareal", 400_000, 60, "Meireles"), completo]
    resultado = deduplicar_cross_portal(itens)
    assert len(resultado) == 1
    assert resultado[0]["banheiros"] == 2


def test_lista_vazia_ou_unitaria():
    assert deduplicar_cross_portal([]) == []
    assert len(deduplicar_cross_portal([anuncio("vivareal", 400_000, 60, "X")])) == 1


def test_escala_sem_custo_quadratico():
    """300 anúncios devem processar em tempo trivial — antes eram ~73s para 163."""
    import time
    itens = [
        anuncio("vivareal" if i % 2 else "zapimoveis", 300_000 + i * 1_000, 50 + i % 40, f"Bairro{i % 25}")
        for i in range(300)
    ]
    inicio = time.time()
    deduplicar_cross_portal(itens)
    assert time.time() - inicio < 2.0
