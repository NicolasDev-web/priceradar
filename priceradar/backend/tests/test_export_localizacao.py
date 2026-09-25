"""Testes da planilha exportada (estrutura INICIO/RESUMO/BAIRROS/ANUNCIOS/CONFIG).

Cada teste trava uma regra que um protótipo quebrou ou que o antigo layout já
garantia:
- coordenada e "Precisão do local" continuam na base (centroide não pode ser
  lido como endereço);
- abas de dados rolam como planilha comum (v2 ficou "travada");
- nenhuma coluna numérica apertada (v2 mostrava #####);
- só cores da paleta MRV;
- sem referencial MRV a planilha não quebra.
"""
import io
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Empreendimento  # noqa: E402
from services import export  # noqa: E402
from services.export import COL, COLUNAS, gerar_excel  # noqa: E402


def empreendimento(**extra) -> Empreendimento:
    base = dict(
        id="1", nome_anuncio="Apartamento 2 quartos", nome_empreendimento="Residencial Teste",
        cidade="Fortaleza", bairro="Meireles", portal="vivareal", preco=400_000.0, area_m2=60.0,
        preco_m2=6_666.67, construtora=None, quartos=2, banheiros=1, vagas=1, descricao=None,
        url_anuncio="https://exemplo.com/imovel/1", data_coleta=datetime(2026, 7, 31, 10, 0),
    )
    base.update(extra)
    return Empreendimento(**base)


def livro(emps, media=7_000.0, contexto=None):
    return openpyxl.load_workbook(io.BytesIO(gerar_excel(emps, media, contexto)))


def celula(ws, nome_coluna, linha=2):
    return ws[f"{COL[nome_coluna]}{linha}"]


# ── Estrutura ────────────────────────────────────────────────────────────────

def test_abas_na_ordem_e_abre_no_resumo():
    wb = livro([empreendimento()])
    assert wb.sheetnames == ["INICIO", "RESUMO", "BAIRROS", "ANUNCIOS", "CONFIG"]
    assert wb.active.title == "RESUMO"


def test_abas_de_dados_rolam_como_planilha_comum():
    wb = livro([empreendimento()])
    assert wb["ANUNCIOS"].freeze_panes == "A2"          # só o cabeçalho
    assert wb["BAIRROS"].freeze_panes is None
    for aba in ("ANUNCIOS", "BAIRROS"):
        assert wb[aba]["A1"].value in ("Empreendimento", "Bairro")   # tabela começa em A1
        assert wb[aba].sheet_view.showGridLines is not False


def test_cabecalho_da_base_bate_com_colunas():
    ws = livro([empreendimento()])["ANUNCIOS"]
    assert [c.value for c in ws[1]] == [nome for nome, *_ in COLUNAS]


def test_nenhuma_coluna_numerica_apertada():
    """A v2 mostrava ##### em data e coordenada. Folga mínima: valor formatado + 20%."""
    for nome, largura, fmt, _ in COLUNAS:
        if not fmt:
            continue
        exemplo = {"Coletado em": "31/07/2026", "Latitude": "-12.97123", "Longitude": "-38.51234",
                   "Preço": "R$ 1.250.000", "Preço/m²": "R$ 12.500 /m²"}.get(nome, "+100.0%")
        assert largura >= len(exemplo) * 1.2, nome


# ── Conteúdo ─────────────────────────────────────────────────────────────────

def test_coordenada_e_precisao_na_base():
    ws = livro([empreendimento(latitude=-3.74631, longitude=-38.479013, origem_coordenada="exata")])["ANUNCIOS"]
    assert celula(ws, "Latitude").value == pytest.approx(-3.74631)
    assert celula(ws, "Longitude").value == pytest.approx(-38.479013)
    assert celula(ws, "Precisão do local").value == "Endereço"


@pytest.mark.parametrize("origem,rotulo", [
    ("exata", "Endereço"), ("aproximada_portal", "Aproximada (portal)"), ("centroide_bairro", "Centro do bairro"),
])
def test_rotulo_de_precisao(origem, rotulo):
    ws = livro([empreendimento(latitude=-3.7, longitude=-38.5, origem_coordenada=origem)])["ANUNCIOS"]
    assert celula(ws, "Precisão do local").value == rotulo


def test_sem_coordenada_fica_vazio_e_nao_zero():
    """0,0 é uma coordenada válida — no Golfo da Guiné. Vazio é a verdade."""
    ws = livro([empreendimento(origem_coordenada="formato_novo")])["ANUNCIOS"]
    for nome in ("Latitude", "Longitude", "Precisão do local"):
        assert celula(ws, nome).value in (None, "")


def test_preco_m2_e_posicao_sao_formulas_ligadas_a_config():
    ws = livro([empreendimento()])["ANUNCIOS"]
    assert celula(ws, "Preço/m²").value.startswith("=")
    assert "FAIXA" in celula(ws, "Posição").value
    assert "REF_MRV" in celula(ws, "vs. MRV").value


def test_link_do_anuncio_e_da_foto():
    ws = livro([empreendimento(fotos=["https://img/capa.jpg"])])["ANUNCIOS"]
    assert celula(ws, "Anúncio").hyperlink.target == "https://exemplo.com/imovel/1"
    assert celula(ws, "Foto").hyperlink.target == "https://img/capa.jpg"
    sem = livro([empreendimento()])["ANUNCIOS"]
    assert celula(sem, "Foto").value in (None, "")


def test_bairro_ausente_vira_nao_informado_e_entra_no_ranking():
    wb = livro([empreendimento(), empreendimento(id="2", bairro=None)])
    assert celula(wb["ANUNCIOS"], "Bairro", 3).value == export.SEM_BAIRRO or \
        celula(wb["ANUNCIOS"], "Bairro", 2).value == export.SEM_BAIRRO
    assert export.SEM_BAIRRO in [c.value for c in wb["BAIRROS"]["A"]]


def test_referencial_mrv_vem_do_contexto_ou_fica_vazio():
    com = livro([empreendimento()], contexto={"preco_m2_mrv": 6800})["CONFIG"]
    assert com["C7"].value == 6800
    sem = livro([empreendimento()])["CONFIG"]
    assert sem["C7"].value in (None, "")


def test_contexto_aparece_no_resumo():
    ctx = {"cidade": "Fortaleza, CE", "quartos": 2, "banheiros": 2, "preco_min": 280_000, "preco_max": 500_000}
    res = livro([empreendimento()], contexto=ctx)["RESUMO"]
    assert "Fortaleza, CE" in res["B1"].value
    assert "2 quartos" in res["B2"].value and "2 banheiros" in res["B2"].value


# ── Paleta da marca ──────────────────────────────────────────────────────────

def test_so_cores_da_paleta_mrv():
    paleta = {export.VERDE_ESCURO, export.VERDE, export.AMARELO, export.LARANJA, export.BRANCO,
              export.VERDE_CLARO, export.AMARELO_CLARO, export.LARANJA_CLARO, export.INPUT_FUNDO}
    wb = livro([empreendimento(id=str(i), preco=p * 60, preco_m2=p) for i, p in enumerate((5_000, 7_000, 9_000))])
    usadas = set()
    for ws in wb.worksheets:
        for linha in ws.iter_rows():
            for c in linha:
                if c.fill is not None and c.fill.fill_type == "solid":
                    usadas.add(c.fill.fgColor.rgb[-6:])
        for faixa in ws.conditional_formatting:
            for regra in faixa.rules:
                if regra.dxf and regra.dxf.fill is not None and regra.dxf.fill.fgColor is not None \
                        and regra.dxf.fill.fgColor.rgb:
                    usadas.add(regra.dxf.fill.fgColor.rgb[-6:])
    assert usadas and usadas <= paleta, usadas - paleta
