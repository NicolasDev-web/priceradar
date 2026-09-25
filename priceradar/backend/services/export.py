"""Exportação para Excel.

Estrutura (desenhada com o agente Excel Design Architect e validada em quatro
rodadas de protótipo):

    INICIO    índice das abas e o que foi buscado
    RESUMO    indicadores + ranking de bairros — a resposta em uma página
    BAIRROS   uma linha por bairro, recalculada a partir de ANUNCIOS
    ANUNCIOS  base: um anúncio por linha, tabela do Excel, rola como planilha comum
    CONFIG    únicas células editáveis: faixa (±10%) e referencial MRV

Regras que os protótipos ensinaram, e que não devem voltar:
- Abas de dados (ANUNCIOS, BAIRROS) começam em A1, com grade visível e só o
  cabeçalho congelado. Título por cima e colunas congeladas deixaram a rolagem
  "travada".
- Número nunca tem recuo e toda coluna numérica tem folga: o Excel do Windows
  usa fonte mais larga que a do LibreOffice, e data/coordenada viraram #####.
- Indicador é tabela (Indicador | Valor | Leitura), não card: número grande em
  coluna estreita virou ###.
- Posição acima/abaixo sempre com símbolo (▲ ● ▼), nunca só cor.
- Cor de exceção vem de formatação condicional ligada à CONFIG: mudar a faixa
  ou o referencial MRV recalcula a planilha inteira sem reexportar.
- Comparação contra a MÉDIA (±10%), a mesma regra dos cards do app. A planilha
  não pode discordar da tela.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from models import Empreendimento

logger = logging.getLogger(__name__)

# ── Paleta oficial MRV (Território de marca, pp. 38-39) ─────────────────────
VERDE_ESCURO = "00683F"   # Pantone 7728 C — cabeçalhos e títulos
VERDE = "079D56"          # Pantone 7725 C — abaixo da média, gráfico
AMARELO = "FFB719"        # Pantone 137 C — borda das células editáveis
LARANJA = "FF8822"        # Pantone 1575 C
BRANCO = "FFFFFF"
# Tons claros das mesmas cores, para o fundo das exceções: com a cor cheia o
# texto perde contraste e a tabela vira um bloco colorido.
VERDE_CLARO, AMARELO_CLARO, LARANJA_CLARO = "E6F4EC", "FFF4D6", "FFE9D6"
LARANJA_TXT = "A34A00"
TXT, SUB = "333333", "767676"
INPUT_FUNDO, INPUT_TXT = "FFF8E1", "1F4E79"

FONTE = "Arial"
F_TITULO = Font(name=FONTE, size=16, bold=True, color=VERDE_ESCURO)
F_SUB = Font(name=FONTE, size=10, color=SUB)
F_SECAO = Font(name=FONTE, size=11, bold=True, color=VERDE_ESCURO)
F_TXT = Font(name=FONTE, size=10, color=TXT)
F_FORTE = Font(name=FONTE, size=11, bold=True, color=TXT)
F_CAB = Font(name=FONTE, size=10, bold=True, color=BRANCO)
F_LINK = Font(name=FONTE, size=10, color=VERDE, underline="single")

FINO = Side(style="thin", color="D9D9D9")
B_BAIXO = Border(bottom=FINO)
TRAC = Side(style="dashed", color=AMARELO)
B_INPUT = Border(left=TRAC, right=TRAC, top=TRAC, bottom=TRAC)

FMT_RS = '"R$" #,##0'
FMT_RS_M2 = '"R$" #,##0" /m²"'
FMT_PCT = '+0.0%;-0.0%;0.0%'
FMT_M2 = '0" m²"'
# Recuo só no texto à esquerda — é ele que encostava no número da coluna
# anterior. Número sem recuo: recuo come largura e gera #####.
ESQ = Alignment(horizontal="left", vertical="center", indent=1)
DIR = Alignment(horizontal="right", vertical="center")

SEM_BAIRRO = "Não informado"

PORTAL_LABEL = {
    "vivareal": "VivaReal", "zapimoveis": "ZAP", "chavesnamao": "ChavesNaMão", "imovelweb": "ImovelWeb",
    "olx": "OLX", "quintoandar": "QuintoAndar", "netimoveis": "NetImóveis", "mercadolivre": "Mercado Livre",
}

# Como ler a coordenada da linha — sem isso, um centroide de bairro seria lido
# como o endereço do imóvel.
_ROTULO_ORIGEM = {
    "exata": "Endereço",
    "aproximada_portal": "Aproximada (portal)",
    "centroide_bairro": "Centro do bairro",
}

# Base de anúncios: (cabeçalho, largura, formato, alinhamento). Larguras com
# folga para o maior valor formatado na fonte do Excel Windows.
COLUNAS = [
    ("Empreendimento", 36, None, ESQ), ("Bairro", 18, None, ESQ), ("Construtora", 17, None, ESQ),
    ("Portal", 15, None, ESQ), ("Quartos", 10, "0", DIR), ("Banheiros", 11, "0", DIR), ("Vagas", 9, "0", DIR),
    ("Área", 11, FMT_M2, DIR), ("Preço", 17, FMT_RS, DIR), ("Preço/m²", 19, FMT_RS_M2, DIR),
    ("vs. média", 13, FMT_PCT, DIR), ("Posição", 16, None, ESQ), ("vs. MRV", 12, FMT_PCT, DIR),
    ("Anúncio", 11, None, ESQ), ("Foto", 11, None, ESQ), ("Coletado em", 14, "dd/mm/yyyy", DIR),
    ("Latitude", 14, "0.00000", DIR), ("Longitude", 14, "0.00000", DIR), ("Precisão do local", 20, None, ESQ),
    ("Título do anúncio", 50, None, ESQ),
]
COL = {nome: get_column_letter(i) for i, (nome, *_) in enumerate(COLUNAS, start=1)}


def _fill(cor: str) -> PatternFill:
    return PatternFill("solid", fgColor=cor)


def _impressao(ws, uma_pagina: bool = False) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if uma_pagina else 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4


def _pagina(ws, titulo: str, subtitulo: str, larguras: dict[str, float], voltar: bool = True) -> None:
    """Abas de interface (INICIO, RESUMO, CONFIG): A margem, título em B1."""
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for letra, larg in larguras.items():
        ws.column_dimensions[letra].width = larg
    ws["B1"], ws["B1"].font = titulo, F_TITULO
    ws.row_dimensions[1].height = 26
    ws["B2"], ws["B2"].font = subtitulo, F_SUB
    if voltar:
        ws["B3"] = "‹ Voltar ao início"
        ws["B3"].hyperlink = "#'INICIO'!A1"
        ws["B3"].font = F_LINK
    _impressao(ws)


def _cabecalho(ws, linha: int, colunas: list[tuple[str, str, Alignment]]) -> None:
    for letra, texto, al in colunas:
        c = ws[f"{letra}{linha}"]
        c.value, c.font, c.fill = texto, F_CAB, _fill(VERDE_ESCURO)
        c.alignment = Alignment(horizontal=al.horizontal, vertical="center", wrap_text=True,
                                indent=1 if al.horizontal == "left" else 0)
    ws.row_dimensions[linha].height = 30


def _descrever_busca(ctx: dict) -> str:
    partes = []
    if ctx.get("quartos"):
        partes.append(f"{ctx['quartos']}{'+' if ctx['quartos'] >= 4 else ''} quartos")
    if ctx.get("banheiros"):
        partes.append(f"{ctx['banheiros']}{'+' if ctx['banheiros'] >= 4 else ''} banheiros")
    if ctx.get("preco_min") or ctx.get("preco_max"):
        def mil(v):
            return f"R$ {v / 1000:,.0f} mil".replace(",", ".")
        partes.append(f"{mil(ctx.get('preco_min') or 0)} a {mil(ctx.get('preco_max') or 0)}")
    if ctx.get("tipo_edificacao"):
        partes.append({"torre": "só torre", "provavel_bloco": "só bloco", "indefinido": "prédio sem info"}.get(
            ctx["tipo_edificacao"], ctx["tipo_edificacao"]))
    if ctx.get("bairros"):
        partes.append("bairros: " + ", ".join(ctx["bairros"]))
    return " · ".join(partes) or "sem filtros adicionais"


def gerar_excel(
    empreendimentos: list[Empreendimento],
    preco_m2_medio: float,
    contexto: dict | None = None,
) -> bytes:
    """
    Gera o workbook e devolve os bytes.

    `contexto` (opcional) descreve a busca: cidade, preco_min, preco_max,
    quartos, banheiros, bairros, tipo_edificacao, preco_m2_mrv, fontes.
    Sem ele a planilha sai completa, só com o cabeçalho mais genérico.
    `preco_m2_medio` fica na assinatura por compatibilidade; a média é
    recalculada por fórmula para acompanhar edições na base.
    """
    ctx = dict(contexto or {})
    ref_mrv = ctx.get("preco_m2_mrv") or next((e.preco_m2_mrv for e in empreendimentos if e.preco_m2_mrv), None)
    cidade = ctx.get("cidade") or (empreendimentos[0].cidade.title() if empreendimentos else "")
    coleta = max((e.data_coleta for e in empreendimentos if e.data_coleta), default=datetime.now())
    busca = _descrever_busca(ctx)

    emps = sorted(empreendimentos, key=lambda e: e.preco_m2)
    n = len(emps)

    wb = Workbook()
    nomes = ["INICIO", "RESUMO", "BAIRROS", "ANUNCIOS", "CONFIG"]
    abas = {nome: (wb.active if i == 0 else wb.create_sheet()) for i, nome in enumerate(nomes)}
    for nome, ws in abas.items():
        ws.title = nome

    # ═════════════ CONFIG ═════════════
    cfg = abas["CONFIG"]
    _pagina(cfg, "Configurações", "Edite só as células de fundo creme. As outras abas recalculam a partir daqui.",
            {"B": 32, "C": 18, "D": 72})
    _cabecalho(cfg, 5, [("B", "Parâmetro", ESQ), ("C", "Valor", DIR), ("D", "O que faz", ESQ)])
    parametros = [
        ('Faixa "na média" (±)', 0.10, "0%",
         "Anúncio dentro desta faixa em torno da média conta como 'na média'. Padrão do PriceRadar: 10%.", "FAIXA",
         DataValidation(type="decimal", operator="between", formula1="0", formula2="0.5",
                        showErrorMessage=True, error="Use um valor entre 0% e 50%.")),
        ("Referencial MRV (R$/m²)", ref_mrv, FMT_RS_M2,
         "Preço/m² da MRV na praça, vindo do PriceRadar." if ref_mrv else
         "Sem referencial cadastrado para esta cidade. Digite aqui para ver a comparação com a MRV.", "REF_MRV",
         DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True,
                        showErrorMessage=True, error="O referencial precisa ser maior que zero.")),
    ]
    for r, (rot, val, fmt, nota, nome, dv) in enumerate(parametros, start=6):
        cfg[f"B{r}"], cfg[f"B{r}"].font = rot, F_TXT
        v = cfg[f"C{r}"]
        v.value, v.number_format, v.alignment = val, fmt, DIR
        v.font = Font(name=FONTE, size=11, bold=True, color=INPUT_TXT)
        v.fill, v.border = _fill(INPUT_FUNDO), B_INPUT
        cfg[f"D{r}"], cfg[f"D{r}"].font = nota, F_SUB
        cfg.row_dimensions[r].height = 22
        wb.defined_names[nome] = DefinedName(nome, attr_text=f"CONFIG!$C${r}")
        cfg.add_data_validation(dv)
        dv.add(f"C{r}")

    # ═════════════ ANUNCIOS ═════════════
    base = abas["ANUNCIOS"]
    for nome, larg, *_ in COLUNAS:
        base.column_dimensions[COL[nome]].width = larg
    _impressao(base)
    _cabecalho(base, 1, [(COL[nome], nome, al) for nome, _, _, al in COLUNAS])
    p1, pn = 2, max(2, 1 + n)

    def rng(nome: str) -> str:
        return f"ANUNCIOS!${COL[nome]}${p1}:${COL[nome]}${pn}"

    wb.defined_names["PRECO_M2"] = DefinedName("PRECO_M2", attr_text=rng("Preço/m²"))
    wb.defined_names["MEDIA"] = DefinedName("MEDIA", attr_text="RESUMO!$C$6")

    for r, e in enumerate(emps, start=p1):
        pm2, vm = COL["Preço/m²"], COL["vs. média"]
        vals = {
            "Empreendimento": e.nome_empreendimento or e.nome_anuncio,
            "Bairro": e.bairro or SEM_BAIRRO,
            "Construtora": e.construtora or "",
            "Portal": PORTAL_LABEL.get(e.portal, e.portal),
            "Quartos": e.quartos if e.quartos is not None else "",
            "Banheiros": e.banheiros if e.banheiros is not None else "",
            "Vagas": e.vagas if e.vagas is not None else "",
            "Área": e.area_m2,
            "Preço": e.preco,
            "Preço/m²": f"={COL['Preço']}{r}/{COL['Área']}{r}",
            "vs. média": f"={pm2}{r}/MEDIA-1",
            "Posição": f'=IF({vm}{r}<-FAIXA,"▼ Abaixo",IF({vm}{r}>FAIXA,"▲ Acima","● Na média"))',
            "vs. MRV": f'=IF(REF_MRV>0,{pm2}{r}/REF_MRV-1,"")',
            "Anúncio": "Abrir" if e.url_anuncio else "",
            "Foto": "Ver foto" if e.fotos else "",
            "Coletado em": e.data_coleta,
            "Latitude": e.latitude if e.latitude is not None else "",
            "Longitude": e.longitude if e.longitude is not None else "",
            "Precisão do local": _ROTULO_ORIGEM.get(e.origem_coordenada or "", ""),
            "Título do anúncio": e.nome_anuncio,
        }
        for nome, _, fmt, al in COLUNAS:
            c = base[f"{COL[nome]}{r}"]
            c.value, c.font, c.alignment = vals[nome], F_TXT, al
            if fmt:
                c.number_format = fmt
        if e.url_anuncio:
            base[f"{COL['Anúncio']}{r}"].hyperlink = e.url_anuncio
            base[f"{COL['Anúncio']}{r}"].font = F_LINK
        if e.fotos:
            base[f"{COL['Foto']}{r}"].hyperlink = e.fotos[0]
            base[f"{COL['Foto']}{r}"].font = F_LINK

    ult = COL[COLUNAS[-1][0]]
    tabela = Table(displayName="tblAnuncios", ref=f"A1:{ult}{pn}")
    tabela.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    base.add_table(tabela)
    base.freeze_panes = "A2"      # só o cabeçalho; nenhuma coluna presa
    base.print_title_rows = "1:1"

    vs = f"${COL['vs. média']}{p1}"
    alvo = f"{COL['Preço/m²']}{p1}:{COL['Posição']}{pn}"
    base.conditional_formatting.add(alvo, FormulaRule(formula=[f"{vs}<-FAIXA"], fill=_fill(VERDE_CLARO),
                                                      font=Font(bold=True, color=VERDE_ESCURO)))
    base.conditional_formatting.add(alvo, FormulaRule(formula=[f"{vs}>FAIXA"], fill=_fill(LARANJA_CLARO),
                                                      font=Font(bold=True, color=LARANJA_TXT)))
    base.conditional_formatting.add(alvo, FormulaRule(formula=[f"AND({vs}>=-FAIXA,{vs}<=FAIXA)"],
                                                      fill=_fill(AMARELO_CLARO)))

    # ═════════════ BAIRROS ═════════════
    bai = abas["BAIRROS"]
    por_bairro: dict[str, list[float]] = {}
    for e in emps:
        por_bairro.setdefault(e.bairro or SEM_BAIRRO, []).append(e.preco_m2)
    # Ordem de exibição calculada aqui (o LibreOffice/Excel antigo não têm SORT);
    # os VALORES continuam sendo fórmula.
    bairros = sorted(por_bairro, key=lambda b: -sum(por_bairro[b]) / len(por_bairro[b]))
    for letra, larg in zip("ABCDEFG", (24, 12, 19, 14, 16, 12, 13)):
        bai.column_dimensions[letra].width = larg
    _impressao(bai)
    _cabecalho(bai, 1, [("A", "Bairro", ESQ), ("B", "Anúncios", DIR), ("C", "Preço/m² médio", DIR),
                        ("D", "vs. média", DIR), ("E", "Posição", ESQ), ("F", "vs. MRV", DIR), ("G", "Área média", DIR)])
    b1, bn = 2, max(2, 1 + len(bairros))
    for r, b in enumerate(bairros, start=b1):
        linha = [("A", b, None, ESQ), ("B", f"=COUNTIF({rng('Bairro')},A{r})", "0", DIR),
                 ("C", f"=AVERAGEIF({rng('Bairro')},A{r},{rng('Preço/m²')})", FMT_RS_M2, DIR),
                 ("D", f"=C{r}/MEDIA-1", FMT_PCT, DIR),
                 ("E", f'=IF(D{r}<-FAIXA,"▼ Abaixo",IF(D{r}>FAIXA,"▲ Acima","● Na média"))', None, ESQ),
                 ("F", f'=IF(REF_MRV>0,C{r}/REF_MRV-1,"")', FMT_PCT, DIR),
                 ("G", f"=AVERAGEIF({rng('Bairro')},A{r},{rng('Área')})", FMT_M2, DIR)]
        for letra, v, fmt, al in linha:
            c = bai[f"{letra}{r}"]
            c.value, c.font, c.alignment = v, F_TXT, al
            if fmt:
                c.number_format = fmt
    for regra, cf, ct in (("$D2<-FAIXA", VERDE_CLARO, VERDE_ESCURO), ("$D2>FAIXA", LARANJA_CLARO, LARANJA_TXT)):
        bai.conditional_formatting.add(f"C2:E{bn}", FormulaRule(formula=[regra], fill=_fill(cf),
                                                                font=Font(bold=True, color=ct)))
    tb = Table(displayName="tblBairros", ref=f"A1:G{bn}")
    tb.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    bai.add_table(tb)

    # ═════════════ RESUMO ═════════════
    res = abas["RESUMO"]
    _pagina(res, f"Preço de mercado — {cidade}",
            f"Apartamentos à venda · {busca} · coletado em {coleta:%d/%m/%Y}",
            {"B": 30, "C": 18, "D": 62})
    _cabecalho(res, 5, [("B", "Indicador", ESQ), ("C", "Valor", DIR), ("D", "Leitura", ESQ)])
    pos = rng("Posição")
    kpis = [
        ("Preço/m² médio", "=AVERAGE(PRECO_M2)", FMT_RS_M2,
         "Referência das cores (▲ ● ▼), a mesma dos cards do PriceRadar."),
        ("Preço/m² mediano", "=MEDIAN(PRECO_M2)", FMT_RS_M2,
         "Não é puxado por anúncio extremo — bom número para a reunião."),
        ("vs. referencial MRV", '=IF(REF_MRV>0,C6/REF_MRV-1,"—")', FMT_PCT,
         '=IF(REF_MRV>0,IF(C8>0,"▲ Mercado acima do referencial MRV","▼ Mercado abaixo do referencial MRV"),'
         '"Sem referencial MRV — informe na aba Configurações")'),
        ("Anúncios analisados", f"=COUNTA({rng('Bairro')})", "0", f'="Em "&COUNTA(BAIRROS!A{b1}:A{bn})&" bairros"'),
        ("▼ Abaixo da média", f'=COUNTIF({pos},"▼*")', "0", '=IF(C9>0,TEXT(C10/C9,"0%")&" dos anúncios","")'),
        ("▲ Acima da média", f'=COUNTIF({pos},"▲*")', "0", '=IF(C9>0,TEXT(C11/C9,"0%")&" dos anúncios","")'),
        ("Menor e maior preço/m²", "=MIN(PRECO_M2)", FMT_RS_M2, '="Maior: R$ "&FIXED(MAX(PRECO_M2),0)&" /m²"'),
    ]
    for r, (rot, formula, fmt, leitura) in enumerate(kpis, start=6):
        res[f"B{r}"], res[f"C{r}"], res[f"D{r}"] = rot, formula, leitura
        res[f"B{r}"].font, res[f"C{r}"].font, res[f"D{r}"].font = F_TXT, F_FORTE, F_SUB
        res[f"C{r}"].number_format = fmt
        res[f"B{r}"].alignment, res[f"C{r}"].alignment, res[f"D{r}"].alignment = ESQ, DIR, ESQ
        for letra in "BCD":
            res[f"{letra}{r}"].border = B_BAIXO
        res.row_dimensions[r].height = 20
    res["C6"].font = res["C7"].font = Font(name=FONTE, size=12, bold=True, color=VERDE_ESCURO)
    res.conditional_formatting.add("C8", FormulaRule(formula=["AND(ISNUMBER(C8),C8>0)"],
                                                     font=Font(bold=True, color=LARANJA_TXT)))
    res.conditional_formatting.add("C8", FormulaRule(formula=["AND(ISNUMBER(C8),C8<=0)"],
                                                     font=Font(bold=True, color=VERDE_ESCURO)))

    linha_graf = 15
    res[f"B{linha_graf - 1}"], res[f"B{linha_graf - 1}"].font = "Preço/m² médio por bairro", F_SECAO
    if bairros:
        g = BarChart()
        g.type, g.style, g.legend, g.title = "bar", 2, None, None
        g.add_data(Reference(bai, min_col=3, min_row=1, max_row=bn), titles_from_data=True)
        g.set_categories(Reference(bai, min_col=1, min_row=b1, max_row=bn))
        g.x_axis.scaling.orientation = "maxMin"   # mais caro no topo, como na aba BAIRROS
        g.y_axis.numFmt = '"R$" #,##0'
        g.y_axis.majorGridlines = None
        g.x_axis.delete = g.y_axis.delete = False
        s = g.series[0]
        s.graphicalProperties.solidFill = VERDE
        s.graphicalProperties.line.solidFill = VERDE
        s.dLbls = DataLabelList()
        s.dLbls.showVal = True
        for attr in ("showCatName", "showSerName", "showLegendKey", "showPercent"):
            setattr(s.dLbls, attr, False)
        s.dLbls.numFmt = '"R$" #,##0'
        g.gapWidth = 50
        g.width = 26
        g.height = max(7.0, 0.65 * len(bairros) + 1.5)   # cresce com o número de bairros
        res.add_chart(g, f"B{linha_graf}")
    linhas_graf = int((max(7.0, 0.65 * len(bairros) + 1.5)) / 0.5) + 2
    como_ler = linha_graf + linhas_graf
    res[f"B{como_ler}"], res[f"B{como_ler}"].font = "Como ler", F_SECAO
    for k, txt in enumerate([
        "▼ Abaixo: preço/m² mais de 10% abaixo da média.   ● Na média: dentro de ±10%.   ▲ Acima: mais de 10% acima.",
        "A faixa de 10% e o referencial MRV ficam na aba Configurações. Mudou lá, tudo recalcula.",
    ], start=como_ler + 1):
        res[f"B{k}"], res[f"B{k}"].font = txt, F_SUB
    _impressao(res, uma_pagina=True)

    # ═════════════ INICIO ═════════════
    ini = abas["INICIO"]
    _pagina(ini, "PriceRadar — Inteligência de preço",
            "Preço/m² de apartamentos à venda em portais concorrentes, comparado ao referencial MRV.",
            {"B": 22, "C": 95}, voltar=False)
    _cabecalho(ini, 5, [("B", "Aba", ESQ), ("C", "Para que serve", ESQ)])
    for r, (aba, rot, desc) in enumerate([
        ("RESUMO", "Resumo", "Comece aqui: preço/m² médio e mediano, comparação com a MRV e ranking de bairros."),
        ("BAIRROS", "Por bairro", "Quantidade, preço/m² médio e posição de cada bairro."),
        ("ANUNCIOS", "Anúncios", "Base completa: um anúncio por linha, com filtro, link e foto."),
        ("CONFIG", "Configurações", "Faixa de ±10% e referencial MRV. Única aba para editar."),
    ], start=6):
        ini[f"B{r}"], ini[f"C{r}"] = rot, desc
        ini[f"B{r}"].hyperlink = f"#'{aba}'!A1"
        ini[f"B{r}"].font, ini[f"C{r}"].font = F_LINK, F_TXT
        ini[f"B{r}"].alignment = ini[f"C{r}"].alignment = ESQ
        ini[f"B{r}"].border = ini[f"C{r}"].border = B_BAIXO
        ini.row_dimensions[r].height = 20
    _cabecalho(ini, 12, [("B", "Busca", ESQ), ("C", "", ESQ)])
    info = [("Cidade", cidade), ("Filtros", busca), ("Coletado em", f"{coleta:%d/%m/%Y %H:%M}"),
            ("Anúncios", str(n))]
    if ctx.get("fontes"):
        info.append(("Fontes", ", ".join(PORTAL_LABEL.get(f, f) for f in ctx["fontes"])))
    for r, (rot, val) in enumerate(info, start=13):
        ini[f"B{r}"], ini[f"C{r}"] = rot, val
        ini[f"B{r}"].font, ini[f"C{r}"].font = F_TXT, F_TXT
        ini[f"B{r}"].alignment = ini[f"C{r}"].alignment = ESQ
        ini[f"B{r}"].border = ini[f"C{r}"].border = B_BAIXO

    for nome, cor in zip(nomes, (VERDE_ESCURO, VERDE_ESCURO, VERDE, "BFBFBF", AMARELO)):
        abas[nome].sheet_properties.tabColor = cor
    wb.active = 1                         # abre no RESUMO
    wb.calculation.fullCalcOnLoad = True  # openpyxl não grava resultado de fórmula

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
