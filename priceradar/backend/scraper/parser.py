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


# ── Extração de bairro a partir do slug da URL ───────────────────────────────
#
# VivaReal e Zap NÃO expõem o bairro no JSON-LD: `address.addressLocality` traz
# a cidade e `streetAddress` traz o logradouro. O bairro só aparece no slug da
# URL do anúncio, imediatamente antes do nome da cidade:
#
#   apartamento-3-quartos-jose-bonifacio-fortaleza-com-garagem-78m2-venda-...
#   venda-apartamento-3-quartos-com-area-de-servico-montese-fortaleza-ce-...
#
# Ancoramos na cidade e caminhamos para trás até bater numa palavra descritiva.

# Palavras que aparecem no slug e nunca fazem parte do nome do bairro.
# Inclui amenidades: sem elas, "com-cozinha-jangurussu" viraria
# "Cozinha Jangurussu" em vez de "Jangurussu".
_TOKENS_NAO_BAIRRO = frozenset({
    'apartamento', 'apartamentos', 'apto', 'casa', 'cobertura', 'studio', 'kitnet',
    'flat', 'loft', 'lancamento', 'lancamentos', 'imovel', 'imoveis',
    'venda', 'vender', 'comprar', 'compra', 'aluguel', 'alugar', 'locacao',
    'quarto', 'quartos', 'dormitorio', 'dormitorios', 'suite', 'suites',
    'banheiro', 'banheiros', 'vaga', 'vagas', 'garagem', 'andar',
    'com', 'sem', 'de', 'do', 'da', 'e', 'em', 'no', 'na', 'para', 'por',
    'area', 'servico', 'lazer', 'mobiliado', 'mobiliada', 'semi', 'novo', 'nova',
    'piscina', 'academia', 'churrasqueira', 'playground', 'elevador', 'portaria',
    'condominio', 'salao', 'festas', 'varanda', 'sacada', 'gourmet', 'quadra',
    'cozinha', 'sala', 'jantar', 'estar', 'closet', 'escritorio', 'lavabo',
    'armarios', 'planejados', 'reformado', 'todo', 'otimo', 'excelente',
})

_RE_SUFIXO_ID = re.compile(r'-id-\d+$')
_RE_MEDIDA = re.compile(r'^\d+m2$|^rs\d+$|^\d+$')


def extrair_bairro_do_slug(url: str, cidade: str) -> str | None:
    """
    Extrai o bairro do slug da URL do anúncio, ancorando no nome da cidade.

    Retorna None quando não há evidência — anúncios de lançamento usam outro
    formato de slug (`/imoveis-lancamentos/nome-do-empreendimento-id-N/`) e
    não carregam bairro. Melhor vazio que errado.
    """
    if not url or not cidade:
        return None

    cidade_slug = normalizar_cidade(cidade).replace(' ', '-')
    if not cidade_slug:
        return None

    slug = url.rstrip('/').split('/')[-1]
    slug = _RE_SUFIXO_ID.sub('', slug)
    tokens = slug.split('-')

    # A cidade pode ser multi-token ("sao-paulo"): localiza a sequência.
    partes_cidade = cidade_slug.split('-')
    inicio_cidade = _indice_da_sequencia(tokens, partes_cidade)
    if inicio_cidade is None:
        return None

    bairro: list[str] = []
    for token in reversed(tokens[:inicio_cidade]):
        if token in _TOKENS_NAO_BAIRRO or _RE_MEDIDA.match(token):
            break
        bairro.insert(0, token)

    if not bairro:
        return None

    nome = ' '.join(bairro).title()
    # Bairro de uma letra ou absurdamente longo é ruído de parsing.
    return nome if 2 < len(nome) < 45 else None


def _indice_da_sequencia(tokens: list[str], sequencia: list[str]) -> int | None:
    """Índice onde `sequencia` começa dentro de `tokens`, ou None."""
    n = len(sequencia)
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == sequencia:
            return i
    return None


# ── Agente 3: lista expandida de construtoras ─────────────────────────────────

# Lista de construtoras/incorporadoras conhecidas — nacional + Nordeste/CE.
# Usada tanto para busca literal quanto para normalização do resultado.
_CONSTRUTORAS_CONHECIDAS: list[str] = [
    # Nacionais
    "MRV", "Cyrela", "Direcional", "Tenda", "Tegra", "Cury", "PDG",
    "Gafisa", "Rossi", "EzTec", "Mitre", "Helbor", "Lavvi", "Plano&Plano",
    "João Fortes", "Moura Dubeux", "Patrimar", "OAS", "EZTEC",
    "RNI", "Vitacon", "Kallas", "Brookfield", "Inpar",
    # Nordeste / Ceará
    "Marquise", "HM Engenharia", "Construtora Marquise",
    "Grupo Veredas", "Porte Engenharia", "NV Construtora", "Norcon",
    "Irmãos Almeida", "Capuche", "MDL", "Concret",
    "Via Empreendimentos", "Construtora Colinas", "Grupo Netos",
    "Construtora Barbosa Mello", "Cidade Verde",
    "G3 Construtora", "Conenge", "Plaenge", "Habitasul", "Setin",
]

# Removidos por gerarem falso positivo em texto livre de anúncio:
#   "Sky", "You", "Thera", "Aqwa"     — palavras comuns em nome de empreendimento
#   "Diagonal", "Dimensão", "Colinas" — substantivos comuns em descrição
#   "Habib", "CBL", "GEF", "Even"     — siglas/sobrenomes ambíguos
#   "Morada Nova"                      — é uma cidade do Ceará, não construtora
#   "Bairro Novo"                      — expressão genérica
# Regra: melhor o campo vazio que preenchido errado. Um "Sky" errado numa
# planilha entregue ao comercial custa mais do que uma célula em branco.

# Regex de busca para cada construtora (ordem: mais específica primeiro)
_RE_CONSTRUTORAS = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in _CONSTRUTORAS_CONHECIDAS) + r')\b',
    re.IGNORECASE,
)

# Prefixos institucionais que introduzem o nome da construtora
# "Imobiliária" saiu da lista: imobiliária é quem anuncia, não quem constrói —
# capturá-la enchia o campo `construtora` com nome de corretora.
_RE_PREFIXO_CONSTRUTORA = re.compile(
    r'(?:Construtora|Incorporadora)\s+'
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
            if nome and nome[0].isupper() and not _RE_RAZAO_SOCIAL.search(nome):
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
# Prefixos que identificam um empreendimento com segurança razoável.
# Removidos os que são acidente geográfico ou substantivo comum — "Parque",
# "Bosque", "Morada", "Jardins", "Reserva", "Clube" capturavam trechos como
# "Parque Estadual do Cocó" (um parque citado na descrição) e "Morada Nova"
# (cidade do Ceará) como se fossem nome de empreendimento.
_RE_EMPREENDIMENTO = re.compile(
    r'\b(?:Resid[eê]ncial\s+|Cond\.\s+|Condom[íi]nio\s+|'
    r'Ed[íi]f[íi]cio\s+|Torre\s+|Village\s+|Villa\s+|'
    r'Splendor\s+|Solaris\s+|Vivace\s+|Spazio\s+)'
    r'([A-ZÀ-Ú][A-Za-zÀ-ú0-9 \t&]{2,45})',
    re.IGNORECASE,
)

# Trechos que nunca são nome de empreendimento, mesmo casando com um prefixo.
_RE_NAO_E_EMPREENDIMENTO = re.compile(
    r'\b(estadual|municipal|nacional|federal|ecol[óo]gico|aqu[áa]tico|'
    r'shopping|hospital|universidade|aeroporto|terminal)\b',
    re.IGNORECASE,
)

# Sufixos societários: sinal de que se capturou uma razão social de
# imobiliária/anunciante, não a construtora do empreendimento.
_RE_RAZAO_SOCIAL = re.compile(r'\b(ltda|me|epp|eireli|s/?a)\b\.?\s*$', re.IGNORECASE)

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

    if m and _RE_NAO_E_EMPREENDIMENTO.search(m.group(0)):
        m = None  # equipamento urbano citado na descrição, não empreendimento

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

    # Sem padrão explícito de empreendimento, devolve None.
    #
    # Havia aqui um fallback que usava a primeira linha da descrição. Ele
    # produzia nomes que não são empreendimento — "LOCALIZAÇÃO PRIVILEGIADA",
    # "Parque Estadual do Cocó" — e inflava artificialmente a métrica de
    # preenchimento: o campo parecia cheio, mas com lixo.
    #
    # Melhor vazio que errado: o comercial consegue trabalhar com uma célula
    # em branco, não com um nome inventado.
    return None
