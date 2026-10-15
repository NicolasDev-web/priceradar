import re
from urllib.parse import urljoin

from services.texto import normalizar as normalizar_cidade


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


# ── Classificação torre × bloco ──────────────────────────────────────────────
#
# Torre e bloco são produtos diferentes e não deveriam entrar no mesmo preço/m².
# O sinal disponível é o elevador: torre tem, bloco não.
#
# A assimetria que define este código: `"sem elevador"` aparece em ZERO de 30
# anúncios medidos. Ninguém anuncia a ausência. Então:
#
#   elevador declarado        → evidência de TORRE
#   nada declarado            → ausência de DADO, não de elevador
#
# Por isso existe o rótulo `indefinido` (~48% da base) em vez de empurrar tudo
# para "bloco". Marcar como bloco o que apenas não foi declarado seria afirmar
# algo falso em metade dos anúncios, sem que ninguém pudesse perceber.

TORRE = "torre"
PROVAVEL_BLOCO = "provavel_bloco"
INDEFINIDO = "indefinido"

# Prédio sem elevador raramente passa de 4 pavimentos; a partir do 5º, tem.
_ANDAR_MINIMO_TORRE = 5

_RE_ELEVADOR = re.compile(r'\belevador', re.IGNORECASE)
_RE_ANDAR = re.compile(r'\b(\d{1,2})\s*[ºo°]?\s*(?:andar|pavimento)', re.IGNORECASE)


def classificar_edificacao(amenidades: list[str] | None, texto: str | None) -> str:
    """
    Classifica o anúncio em torre, provável bloco ou indefinido.

    `amenidades` são os valores de `amenityFeature` do JSON-LD (ex.: "Elevator").
    `texto` é título + descrição.

    Só devolve TORRE com evidência positiva. `PROVAVEL_BLOCO` é inferência a
    partir do andar e vem rotulado como provável de propósito — o card mostra
    o rótulo para que quem lê saiba o que é medido e o que é deduzido.
    """
    valores = [str(a).lower() for a in (amenidades or [])]
    conteudo = texto or ""

    tem_elevador = any("elevator" in v or "elevador" in v for v in valores)
    if tem_elevador or _RE_ELEVADOR.search(conteudo):
        return TORRE

    andar = _maior_andar(conteudo)
    if andar is not None:
        if andar >= _ANDAR_MINIMO_TORRE:
            return TORRE
        return PROVAVEL_BLOCO

    return INDEFINIDO


def _maior_andar(texto: str) -> int | None:
    """
    Maior andar citado no texto.

    Pega o maior porque um anúncio pode citar vários números ("do 2º ao 12º
    andar") e o que interessa é a altura do prédio, não a da unidade.
    """
    andares = [int(m.group(1)) for m in _RE_ANDAR.finditer(texto)]
    andares = [a for a in andares if 0 < a <= 60]  # descarta ruído de parsing
    return max(andares) if andares else None


def extrair_amenidades(item: dict) -> list[str]:
    """Valores de `amenityFeature` do JSON-LD, tolerante a formatos diferentes."""
    bruto = item.get("amenityFeature") or []
    if isinstance(bruto, dict):
        bruto = [bruto]
    valores = []
    for a in bruto:
        if isinstance(a, dict):
            v = a.get("value") or a.get("name")
            if v:
                valores.append(str(v))
        elif a:
            valores.append(str(a))
    return valores


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


# O regex de empreendimento captura até 45 caracteres depois do prefixo, e a
# frase continua: "Condomínio Vidal Vasconcelos oferece segurança",
# "Edifício Beach Class Unique localizado Meireles". O nome termina na primeira
# palavra que já é a frase seguindo — verbo ou conector.
_FIM_DO_NOME = frozenset({
    'oferece', 'oferecendo', 'localizado', 'localizada', 'situado', 'situada',
    'possui', 'conta', 'fica', 'proximo', 'perto', 'com', 'no', 'na', 'em', 'que',
    'para', 'ao', 'onde', 'apartamento', 'apto', 'unidade', 'venda', 'andar',
    'quartos', 'nascente', 'frente', 'excelente', 'otimo', 'lindo',
})

# Palavras de chamada comercial: o trecho depois do prefixo é slogan, não nome.
# "CONDOMÍNIO MAIS ACOLHEDOR DO MEIRELES", "Condomínio Clube", "Condomínio
# FECHADO". Um nome legítimo com uma delas se perde — melhor vazio que errado.
_PALAVRAS_SLOGAN = frozenset({
    'mais', 'melhor', 'acolhedor', 'completo', 'exclusivo', 'incrivel', 'perfeito',
    'privilegiado', 'privilegiada', 'fechado', 'clube', 'lazer', 'seguro', 'tranquilo',
    'moderno', 'novo', 'nova', 'otima', 'linda', 'top',
})

# Palavra em caixa alta grudada na seguinte: "MEIRELESLocalizado" vira
# "MEIRELES Localizado". Acontece quando o portal junta título e corpo.
_RE_GRUDADO = re.compile(r'([A-ZÀ-Ú]{2,})([A-ZÀ-Ú][a-zà-ú])')
_RE_NUMERO_SOLTO = re.compile(r'^\d+(?:[/,.]\d+)?(?:m|m2|m²)?$')

_PREFIXOS_NOME = frozenset({
    'residencial', 'cond', 'condominio', 'edificio', 'torre', 'village', 'villa',
})


def _cortar_nome(nome: str) -> str | None:
    """Corta o nome na frase que continua depois dele e recusa slogan."""
    nome = _RE_GRUDADO.sub(r'\1 \2', nome)
    palavras = nome.split()
    if not palavras:
        return None

    # O prefixo ("Residencial", "Cond.") não conta como palavra do nome.
    inicio = 1 if normalizar_cidade(palavras[0]).rstrip('.') in _PREFIXOS_NOME else 0
    corte = len(palavras)
    for i in range(inicio + 1, len(palavras)):
        palavra = normalizar_cidade(palavras[i]).strip('.,')
        # Número solto já é a frase seguindo: "Reserva Arvoredo 02 Quartos",
        # "Villa Venezia 3/4", "Villa Venezia 65 m²".
        if palavra in _FIM_DO_NOME or _RE_NUMERO_SOLTO.match(palavra):
            corte = i
            break
    palavras = palavras[:corte]

    resto = [normalizar_cidade(p).strip('.,') for p in palavras[inicio:]]
    if not resto or any(p in _PALAVRAS_SLOGAN for p in resto):
        return None
    return ' '.join(palavras)


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
        nome = _cortar_nome(nome)
        if nome and 5 < len(nome) < 80:
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


# ── Lançamentos ──────────────────────────────────────────────────────────────
#
# Os três portais que publicam lançamento põem o NOME DO EMPREENDIMENTO no slug
# da URL, em vez da descrição do imóvel que os anúncios comuns usam:
#
#   vivareal.com.br/imoveis-lancamentos/monte-roraima-id-2864813095/
#   zapimoveis.com.br/lancamentos/villa-lobos-id-2889406440/
#   chavesnamao.com.br/lancamento/lancamento-mood-guararapes/id-45658693/
#
# É o nome mais confiável que a coleta consegue sem requisição nova — escrito
# pelo portal, não garimpado de texto livre.
_RE_SLUG_LANCAMENTO = re.compile(
    r'/(?:imoveis-lancamentos?|lancamentos?)/(?P<slug>[a-z0-9-]+?)-?(?:-id-\d+)?/(?:id-\d+/)?$',
    re.IGNORECASE,
)
# Cauda de marketing no slug: "wind-no-meireles-powered-by-porsche-consulting".
_SLUG_FIM_DO_NOME = frozenset({'no', 'na', 'em', 'powered', 'by', 'com', 'apartamento', 'apartamentos'})

# Texto que declara a fase da obra. Ausência de declaração não é evidência de
# nada — o anúncio fica `None` (sem selo), como no torre × bloco.
_RE_TEXTO_LANCAMENTO = re.compile(
    r'\b(lan[çc]amento|na planta|previs[ãa]o de entrega|entrega prevista|em constru[çc][ãa]o)\b',
    re.IGNORECASE,
)
_RE_TEXTO_PRONTO = re.compile(
    r'\b(pronto para morar|reformad[oa]|usad[oa]|habite-se|mobiliad[oa])\b',
    re.IGNORECASE,
)


def extrair_nome_do_slug_lancamento(url: str | None) -> str | None:
    """Nome do empreendimento no slug de uma URL de lançamento, ou None."""
    caminho = (url or '').split('?')[0].split('#')[0].rstrip('/') + '/'
    m = _RE_SLUG_LANCAMENTO.search(caminho)
    if not m:
        return None
    tokens = [t for t in m.group('slug').lower().split('-') if t]
    # ChavesNaMão repete a categoria: "lancamento-mood-guararapes".
    while tokens and tokens[0] in ('lancamento', 'lancamentos'):
        tokens.pop(0)
    nome: list[str] = []
    for t in tokens:
        if t in _SLUG_FIM_DO_NOME and nome:
            break
        nome.append(t)
    texto = ' '.join(nome).title()
    return texto if 2 < len(texto) < 60 else None


def eh_anuncio_lancamento(url: str | None, texto: str | None) -> bool | None:
    """
    True = lançamento declarado; False = imóvel pronto declarado; None = não diz.

    A URL de lançamento é a evidência mais forte; depois, o texto. Texto que
    fala nos dois ("lançamento" e "pronto para morar") conta como lançamento
    recém-entregue.
    """
    if extrair_nome_do_slug_lancamento(url):
        return True
    conteudo = texto or ''
    if _RE_TEXTO_LANCAMENTO.search(conteudo):
        return True
    if _RE_TEXTO_PRONTO.search(conteudo):
        return False
    return None


def completar_empreendimento(registro: dict, texto: str | None = None) -> dict:
    """
    Preenche `nome_empreendimento` e `eh_lancamento` a partir do que o anúncio
    já tem — chamado por todo scraper no fim do parse, para que a regra seja a
    mesma em todos os portais.

    Ordem de confiança do nome: slug de lançamento (escrito pelo portal) >
    o que o scraper já extraiu > padrão explícito no título/descrição. Nunca
    copia o título: título é "Apartamento 2 quartos no Cocó", não um nome.
    """
    url = registro.get('url_anuncio')
    conteudo = texto if texto is not None else f"{registro.get('nome_anuncio') or ''}\n{registro.get('descricao') or ''}"
    nome = extrair_nome_do_slug_lancamento(url) or registro.get('nome_empreendimento')
    if nome and nome == registro.get('nome_anuncio'):
        nome = None
    registro['nome_empreendimento'] = nome or extrair_nome_empreendimento(conteudo)
    registro['eh_lancamento'] = eh_anuncio_lancamento(url, conteudo)
    return registro


def revisar_empreendimento_gravado(registro: dict) -> dict:
    """
    `completar_empreendimento` para anúncio que veio do BANCO.

    O nome gravado foi extraído pela regra de quando a busca rodou: em alguns
    portais era o título inteiro ("Apartamento com 3 dormitórios à venda… -
    Meireles - Fortaleza/CE"), em outros vinha com a frase seguinte colada
    ("… localizado Meireles"). Título vira None; o resto passa de novo pela
    extração, que corta a sobra sem perder o nome que veio da descrição
    completa (o banco só guarda 300 caracteres dela).
    """
    gravado = registro.get('nome_empreendimento')
    if gravado and gravado != registro.get('nome_anuncio'):
        registro['nome_empreendimento'] = extrair_nome_empreendimento(gravado)
    else:
        registro['nome_empreendimento'] = None
    return completar_empreendimento(registro)


# ── Fotos ────────────────────────────────────────────────────────────────────
#
# Só as fotos que já vêm na página de resultados: buscar a página de detalhe de
# cada anúncio multiplicaria as requisições, que é o que os portais pontuam
# como robô. Decisão registrada no PLANO_MELHORIAS.md (F1).

# Mais que isso não cabe no carrossel de um card e só engorda o cache no banco.
MAX_FOTOS = 10

# O CDN do Grupo ZAP publica a URL como molde:
#   https://resizedimgs.vivareal.com/{action}/{width}x{height}/named.images.sp/<hash>/foto.jpg
# Sem preencher, o navegador pede a URL literal com chaves e recebe 404.
_MOLDE_CDN = {
    "{action}": "fit-in",
    "{width}": "870",
    "{height}": "653",
    "{description}": "foto",
}

# Imagens de card que não são foto do imóvel: logo do anunciante, ícone,
# selo, pixel de rastreio.
_NAO_E_FOTO = re.compile(r"logo|icon|sprite|placeholder|badge|avatar|pixel|\.svg(?:\?|$)", re.I)


def _normalizar_url_foto(bruta: str, base_url: str | None) -> str | None:
    url = (bruta or "").strip()
    if not url or url.startswith("data:"):
        return None
    for molde, valor in _MOLDE_CDN.items():
        url = url.replace(molde, valor)
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        if not base_url:
            return None
        url = urljoin(base_url, url)
    if "{" in url or _NAO_E_FOTO.search(url):
        return None
    return url


def extrair_fotos(valor, base_url: str | None = None) -> list[str]:
    """
    URLs de foto a partir do que o portal publicar.

    Aceita os formatos que aparecem na prática: string, lista de strings,
    `ImageObject` do schema.org (`url`/`contentUrl`) ou lista deles.
    Devolve URLs absolutas, sem repetição, capa primeiro, no máximo MAX_FOTOS.
    Nunca levanta exceção: sem foto o anúncio continua valendo, e o card mostra
    a imagem genérica sinalizada.
    """
    candidatas: list[str] = []

    def coletar(v) -> None:
        if isinstance(v, str):
            candidatas.append(v)
        elif isinstance(v, dict):
            for chave in ("url", "contentUrl", "src", "href", "original", "thumbnailUrl"):
                if isinstance(v.get(chave), str):
                    candidatas.append(v[chave])
                    return
        elif isinstance(v, (list, tuple)):
            for x in v:
                coletar(x)

    try:
        coletar(valor)
    except Exception:  # formato inesperado: sem foto, não sem anúncio
        return []

    fotos: list[str] = []
    for bruta in candidatas:
        url = _normalizar_url_foto(bruta, base_url)
        if url and url not in fotos:
            fotos.append(url)
        if len(fotos) >= MAX_FOTOS:
            break
    return fotos


def fotos_de_card(card, base_url: str | None = None) -> list[str]:
    """
    Fotos de um card HTML (portais sem dado estruturado).

    Lazy-load é a regra nesses sites: a URL real costuma estar em `data-src`
    ou `srcset`, e o `src` é um placeholder — por isso a ordem de preferência.
    """
    urls: list[str] = []
    try:
        for img in card.select("img, source"):
            for attr in ("data-src", "data-lazy", "data-original", "src"):
                if img.get(attr):
                    urls.append(img[attr])
                    break
            else:
                srcset = img.get("srcset") or img.get("data-srcset")
                if srcset:
                    # "url1 320w, url2 640w" → a maior, que é a última
                    urls.append(srcset.split(",")[-1].strip().split(" ")[0])
    except Exception:
        return []
    return extrair_fotos(urls, base_url)
