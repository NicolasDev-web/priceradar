import io
import logging

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from models import Empreendimento

logger = logging.getLogger(__name__)

# ── Paleta oficial MRV (Território de marca, pp. 38-39) ─────────────────────
# O manual pede o verde como cor principal. Nada fora da paleta: o azul-marinho, o vermelho e o azul-claro
# que a planilha usava antes não pertencem à marca.
VERDE_ESCURO = "00683F"   # Pantone 7728 C
VERDE = "079D56"          # Pantone 7725 C
AMARELO = "FFB719"        # Pantone 137 C
ROSA = "F7287C"           # Pantone 213 C (secundária)
BRANCO = "FFFFFF"
CINZA_70 = "4D4D4D"       # tons de cinza da paleta neutra
CINZA_ZEBRA = "F2F2F2"

HEADER_FG = BRANCO
ROW_ALT_BG = CINZA_ZEBRA

# Preço/m² contra a média. "Acima" usa o rosa da paleta secundária: é a única
# cor da marca que lê como alerta sem ser confundida com o amarelo da média.
COR_VERDE = VERDE
COR_AMARELO = AMARELO
COR_VERMELHO = ROSA
# Texto sobre cada faixa: branco some no amarelo (contraste ~1,7:1).
_TEXTO_SOBRE = {COR_VERDE: BRANCO, COR_AMARELO: VERDE_ESCURO, COR_VERMELHO: BRANCO}

_LINHA = Side(style="thin", color="D9D9D9")

COLUNAS = [
    ("Empreendimento", 32),
    ("Anúncio", 38),
    ("Construtora", 18),
    ("Cidade", 14),
    ("Bairro", 20),
    ("Preço (R$)", 15),
    ("Área m²", 10),
    ("Preço/m²", 12),
    ("Quartos", 9),
    ("Banheiros", 10),
    ("Vagas", 7),
    ("Portal", 12),
    ("URL", 40),
    ("Data Coleta", 20),
    # No fim de propósito: a formatação condicional abaixo endereça preço,
    # área e preço/m² por índice fixo (colunas 6, 7 e 8).
    ("Latitude", 12),
    ("Longitude", 12),
    ("Precisão", 18),
    # Só a capa: a planilha é para análise, e várias URLs numa célula não
    # servem para nada. Vazio = o anúncio não trouxe foto.
    ("Foto (capa)", 40),
]

# Como ler a coordenada da linha — sem isso, um centroide de bairro seria lido
# como o endereço do imóvel.
_ROTULO_ORIGEM = {
    "exata": "Endereço",
    "aproximada_portal": "Aproximada (portal)",
    "centroide_bairro": "Centro do bairro",
}


def gerar_excel(empreendimentos: list[Empreendimento], preco_m2_medio: float) -> bytes:
    """Gera planilha Excel formatada e retorna bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PriceRadar"

    # Cabeçalho
    # Verde principal sólido. O manual prefere degradê (45°) como recurso
    # gráfico, mas o Excel aplica degradê célula a célula e o cabeçalho fica
    # listrado nas emendas — sólido é o que lê como uma faixa só.
    header_fill = PatternFill(fill_type="solid", fgColor=VERDE_ESCURO)
    header_font = Font(color=HEADER_FG, bold=True, name="Calibri", size=11)

    for col_idx, (nome_col, largura) in enumerate(COLUNAS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=nome_col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = largura

    ws.row_dimensions[1].height = 28

    limite_verde = preco_m2_medio * 0.9
    limite_vermelho = preco_m2_medio * 1.1

    # Linhas de dados
    for row_idx, emp in enumerate(empreendimentos, start=2):
        is_alt = (row_idx % 2 == 0)
        row_fill = PatternFill(fill_type="solid", fgColor=ROW_ALT_BG) if is_alt else None

        valores = [
            emp.nome_empreendimento or emp.nome_anuncio,
            emp.nome_anuncio,
            emp.construtora or "",
            emp.cidade,
            emp.bairro or "",
            emp.preco,
            emp.area_m2,
            emp.preco_m2,
            emp.quartos if emp.quartos is not None else "",
            emp.banheiros if emp.banheiros is not None else "",
            emp.vagas if emp.vagas is not None else "",
            emp.portal,
            emp.url_anuncio,
            emp.data_coleta.strftime("%d/%m/%Y %H:%M") if emp.data_coleta else "",
            emp.latitude if emp.latitude is not None else "",
            emp.longitude if emp.longitude is not None else "",
            _ROTULO_ORIGEM.get(emp.origem_coordenada or "", ""),
            emp.fotos[0] if emp.fotos else "",
        ]

        for col_idx, valor in enumerate(valores, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=valor)
            if row_fill:
                cell.fill = row_fill
            cell.font = Font(name="Calibri", size=10, color=CINZA_70)
            cell.alignment = Alignment(vertical="center")
            cell.border = Border(bottom=_LINHA)

        # Formatação condicional para Preço/m² (coluna 8)
        preco_m2_cell = ws.cell(row=row_idx, column=8)
        if emp.preco_m2 < limite_verde:
            cor = COR_VERDE
        elif emp.preco_m2 > limite_vermelho:
            cor = COR_VERMELHO
        else:
            cor = COR_AMARELO
        preco_m2_cell.fill = PatternFill(fill_type="solid", fgColor=cor)
        preco_m2_cell.font = Font(name="Calibri", size=10, color=_TEXTO_SOBRE[cor], bold=True)

        # Formatar preço, área e preço/m² como números (colunas 6, 7, 8)
        ws.cell(row=row_idx, column=6).number_format = 'R$ #,##0.00'
        ws.cell(row=row_idx, column=7).number_format = '#,##0.00'
        ws.cell(row=row_idx, column=8).number_format = 'R$ #,##0.00'

    # Linha de médias/totais
    total_row = len(empreendimentos) + 2
    ws.cell(row=total_row, column=1, value="TOTAIS / MÉDIAS").font = Font(bold=True, name="Calibri")
    ws.cell(row=total_row, column=6, value=f"=AVERAGE(F2:F{total_row-1})").number_format = 'R$ #,##0.00'
    ws.cell(row=total_row, column=7, value=f"=AVERAGE(G2:G{total_row-1})").number_format = '#,##0.00'
    ws.cell(row=total_row, column=8, value=preco_m2_medio).number_format = 'R$ #,##0.00'

    footer_fill = PatternFill(fill_type="solid", fgColor=VERDE)
    for col_idx in range(1, len(COLUNAS) + 1):
        cell = ws.cell(row=total_row, column=col_idx)
        cell.fill = footer_fill
        cell.font = Font(bold=True, name="Calibri", size=10, color=BRANCO)
    ws.row_dimensions[total_row].height = 20

    # Legenda das cores do preço/m² — sem ela, quem recebe a planilha por
    # e-mail não sabe o que o verde, o amarelo e o rosa querem dizer.
    legenda_row = total_row + 2
    ws.cell(row=legenda_row, column=1, value="Legenda do Preço/m²").font = Font(
        bold=True, name="Calibri", size=10, color=VERDE_ESCURO
    )
    faixas = [
        (COR_VERDE, "Abaixo da média (−10% ou mais)"),
        (COR_AMARELO, "Na média (±10%)"),
        (COR_VERMELHO, "Acima da média (+10% ou mais)"),
    ]
    for i, (cor, texto) in enumerate(faixas, start=1):
        amostra = ws.cell(row=legenda_row + i, column=1, value=texto)
        amostra.fill = PatternFill(fill_type="solid", fgColor=cor)
        amostra.font = Font(name="Calibri", size=10, bold=True, color=_TEXTO_SOBRE[cor])

    # Cabeçalho fixo e filtro em todas as colunas dos dados.
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS))}{total_row - 1}"
    ws.sheet_properties.tabColor = VERDE_ESCURO

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
