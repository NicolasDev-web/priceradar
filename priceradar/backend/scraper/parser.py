import re
import unicodedata


def limpar_preco(texto: str) -> float | None:
    """Remove 'R$', pontos de milhar e normaliza para float."""
    try:
        if not texto:
            return None
        limpo = re.sub(r'[R$\s]', '', texto)
        limpo = re.sub(r'[^\d,.]', '', limpo)
        if ',' in limpo:
            limpo = limpo.replace('.', '').replace(',', '.')
        else:
            partes = limpo.split('.')
            if len(partes) > 2:
                limpo = ''.join(partes)
        return float(limpo)
    except Exception:
        return None


def limpar_area(texto: str) -> float | None:
    """Remove 'm²', espaços e converte para float."""
    try:
        if not texto:
            return None
        limpo = re.sub(r'[m²\s]', '', texto)
        limpo = limpo.replace(',', '.')
        limpo = re.sub(r'[^\d.]', '', limpo)
        return float(limpo) if limpo else None
    except Exception:
        return None


def extrair_numero(texto: str) -> int | None:
    """Extrai o primeiro inteiro de uma string."""
    try:
        if not texto:
            return None
        match = re.search(r'\d+', texto)
        return int(match.group()) if match else None
    except Exception:
        return None


def normalizar_cidade(texto: str) -> str:
    """Remove acentos, lowercase, strip."""
    try:
        nfkd = unicodedata.normalize('NFKD', texto)
        sem_acento = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return sem_acento.lower().strip()
    except Exception:
        return texto.lower().strip()


def calcular_preco_m2(preco: float, area: float) -> float:
    return round(preco / area, 2)


# ── Agente 3: lista expandida de construtoras ─────────────────────────────────

# Lista de construtoras/incorporadoras conhecidas — nacional + Nordeste/CE.
# Usada tanto para busca literal quanto para normalização do resultado.
_CONSTRUTORAS_CONHECIDAS: list[str] = [
    # Nacionais
    "MRV", "Cyrela", "Direcional", "Tenda", "Even", "Tegra", "Cury", "PDG",
    "Gafisa", "Rossi", "EzTec", "Mitre", "Helbor", "Lavvi", "Plano&Plano",
    "João Fortes", "Bairro Novo", "Moura Dubeux", "Patrimar", "OAS", "EZTEC",
    "RNI", "You", "Vitacon", "Kallas", "Brookfield", "Inpar",
    # Nordeste / Ceará
    "Marquise", "HM Engenharia", "Construtora Marquise", "Thera",
    "Grupo Veredas", "CBL", "Porte Engenharia", "NV Construtora", "Norcon",
    "GEF", "Irmãos Almeida", "Capuche", "MDL", "Concret", "Colinas",
    "Via Empreendimentos", "Construtora Colinas", "Aqwa", "Grupo Netos",
    "Construtora Barbosa Mello", "Diagonal", "Dimensão", "Cidade Verde",
    "G3 Construtora", "Conenge", "Habib", "Plaenge", "Habitasul",
    # Outros estados do Nordeste mas presentes em CE
    "Morada Nova", "Setin", "Sky",
]

# Regex de busca para cada construtora (ordem: mais específica primeiro)
_RE_CONSTRUTORAS = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in _CONSTRUTORAS_CONHECIDAS) + r')\b',
    re.IGNORECASE,
)

# Prefixos institucionais que introduzem o nome da construtora
_RE_PREFIXO_CONSTRUTORA = re.compile(
    r'(?:Construtora|Incorporadora|Imobili[áa]ria|Empreendimentos?)\s+'
    r'([A-Z][A-Za-zÀ-ú&\s]{2,30}?)(?=\s*[.,\-\n(]|\s{2}|\s*$)',
    re.IGNORECASE,
)

# Preposição "da/pela/pelo/da empresa X" seguido de nome conhecido
_RE_DA_CONSTRUTORA = re.compile(
    r'\b(?:da|pela|pelo|de|do)\s+(' + '|'.join(re.escape(c) for c in _CONSTRUTORAS_CONHECIDAS) + r')\b',
    re.IGNORECASE,
)

# Primeira palavra do nome capturado que indica falso positivo (preposição/artigo)
_PRIMEIRAS_PALAVRAS_INVALIDAS = frozenset({
    'a', 'o', 'de', 'do', 'da', 'em', 'no', 'na', 'um', 'uma',
    'com', 'por', 'para', 'todo', 'toda', 'seu', 'sua',
    'fortaleza', 'apartamento', 'imovel', 'imóvel', 'casa', 'venda', 'aluguel',
})


def extrair_construtora(nome_anuncio: str, descricao: str | None) -> str | None:
    """
    Extrai construtora/incorporadora do texto do anúncio.

    Estratégia (ordem de confiança):
    1. Busca literal na lista expandida de construtoras conhecidas.
    2. Padrão prefixado: "Construtora/Incorporadora X".
    3. Padrão preposicional: "da/pela X" onde X é construtora conhecida.
    """
    try:
        texto = (descricao or '') + ' ' + (nome_anuncio or '')
        if not texto.strip():
            return None

        # 1. Lista expandida: busca literal (mais confiável)
        m = _RE_CONSTRUTORAS.search(texto)
        if m:
            return _normalizar_construtora(m.group(1))

        # 2. Prefixo institucional
        m = _RE_PREFIXO_CONSTRUTORA.search(texto)
        if m:
            nome = m.group(1).strip()
            # re.IGNORECASE contamina [A-Z] — verificar maiúscula em Python
            if nome and nome[0].isupper():
                primeira = nome.split()[0].lower()
                if primeira not in _PRIMEIRAS_PALAVRAS_INVALIDAS and len(nome) > 2:
                    return _normalizar_construtora(nome)

        # 3. Preposição + nome conhecido
        m = _RE_DA_CONSTRUTORA.search(texto)
        if m:
            return _normalizar_construtora(m.group(1))

        return None
    except Exception:
        return None


def _normalizar_construtora(nome: str) -> str:
    """Padroniza capitalização e espaços do nome da construtora."""
    # Mantém siglas em maiúsculo (MRV, OAS, CBL, etc.)
    if nome.upper() == nome and len(nome) <= 5:
        return nome.upper()
    return ' '.join(p.capitalize() for p in nome.strip().split())


# ── Agente 3: extração melhorada de nome de empreendimento ───────────────────

# Prefixos típicos de nomes de empreendimentos imobiliários.
# \b garante que "Cond." não matcheia "condicionado".
# [ \t] em vez de \s para não capturar quebras de linha no nome.
_RE_EMPREENDIMENTO = re.compile(
    r'\b(?:Resid[eê]ncial|Cond\.\s+|Condom[íi]nio\s+|Parque\s+|Jardins?\s+d[oa]?\s*|'
    r'Ed[íi]f[íi]cio\s+|Torre\s+|Village\s+|Villa\s+|Vila\s+|'
    r'Gran\s+|Grand\s+|Reserva\s+|Bosque\s+|Portal\s+d[oa]?\s*|'
    r'Mirante\s+|Splendor\s+|Solaris\s+|Veredas\s+|'
    r'Clube\s+|Morada\s+|Vivace\s+|Spazio\s+|Excellence\s+|Unique\s+)'
    r'([A-ZÀ-Ú][A-Za-zÀ-ú0-9 \t&]{2,45})',
    re.IGNORECASE,
)

# Nome de empreendimento que parece ser apenas um preço monetário
_RE_PARECE_PRECO = re.compile(
    r'^\s*R?\$?\s*[\d.,]+\s*(mil|k|M)?\s*$',
    re.IGNORECASE,
)

# Texto que claramente é descrição de anúncio, não nome de empreendimento
_RE_INICIO_GENERICO = re.compile(
    r'^(O\s|A\s|Um\s|Uma\s|Este\s|Esta\s|Descubra|Lindo|Excelente|Melhor|'
    r'Ótimo|Boa\s|Apartamento|Apto|Ap\.|Casa|Imóvel|Imovel|Vendo|'
    r'Vende[-\s]|Compre|Oportunidade|\d)',
    re.IGNORECASE,
)


def extrair_nome_empreendimento(descricao: str | None) -> str | None:
    """
    Extrai o nome do empreendimento da descrição.

    Não retorna nomes genéricos (= título do anúncio, preço, descrição).
    Prefere padrões explícitos ("Residencial X", "Cond. X") a qualquer
    primeira linha.
    """
    if not descricao:
        return None

    texto = descricao.strip()

    # Prioridade 1: padrão explícito de empreendimento em qualquer parte do texto
    m = _RE_EMPREENDIMENTO.search(texto)
    if m:
        # re.IGNORECASE contamina [A-ZÀ-Ú] — verificar maiúscula do grupo capturado em Python
        captured = m.group(1)
        if not captured or not captured[0].isupper():
            m = None  # falso positivo; deixa cair para a segunda prioridade

    if m:
        nome = m.group(0).strip()
        # Remove parte descritiva após separador (ex: "Gran Club - Apartamento 2 quartos")
        nome = re.sub(
            r'\s*[-–—,]\s*(Apartamento|Apto|Casa|Im[oó]vel|com\s+\d|\d+\s*[Qq]uartos|[Aa]ndar).*$',
            '', nome, flags=re.IGNORECASE,
        )
        # Remove trailing ruído (pontuação, espaços, números soltos)
        nome = re.sub(r'[\s.,!?\-]+$', '', nome).strip()
        # Remove newlines embutidas (o character class [A-Za-z0-9 \t] não permite \n,
        # mas a limpeza pós-match garante em caso de edge case)
        nome = nome.replace('\n', ' ').strip()
        if 5 < len(nome) < 80:
            return nome

    # Prioridade 2: primeira linha curta que não pareça descrição genérica
    first = texto.split('\n')[0].strip()

    # Descarta se parece preço
    if _RE_PARECE_PRECO.match(first):
        return None

    # Descarta se começa com marcador genérico
    if _RE_INICIO_GENERICO.match(first):
        return None

    # Descarta se tem caracteres típicos de descrição (encoding quebrado incluso)
    if re.search(r'[mÂ²°]', first):
        return None

    # Exige inicial maiúscula para ser um nome de empreendimento
    if not first or not first[0].isupper():
        return None

    if 5 < len(first) < 70:
        # Remove qualquer newline que tenha escapado
        return first.replace('\n', ' ').strip()

    return None
