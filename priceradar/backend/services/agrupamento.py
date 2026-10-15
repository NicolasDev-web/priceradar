"""Agrupamento de anúncios por empreendimento (prédio/condomínio).

O deduplicador junta o MESMO IMÓVEL anunciado em portais diferentes. Aqui a
pergunta é outra: quais anúncios — de unidades diferentes — são do MESMO
PRÉDIO? É o que permite dizer "o Residencial X está a R$ 9.800/m²" em vez de
só "a cidade está a R$ 7.500/m²".

Sinais, do mais ao menos confiável (medido no banco local em 15/10/2026):

- **Rua + número** (R1). Identifica o prédio. Só o RSC do Grupo ZAP traz o
  número, e nem sempre.
- **Coordenada exata do portal** (R2). O sinal mais abundante: 23 anúncios
  distintos caíam no mesmo ponto da Rua Vilebaldo Aguiar, todos com 80 ou
  100 m². O bairro, por outro lado, diverge no mesmo ponto (Benfica × Fátima),
  então ele NÃO é condição necessária aqui — ao contrário do deduplicador.
- **Nome do empreendimento** (R3). Raro (vem de "Residencial X" na descrição
  ou do slug de lançamento), mas é o único sinal que a OLX — metade da base,
  sem rua nem coordenada — pode ter. Só une com corroboração de lugar.
- Rua **sem** número não une nada: uma avenida tem dezenas de prédios.

Três NÍVEIS, cada anúncio em no máximo um grupo (são as abas da tela e do
Excel):

- ``mesmo_predio``: rua + número idênticos. É a definição de "exato mesmo
  prédio". Medido em 15/10 com os números do RSC: 26 endereços com 2+
  anúncios, 24 com coordenada idêntica. Anúncio sem número no mesmo ponto
  entra como ANEXO provável — mostrado, mas fora do preço.
- ``mesmo_local``: o que sobrou, ligado por coordenada exata. Provável, não
  prova: no mesmo ponto (-3.82086, -38.50859) havia "Rua A, 298" e "Rua B, 100".
- ``mesmo_nome``: o que sobrou, ligado pelo nome. Pode ser condomínio de
  várias torres ou dois empreendimentos homônimos — "confira".

Conservadorismo, como no deduplicador: na dúvida, separado. Um prédio partido
em dois grupos subestima a amostra; dois prédios fundidos produzem um preço
médio que não existe — e esse vai para a reunião comercial.
"""
from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from services.texto import normalizar

# R2: até onde duas coordenadas exatas ainda são o mesmo prédio. Um prédio
# grande ocupa ~50 m; o portal geocodifica a portaria. Sem rua para conferir,
# metade disso.
RAIO_MESMO_PREDIO_M = 30.0
RAIO_SEM_RUA_M = 15.0
# R3: nome igual só une se o lugar for compatível.
RAIO_NOME_M = 300.0
# Trava: grupo cujos membros se espalham além disto não é um prédio.
RAIO_MAXIMO_GRUPO_M = 400.0
LIMIAR_NOME = 0.9
MAX_PALAVRAS_NOME = 5
# R2 sem nome nem número para conferir: o portal às vezes geocodifica pelo
# centro da rua, e prédios vizinhos caem no mesmo ponto. No banco, isso
# aparecia como um "prédio" indo de R$ 2.900 a R$ 6.900/m². Unidades do mesmo
# prédio raramente diferem tanto — se as medianas dos dois lados passarem
# desta razão, não une.
RAZAO_MAX_PRECO_M2 = 1.4

# Níveis de agrupamento — do mais ao menos provado.
NIVEL_PREDIO = 'mesmo_predio'
NIVEL_LOCAL = 'mesmo_local'
NIVEL_NOME = 'mesmo_nome'
_CONFIANCA_NIVEL = {NIVEL_PREDIO: 'alta', NIVEL_LOCAL: 'media', NIVEL_NOME: 'baixa'}
# Mesmo endereço com coordenadas exatas mais longe que isto é erro de
# digitação no portal (o maior desvio medido no mesmo endereço foi 65 m).
RAIO_MESMO_ENDERECO_M = 150.0
# Anúncio sem número a até isto do ponto de um prédio confirmado: provável.
RAIO_ANEXO_M = 15.0

# Mesma unidade anunciada duas vezes (corretores diferentes, mesmo portal):
# o deduplicador não funde pares do mesmo portal, então a estatística do
# prédio precisa colapsar — senão uma unidade com 3 anúncios pesa 3 vezes.
TOLERANCIA_UNIDADE = 0.02

# ── Normalização ─────────────────────────────────────────────────────────────

_ABREVIACOES = {
    'av': 'avenida', 'avda': 'avenida', 'r': 'rua', 'tv': 'travessa', 'trav': 'travessa',
    'al': 'alameda', 'rod': 'rodovia', 'estr': 'estrada', 'pca': 'praca', 'pc': 'praca',
    'dr': 'doutor', 'dra': 'doutora', 'dep': 'deputado', 'gov': 'governador',
    'sen': 'senador', 'prof': 'professor', 'profa': 'professora', 'eng': 'engenheiro',
    'cel': 'coronel', 'pres': 'presidente', 'des': 'desembargador', 'mal': 'marechal',
    'gal': 'general', 'gen': 'general', 'cap': 'capitao', 'ten': 'tenente',
    'sta': 'santa', 'sto': 'santo', 'pe': 'padre', 'cons': 'conselheiro',
}
# Conectores somem: "Avenida da Universidade" e "Av. Universidade" são a mesma rua.
_CONECTORES = frozenset({'de', 'da', 'do', 'das', 'dos', 'e'})
_RE_NAO_ALFANUM = re.compile(r'[^a-z0-9 ]+')
_RE_NUMERO = re.compile(r'\b(\d{1,5})\s*[a-z]?\b')


def _tokens(texto: str) -> list[str]:
    return _RE_NAO_ALFANUM.sub(' ', normalizar(texto)).split()


def normalizar_rua(endereco: str | None) -> tuple[str | None, str | None]:
    """
    ("rua vilebaldo aguiar", "1000") a partir de "R. Vilebaldo Aguiar, 1000".

    O número só é aceito depois da vírgula — "Rua 25 de Março" e "Avenida 13
    de Maio" têm número no nome. Sem vírgula, só um número no fim conta.
    """
    if not endereco or not endereco.strip():
        return None, None
    rua_txt, _, resto = endereco.partition(',')
    numero = None
    if resto:
        m = _RE_NUMERO.search(normalizar(resto))
        numero = m.group(1) if m else None
    else:
        m = re.search(r'\s(\d{1,5})\s*$', rua_txt)
        if m:
            numero, rua_txt = m.group(1), rua_txt[:m.start()]
    if numero is not None:
        # "Raimundo Girão, 0630" e ", 630" são o mesmo prédio (medido em 15/10).
        numero = numero.lstrip('0') or None

    tokens = [_ABREVIACOES.get(t, t) for t in _tokens(rua_txt)]
    tokens = [t for t in tokens if t not in _CONECTORES]
    rua = ' '.join(tokens)
    return (rua or None), numero


# Palavras que todo nome de empreendimento tem e que, sozinhas, não distinguem
# um do outro. "Residencial Jardins" e "Condomínio Jardins" casam pelo resto.
_GENERICOS_NOME = frozenset({
    'residencial', 'residence', 'condominio', 'cond', 'edificio', 'ed', 'edf', 'res',
    'torre', 'torres', 'bloco', 'apartamento', 'apto', 'the', 'de', 'da', 'do', 'das',
    'dos', 'e', 'lancamento',
    # Sozinhos não distinguem: "Condomínio Parque", "Condomínio Club".
    'parque', 'park', 'club', 'clube',
    # Vocabulário de título de anúncio. Linhas antigas do banco têm o título
    # gravado como nome ("Apartamento 2 quartos à venda no Cocó"); sem isto,
    # "quartos venda" viraria um nome e uniria metade da OLX.
    'quarto', 'quartos', 'dormitorio', 'dormitorios', 'suite', 'suites', 'venda',
    'vendo', 'vende', 'metros', 'andar', 'nascente', 'vaga', 'vagas', 'com', 'no',
    'na', 'em', 'para', 'proximo', 'casa', 'cobertura', 'duplex', 'imovel', 'otimo',
    'excelente', 'lindo', 'novo', 'nova', 'comprar', 'banheiro', 'banheiros',
})


def normalizar_nome(nome: str | None) -> str | None:
    """
    "beach class unique" a partir de "Edifício Beach Class Unique".

    None se não sobrar nenhuma palavra distintiva (4+ letras) — "Edifício
    Sol" não é sinal suficiente para afirmar que dois anúncios são o mesmo prédio.
    """
    if not nome:
        return None
    # Número e letra solta não distinguem prédio ("2 quartos", "à venda").
    tokens = [t for t in _tokens(nome) if t not in _GENERICOS_NOME and len(t) > 1 and not t.isdigit()]
    if not any(len(t) >= 4 for t in tokens):
        return None
    # Mais que isso é frase, não nome de prédio: o título gravado como nome
    # ("… 188 m² por R$ 990 mil - Meireles - Fortaleza/CE") passaria aqui e
    # agruparia o bairro inteiro.
    if len(tokens) > MAX_PALAVRAS_NOME:
        return None
    return ' '.join(tokens)


def similaridade_nome(a: str | None, b: str | None) -> float:
    """Similaridade insensível à ordem das palavras ("Villa Roma" × "Roma Villa")."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, ' '.join(sorted(a.split())), ' '.join(sorted(b.split()))).ratio()


def distancia_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine em metros."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ── Features por anúncio ─────────────────────────────────────────────────────

class _Anuncio:
    __slots__ = ('idx', 'cidade', 'bairro', 'rua', 'numero', 'lat', 'lng', 'nome', 'preco_m2')

    def __init__(self, idx: int, item: dict):
        self.idx = idx
        self.preco_m2 = float(item.get('preco_m2') or 0) or None
        self.cidade = normalizar(str(item.get('cidade') or ''))
        self.bairro = normalizar(str(item.get('bairro') or '')) or None
        self.rua, self.numero = normalizar_rua(item.get('endereco'))
        # Só coordenada que o portal declara como do endereço. Centroide de
        # bairro e "aproximada" juntariam o bairro inteiro num prédio.
        if item.get('origem_coordenada') == 'exata' and item.get('latitude') is not None:
            self.lat, self.lng = float(item['latitude']), float(item['longitude'])
        else:
            self.lat = self.lng = None
        self.nome = normalizar_nome(item.get('nome_empreendimento'))

    @property
    def tem_coord(self) -> bool:
        return self.lat is not None


def _regra_r2(a: _Anuncio, b: _Anuncio) -> bool:
    if not (a.tem_coord and b.tem_coord):
        return False
    if a.rua and b.rua and a.rua != b.rua:
        return False
    if a.numero and b.numero and a.numero != b.numero:
        return False
    raio = RAIO_MESMO_PREDIO_M if (a.rua and b.rua) else RAIO_SEM_RUA_M
    return distancia_m(a.lat, a.lng, b.lat, b.lng) <= raio


def _regra_r3(a: _Anuncio, b: _Anuncio) -> bool:
    if similaridade_nome(a.nome, b.nome) < LIMIAR_NOME:
        return False
    if a.numero and b.numero and a.rua == b.rua and a.numero != b.numero:
        return False
    if a.tem_coord and b.tem_coord:
        return distancia_m(a.lat, a.lng, b.lat, b.lng) <= RAIO_NOME_M
    if a.rua and b.rua:
        return a.rua == b.rua
    return bool(a.bairro and b.bairro and (a.bairro in b.bairro or b.bairro in a.bairro))


# ── Union-Find com trava de conflito ─────────────────────────────────────────

class _Grupos:
    """Union-Find em que cada raiz guarda o que o grupo já afirma ser."""

    def __init__(self, anuncios: list[_Anuncio]):
        self.pai = list(range(len(anuncios)))
        self.nomes: dict[int, set[str]] = {a.idx: ({a.nome} if a.nome else set()) for a in anuncios}
        self.enderecos: dict[int, set[tuple[str, str]]] = {
            a.idx: ({(a.rua, a.numero)} if a.rua and a.numero else set()) for a in anuncios
        }
        self.coords: dict[int, list[tuple[float, float]]] = {
            a.idx: ([(a.lat, a.lng)] if a.tem_coord else []) for a in anuncios
        }
        self.sinais: dict[int, set[str]] = {a.idx: set() for a in anuncios}
        self.precos: dict[int, list[float]] = {
            a.idx: ([a.preco_m2] if a.preco_m2 else []) for a in anuncios
        }

    def raiz(self, x: int) -> int:
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def _so_lugar(self, raiz: int) -> bool:
        """O grupo não tem nome nem número: só a coordenada diz que é um prédio."""
        return not self.nomes[raiz] and not self.enderecos[raiz]

    def _conflito(self, ra: int, rb: int, sinal: str) -> bool:
        if sinal == 'coordenada' and self._so_lugar(ra) and self._so_lugar(rb):
            pa, pb = self.precos[ra], self.precos[rb]
            if pa and pb:
                ma, mb = statistics.median(pa), statistics.median(pb)
                if max(ma, mb) / min(ma, mb) > RAZAO_MAX_PRECO_M2:
                    return True
        # Nomes específicos diferentes: dois prédios que caíram no mesmo ponto
        # (geocodificação pelo centro da rua) ou na mesma rua.
        na, nb = self.nomes[ra], self.nomes[rb]
        if na and nb and not any(similaridade_nome(x, y) >= LIMIAR_NOME for x in na for y in nb):
            return True
        # Mesma rua com números diferentes: vizinhos, não o mesmo prédio.
        ruas_a = {r: n for r, n in self.enderecos[ra]}
        for r, n in self.enderecos[rb]:
            if r in ruas_a and ruas_a[r] != n:
                return True
        # Junção transitiva não pode espalhar o grupo pela cidade.
        for (la, ga) in self.coords[ra][:20]:
            for (lb, gb) in self.coords[rb][:20]:
                if distancia_m(la, ga, lb, gb) > RAIO_MAXIMO_GRUPO_M:
                    return True
        return False

    def unir(self, a: int, b: int, sinal: str) -> bool:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra == rb:
            self.sinais[ra].add(sinal)
            return True
        if self._conflito(ra, rb, sinal):
            return False
        self.pai[ra] = rb
        self.precos[rb].extend(self.precos.pop(ra))
        self.nomes[rb] |= self.nomes.pop(ra)
        self.enderecos[rb] |= self.enderecos.pop(ra)
        self.coords[rb].extend(self.coords.pop(ra))
        self.sinais[rb] |= self.sinais.pop(ra) | {sinal}
        return True


def _pares_por_bloco(blocos: dict[tuple, list[int]]):
    vistos: set[tuple[int, int]] = set()
    for indices in blocos.values():
        if len(indices) < 2:
            continue
        for p, i in enumerate(indices):
            for j in indices[p + 1:]:
                par = (i, j) if i < j else (j, i)
                if par not in vistos:
                    vistos.add(par)
                    yield par


# ── Estatística do grupo ─────────────────────────────────────────────────────

def colapsar_unidades(itens: list[dict]) -> list[list[dict]]:
    """
    Agrupa anúncios que são a MESMA UNIDADE: mesmos quartos, área e preço a
    ±2%. Cada sublista é uma unidade; a estatística do prédio conta cada uma
    uma vez.
    """
    unidades: list[list[dict]] = []
    for item in sorted(itens, key=lambda i: (float(i.get('area_m2') or 0), float(i.get('preco') or 0))):
        area, preco = float(item.get('area_m2') or 0), float(item.get('preco') or 0)
        for unidade in unidades:
            ref = unidade[0]
            area_r, preco_r = float(ref.get('area_m2') or 0), float(ref.get('preco') or 0)
            if (
                ref.get('quartos') == item.get('quartos')
                and area_r and preco_r
                and abs(area - area_r) / area_r <= TOLERANCIA_UNIDADE
                and abs(preco - preco_r) / preco_r <= TOLERANCIA_UNIDADE
            ):
                unidade.append(item)
                break
        else:
            unidades.append([item])
    return unidades


def _mais_frequente(valores: list[str]) -> str | None:
    valores = [v for v in valores if v]
    return Counter(valores).most_common(1)[0][0] if valores else None


def _nome_canonico(itens: list[dict]) -> str | None:
    """A grafia original mais frequente do nome normalizado mais frequente."""
    por_chave: dict[str, list[str]] = defaultdict(list)
    for i in itens:
        chave = normalizar_nome(i.get('nome_empreendimento'))
        if chave:
            por_chave[chave].append(i['nome_empreendimento'].strip())
    if not por_chave:
        return None
    chave = max(por_chave, key=lambda k: len(por_chave[k]))
    return _mais_frequente(por_chave[chave])


def _endereco_canonico(itens: list[dict]) -> str | None:
    """Prefere o endereço com número; entre iguais, o mais frequente."""
    enderecos = [str(i.get('endereco') or '').strip() for i in itens]
    com_numero = [e for e in enderecos if normalizar_rua(e)[1]]
    return _mais_frequente(com_numero) or _mais_frequente(enderecos)


def chave_grupo(cidade: str, itens: list[dict]) -> str:
    """
    Chave legível e estável entre buscas: o mesmo prédio, encontrado de novo
    amanhã com outros anúncios, precisa cair no mesmo id para o histórico.

    Ordem: endereço com número > nome > rua + coordenada arredondada a ~100 m.
    """
    pares = [normalizar_rua(i.get('endereco')) for i in itens]
    com_numero = [f'{r}|{n}' for r, n in pares if r and n]
    if com_numero:
        return f'end:{cidade}|{_mais_frequente(com_numero)}'
    nomes = [normalizar_nome(i.get('nome_empreendimento')) for i in itens]
    nome = _mais_frequente([n for n in nomes if n])
    if nome:
        return f'nome:{cidade}|{nome}'
    coords = [
        (float(i['latitude']), float(i['longitude'])) for i in itens
        if i.get('origem_coordenada') == 'exata' and i.get('latitude') is not None
    ]
    rua = _mais_frequente([r for r, _ in pares if r]) or ''
    if coords:
        lat = statistics.median(c[0] for c in coords)
        lng = statistics.median(c[1] for c in coords)
        return f'geo:{cidade}|{rua}|{lat:.3f},{lng:.3f}'
    return f'rua:{cidade}|{rua}'


def id_do_grupo(chave: str) -> str:
    return 'emp_' + hashlib.sha1(chave.encode('utf-8')).hexdigest()[:12]


def resumir_grupo(
    itens: list[dict], sinais: set[str] | None = None, nivel: str | None = None,
    anexos: list[dict] | None = None,
) -> dict:
    """
    Estatística de um empreendimento a partir dos anúncios CONFIRMADOS dele.
    `anexos` (prováveis) só são listados — nunca entram no preço.
    """
    cidade = normalizar(str(itens[0].get('cidade') or ''))
    unidades = colapsar_unidades(itens)
    precos_m2 = sorted(
        statistics.median(float(a['preco_m2']) for a in u) for u in unidades
    )
    areas = [float(i['area_m2']) for i in itens if i.get('area_m2')]
    precos = [float(i['preco']) for i in itens if i.get('preco')]
    coords = [
        (float(i['latitude']), float(i['longitude'])) for i in itens
        if i.get('origem_coordenada') == 'exata' and i.get('latitude') is not None
    ]
    lancamento = [i.get('eh_lancamento') for i in itens]
    sinais = sinais or set()
    chave = chave_grupo(cidade, itens)
    fotos = next((i['fotos'][0] for i in itens if i.get('fotos')), None)

    return {
        'grupo_id': id_do_grupo(chave),
        'chave': chave,
        'nome': _nome_canonico(itens),
        'endereco': _endereco_canonico(itens),
        'bairro': _mais_frequente([str(i.get('bairro') or '') for i in itens]),
        'cidade': cidade,
        'construtora': _mais_frequente([str(i.get('construtora') or '') for i in itens]),
        'latitude': statistics.median(c[0] for c in coords) if coords else None,
        'longitude': statistics.median(c[1] for c in coords) if coords else None,
        'n_anuncios': len(itens),
        'n_unidades': len(unidades),
        'preco_m2_mediana': round(statistics.median(precos_m2), 2),
        'preco_m2_medio': round(sum(precos_m2) / len(precos_m2), 2),
        'preco_m2_min': precos_m2[0],
        'preco_m2_max': precos_m2[-1],
        'area_min': min(areas) if areas else None,
        'area_max': max(areas) if areas else None,
        'preco_min': min(precos) if precos else None,
        'preco_max': max(precos) if precos else None,
        'quartos': sorted({int(i['quartos']) for i in itens if i.get('quartos') is not None}),
        'portais': sorted({str(i.get('portal')) for i in itens if i.get('portal')}),
        # Um anúncio dizendo "lançamento" basta; "pronto" só se nenhum disser o contrário.
        'eh_lancamento': True if True in lancamento else (False if False in lancamento else None),
        'nivel': nivel or _nivel_por_sinais(sinais),
        'confianca': _CONFIANCA_NIVEL[nivel or _nivel_por_sinais(sinais)],
        'sinais': sorted(sinais),
        'foto': fotos,
        'anexos': [a['url_anuncio'] for a in anexos or []],
        'n_provaveis': len(anexos or []),
    }


def _nivel_por_sinais(sinais: set[str]) -> str:
    """Para grupos montados fora de `agrupar` (dossiê, procura)."""
    if 'endereco' in sinais:
        return NIVEL_PREDIO
    if 'coordenada' in sinais:
        return NIVEL_LOCAL
    return NIVEL_NOME


# ── Entrada principal ────────────────────────────────────────────────────────

def _dividir_por_distancia(indices: list[int], anuncios: list['_Anuncio']) -> list[list[int]]:
    """
    Mesmo endereço, mas coordenadas exatas a mais de RAIO_MESMO_ENDERECO_M:
    é erro de digitação de um dos portais, e o "prédio" se divide. Anúncio sem
    coordenada fica com a maior parte — não há como saber de qual lado está.
    """
    com = [i for i in indices if anuncios[i].tem_coord]
    sem = [i for i in indices if not anuncios[i].tem_coord]
    partes: list[list[int]] = []
    for i in com:
        a = anuncios[i]
        for parte in partes:
            if any(distancia_m(a.lat, a.lng, anuncios[j].lat, anuncios[j].lng) <= RAIO_MESMO_ENDERECO_M
                   for j in parte):
                parte.append(i)
                break
        else:
            partes.append([i])
    if not partes:
        return [sem]
    max(partes, key=len).extend(sem)
    return partes


def _ponto(indices: list[int], anuncios: list['_Anuncio']) -> tuple[float, float] | None:
    pts = [(anuncios[i].lat, anuncios[i].lng) for i in indices if anuncios[i].tem_coord]
    if not pts:
        return None
    return statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)


def _componentes(grupos: '_Grupos', indices: list[int]) -> dict[int, list[int]]:
    membros: dict[int, list[int]] = defaultdict(list)
    for i in indices:
        membros[grupos.raiz(i)].append(i)
    return membros


def agrupar(itens: list[dict]) -> list[dict]:
    """
    Liga anúncios do mesmo empreendimento em três níveis (ver o topo do
    módulo). Grava em cada item `grupo_id` e `vinculo_grupo` (confirmado |
    provavel), ou None nos dois, e devolve um resumo por grupo com 2+ anúncios
    confirmados.

    Um anúncio sozinho não é apresentado como empreendimento: a mediana de um
    anúncio é o próprio anúncio, e chamá-la de "preço do prédio" seria afirmar
    o que não se sabe.
    """
    for item in itens:
        item['grupo_id'] = None
        item['vinculo_grupo'] = None
    if len(itens) < 2:
        return []

    anuncios = [_Anuncio(i, item) for i, item in enumerate(itens)]
    usados: set[int] = set()
    resumos: list[dict] = []

    def registrar(confirmados: list[int], nivel: str, sinais: set[str], anexos: list[int] = ()) -> dict:
        resumo = resumir_grupo([itens[i] for i in confirmados], sinais, nivel, [itens[i] for i in anexos])
        for i in confirmados:
            itens[i]['grupo_id'], itens[i]['vinculo_grupo'] = resumo['grupo_id'], 'confirmado'
        for i in anexos:
            itens[i]['grupo_id'], itens[i]['vinculo_grupo'] = resumo['grupo_id'], 'provavel'
        usados.update(confirmados)
        usados.update(anexos)
        resumos.append(resumo)
        return resumo

    # ── Nível 1: mesmo prédio (rua + número idênticos) ──
    por_endereco: dict[tuple, list[int]] = defaultdict(list)
    for a in anuncios:
        if a.rua and a.numero:
            por_endereco[(a.cidade, a.rua, a.numero)].append(a.idx)
    predios = [
        parte
        for indices in por_endereco.values() if len(indices) >= 2
        for parte in _dividir_por_distancia(indices, anuncios) if len(parte) >= 2
    ]
    em_predio = {i for parte in predios for i in parte}

    # Anexos prováveis: sem número, no ponto do prédio (mesma rua ou rua
    # ausente), ou com o mesmo nome no mesmo bairro. Mostrados, fora do preço.
    anexos: dict[int, list[int]] = defaultdict(list)
    pontos = [_ponto(parte, anuncios) for parte in predios]
    ruas = [anuncios[parte[0]].rua for parte in predios]
    nomes = [{anuncios[i].nome for i in parte if anuncios[i].nome} for parte in predios]
    bairros = [{anuncios[i].bairro for i in parte if anuncios[i].bairro} for parte in predios]
    for a in anuncios:
        if a.idx in em_predio or a.numero:
            continue
        melhor, melhor_d = None, None
        if a.tem_coord:
            for k, pt in enumerate(pontos):
                if pt is None or (a.rua and a.rua != ruas[k]):
                    continue
                d = distancia_m(a.lat, a.lng, pt[0], pt[1])
                if d <= RAIO_ANEXO_M and (melhor_d is None or d < melhor_d):
                    melhor, melhor_d = k, d
        if melhor is None and a.nome and a.bairro:
            for k in range(len(predios)):
                if a.bairro in bairros[k] and any(similaridade_nome(a.nome, n) >= LIMIAR_NOME for n in nomes[k]):
                    melhor = k
                    break
        if melhor is not None:
            anexos[melhor].append(a.idx)

    for k, parte in enumerate(predios):
        sinais = {'endereco'} | ({'coordenada'} if pontos[k] else set())
        registrar(parte, NIVEL_PREDIO, sinais, anexos.get(k, []))

    # ── Nível 2: mesmo local (coordenada exata), sobre o que sobrou ──
    restantes = [a for a in anuncios if a.idx not in usados]
    local = _Grupos(anuncios)
    por_celula: dict[tuple, list[int]] = defaultdict(list)
    for a in restantes:
        if a.tem_coord:
            cy, cx = int(math.floor(a.lat * 1000)), int(math.floor(a.lng * 1000))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    por_celula[(cy + dy, cx + dx)].append(a.idx)
    # Mais perto primeiro: a trava de conflito decide pela ligação mais forte.
    pares_r2 = [
        (distancia_m(anuncios[i].lat, anuncios[i].lng, anuncios[j].lat, anuncios[j].lng), i, j)
        for i, j in _pares_por_bloco(por_celula)
        if _regra_r2(anuncios[i], anuncios[j])
    ]
    for _, i, j in sorted(pares_r2):
        local.unir(i, j, 'coordenada')
    for raiz, indices in _componentes(local, [a.idx for a in restantes]).items():
        if len(indices) >= 2:
            registrar(indices, NIVEL_LOCAL, {'coordenada'})

    # ── Nível 3: mesmo nome, sobre o que sobrou ──
    restantes = [a for a in anuncios if a.idx not in usados]
    pelo_nome = _Grupos(anuncios)
    por_palavra: dict[tuple, list[int]] = defaultdict(list)
    for a in restantes:
        if a.nome:
            for t in set(a.nome.split()):
                if len(t) >= 4:
                    por_palavra[(a.cidade, t)].append(a.idx)
    for i, j in _pares_por_bloco(por_palavra):
        if _regra_r3(anuncios[i], anuncios[j]):
            pelo_nome.unir(i, j, 'nome')
    for raiz, indices in _componentes(pelo_nome, [a.idx for a in restantes]).items():
        if len(indices) >= 2:
            registrar(indices, NIVEL_NOME, {'nome'})

    ordem_nivel = {NIVEL_PREDIO: 0, NIVEL_LOCAL: 1, NIVEL_NOME: 2}
    resumos.sort(key=lambda r: (ordem_nivel[r['nivel']], -r['n_unidades'], -r['n_anuncios'], r['preco_m2_mediana']))
    return resumos


def mediana_por_empreendimento(itens: list[dict], resumos: list[dict]) -> float | None:
    """
    Mediana do preço/m² em que cada prédio conta uma vez (pela própria
    mediana) e cada anúncio sem grupo conta uma vez. Sem isso, um prédio com
    20 anúncios decide o número da cidade.
    """
    valores = [r['preco_m2_mediana'] for r in resumos]
    # Anexo provável tem grupo_id: conta pelo prédio, não como anúncio solto.
    valores += [float(i['preco_m2']) for i in itens if not i.get('grupo_id') and i.get('preco_m2')]
    return round(statistics.median(valores), 2) if valores else None
