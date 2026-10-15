"""Dossiê de um empreendimento e busca por nome ou endereço.

As duas coisas trabalham sobre o HISTÓRICO da cidade (todo anúncio já
coletado, uma vez cada), não só sobre a última busca: o preço de um prédio
fica mais firme com os anúncios de várias buscas, e o histórico permite ver
quando cada anúncio apareceu e se ainda está no ar.

Busca por empreendimento — de onde vem cada sinal (ver services/agrupamento.py):

    endereco    rua + número iguais ao digitado                  → confirmado
    coordenada  anúncio a ≤ raio_m do ponto geocodificado        → confirmado
                (só quando o geocoder achou o número; ponto de meio de rua não vale)
    nome        nome extraído do anúncio ≈ nome digitado,        → confirmado
                com lugar compatível
    texto       o nome digitado aparece no título/descrição      → provável
    rua         mesma rua, sem número para confirmar             → provável

Confirmados puxam o resto do prédio: se um anúncio confirmado está num grupo
do histórico, o grupo inteiro entra (motivo `mesmo_predio`).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from scraper.parser import revisar_empreendimento_gravado
from scraper.rsc_grupozap import chave_url
from services.agrupamento import (
    NIVEL_LOCAL,
    NIVEL_NOME,
    NIVEL_PREDIO,
    RAIO_NOME_M,
    agrupar,
    distancia_m,
    normalizar_nome,
    normalizar_rua,
    resumir_grupo,
    similaridade_nome,
    _tokens,
)
from services.evolucao import MIN_AMOSTRA_PONTO, _ponto
from services.texto import normalizar

# Anúncio visto pela última vez até tanto antes da coleta mais recente da
# cidade ainda conta como "no ar". Fora disso, provavelmente saiu.
JANELA_ATIVO = timedelta(days=14)
MAX_PROVAVEIS = 60

_ORDEM_MOTIVO = {'endereco': 0, 'mesmo_predio': 1, 'coordenada': 2, 'mesmo_local': 3, 'anexo': 4,
                 'nome': 5, 'texto': 6, 'rua': 7}

# Que nível cada motivo de confirmação prova. O dossiê assume o nível do elo
# MAIS FRACO entre os confirmados: um "mesmo prédio" com um anúncio que só
# casou pelo nome já não é "exato mesmo prédio".
_NIVEL_DO_MOTIVO = {
    'endereco': NIVEL_PREDIO, 'mesmo_predio': NIVEL_PREDIO,
    'coordenada': NIVEL_LOCAL, 'mesmo_local': NIVEL_LOCAL,
    'nome': NIVEL_NOME, 'texto': NIVEL_NOME,
}
_ORDEM_NIVEL = [NIVEL_PREDIO, NIVEL_LOCAL, NIVEL_NOME]


def preparar_historico(itens: list[dict]) -> list[dict]:
    """Reaplica a regra atual de nome nos anúncios gravados (ver
    `revisar_empreendimento_gravado`)."""
    for item in itens:
        revisar_empreendimento_gravado(item)
    return itens


def _foto(item: dict) -> str | None:
    fotos = item.get('fotos')
    if isinstance(fotos, str):
        try:
            fotos = json.loads(fotos)
        except ValueError:
            fotos = None
    return fotos[0] if isinstance(fotos, list) and fotos else None


def _anuncio_saida(item: dict, mediana: float | None, ultimas: dict, motivo: str | None = None) -> dict:
    ultima_coleta = ultimas.get(_chave_cobertura(item))
    return {
        'url_anuncio': item['url_anuncio'],
        'portal': item.get('portal'),
        'nome_anuncio': item.get('nome_anuncio'),
        'nome_empreendimento': item.get('nome_empreendimento'),
        'preco': item.get('preco'),
        'area_m2': item.get('area_m2'),
        'preco_m2': item.get('preco_m2'),
        'quartos': item.get('quartos'),
        'banheiros': item.get('banheiros'),
        'vagas': item.get('vagas'),
        'bairro': item.get('bairro'),
        'endereco': item.get('endereco'),
        'foto': _foto(item),
        'primeira_vez': item.get('primeira_vez'),
        'ultima_vez': item.get('ultima_vez'),
        'ativo': bool(ultima_coleta and item.get('ultima_vez') and item['ultima_vez'] >= ultima_coleta - JANELA_ATIVO),
        'variacao_vs_grupo_pct': (
            round((item['preco_m2'] - mediana) / mediana * 100, 1) if mediana and item.get('preco_m2') else None
        ),
        'motivo': motivo,
    }


async def _serie(db, cidade: str, urls: set[str]) -> list[dict]:
    from repositories.empreendimento_repo import observacoes_por_periodo
    por_semana: dict[str, list[float]] = defaultdict(list)
    for o in await observacoes_por_periodo(db, cidade, None):
        if o['url'] in urls:
            por_semana[o['semana']].append(o['preco_m2'])
    return [_ponto(s, v) for s, v in sorted(por_semana.items())]


def _chave_cobertura(item: dict) -> tuple[str, str]:
    return (str(item.get('portal') or ''), normalizar(item.get('bairro') or ''))


def _ultimas_coletas(itens: list[dict]) -> dict[tuple[str, str], object]:
    """
    Última vez que cada portal foi coletado em cada bairro.

    "No ar" é relativo a ISTO, não à última coleta da cidade: uma busca de
    hoje no Cocó não diz nada sobre os anúncios do Barroso — com a referência
    da cidade, 21 de 23 anúncios do Reserva Arvoredo apareciam "fora do ar"
    só porque o Barroso não tinha sido coletado de novo.
    """
    ultimas: dict[tuple[str, str], object] = {}
    for i in itens:
        quando = i.get('ultima_vez')
        if quando:
            chave = _chave_cobertura(i)
            if chave not in ultimas or quando > ultimas[chave]:
                ultimas[chave] = quando
    return ultimas


def _membros_por_grupo(itens: list[dict]):
    """(confirmados por grupo, anexos prováveis por grupo, resumos por grupo)."""
    resumos = {r['grupo_id']: r for r in agrupar(itens)}
    membros: dict[str, list[dict]] = defaultdict(list)
    anexos: dict[str, list[dict]] = defaultdict(list)
    for i in itens:
        if i.get('grupo_id'):
            (anexos if i.get('vinculo_grupo') == 'provavel' else membros)[i['grupo_id']].append(i)
    return membros, anexos, resumos


def _nivel_mais_fraco(motivos: list[str], padrao: str) -> str:
    niveis = [_NIVEL_DO_MOTIVO[m] for m in motivos if m in _NIVEL_DO_MOTIVO]
    return max(niveis, key=_ORDEM_NIVEL.index) if niveis else padrao


async def _montar_resposta(db, cidade: str, itens_hist: list[dict], escolhidos: list[dict],
                           motivos: dict[str, str], sinais: set[str], provaveis: list[dict] | None = None,
                           nivel: str | None = None) -> dict:
    ultima = _ultimas_coletas(itens_hist)
    resumo = resumir_grupo(escolhidos, sinais, nivel, provaveis) if escolhidos else None
    mediana = resumo['preco_m2_mediana'] if resumo else None
    anuncios = sorted(
        (_anuncio_saida(i, mediana, ultima, motivos.get(i['url_anuncio'])) for i in escolhidos),
        key=lambda a: (not a['ativo'], a['preco_m2'] or 0),
    )
    urls = {chave_url(i['url_anuncio']) or i['url_anuncio'] for i in escolhidos}
    bairros = sorted({i['bairro'] for i in escolhidos if i.get('bairro')})
    return {
        'grupo': resumo,
        'anuncios': anuncios,
        'ativos': sum(1 for a in anuncios if a['ativo']),
        'provaveis': [
            _anuncio_saida(i, mediana, ultima, motivos.get(i['url_anuncio']))
            for i in (provaveis or [])
        ],
        'serie': await _serie(db, cidade, urls) if urls else [],
        'min_amostra': MIN_AMOSTRA_PONTO,
        # Mesmo nome em bairros distantes costuma ser dois empreendimentos.
        'aviso': (
            f"Os anúncios estão em {len(bairros)} bairros ({', '.join(bairros)}) — "
            "pode ser mais de um empreendimento com o mesmo nome."
            if len(bairros) > 2 or (len(bairros) == 2 and 'endereco' not in sinais and 'coordenada' not in sinais)
            else None
        ),
    }


# ── Dossiê por grupo ─────────────────────────────────────────────────────────

async def montar_dossie(db, cidade: str, grupo_id: str) -> dict | None:
    """
    Tudo o que o histórico sabe sobre o empreendimento `grupo_id`.

    O id pode ter nascido de uma busca com menos anúncios que o histórico, e a
    chave do grupo (nome mais frequente, mediana da coordenada) pode mudar
    quando entram mais. Por isso o grupo do histórico é achado pelos anúncios
    que as buscas gravaram com este id, e não só pelo id recalculado.
    """
    from repositories.empreendimento_repo import historico_da_cidade
    itens = preparar_historico(await historico_da_cidade(db, cidade))
    if not itens:
        return None
    membros, anexos, resumos = _membros_por_grupo(itens)

    gravados = [i for i in itens if grupo_id in (i.get('grupos_gravados') or ())]
    votos = defaultdict(int)
    for i in gravados:
        if i.get('grupo_id'):
            votos[i['grupo_id']] += 1
    alvo = max(votos, key=votos.get) if votos else (grupo_id if grupo_id in membros else None)

    escolhidos = {i['url_anuncio']: i for i in membros.get(alvo, [])}
    provaveis = {i['url_anuncio']: i for i in anexos.get(alvo, [])}
    # O que a busca agrupou e o histórico não (trava de conflito com mais
    # dados) continua no dossiê: foi o que o usuário viu junto na tela.
    for i in gravados:
        if i['url_anuncio'] not in provaveis:
            escolhidos.setdefault(i['url_anuncio'], i)
    if not escolhidos:
        return None
    sinais = set(resumos[alvo]['sinais']) if alvo in resumos else {'busca'}
    nivel = resumos[alvo]['nivel'] if alvo in resumos else NIVEL_NOME
    motivos = {u: 'anexo' for u in provaveis}
    return await _montar_resposta(db, cidade, itens, list(escolhidos.values()), motivos, sinais,
                                  list(provaveis.values()), nivel)


# ── Busca por nome ou endereço ───────────────────────────────────────────────

def _frase(texto: str | None) -> str | None:
    """Nome digitado como frase normalizada, sem as palavras genéricas da ponta."""
    if not texto:
        return None
    tokens = _tokens(texto)
    while tokens and tokens[0] in ('residencial', 'condominio', 'cond', 'edificio', 'ed'):
        tokens.pop(0)
    frase = ' '.join(tokens)
    return frase if len(frase) >= 4 else None


def pontuar(item: dict, alvo: dict) -> str | None:
    """Motivo mais forte pelo qual `item` é o empreendimento procurado, ou None."""
    rua, numero = normalizar_rua(item.get('endereco'))
    if alvo['rua'] and alvo['numero'] and rua == alvo['rua'] and numero == alvo['numero']:
        return 'endereco'

    geo = alvo.get('geo')
    tem_coord = item.get('origem_coordenada') == 'exata' and item.get('latitude') is not None
    dist = (
        distancia_m(geo['latitude'], geo['longitude'], float(item['latitude']), float(item['longitude']))
        if geo and tem_coord else None
    )
    if geo and geo.get('precisa') and dist is not None and dist <= alvo['raio_m']:
        # Esquina: ponto perto, mas outra rua declarada — não é o prédio.
        if not (rua and alvo['rua'] and rua != alvo['rua']):
            return 'coordenada'

    if alvo['nome'] and similaridade_nome(normalizar_nome(item.get('nome_empreendimento')), alvo['nome']) >= 0.9:
        lugar_ok = True
        if dist is not None:
            lugar_ok = dist <= RAIO_NOME_M
        elif alvo['bairro'] and item.get('bairro'):
            b1, b2 = normalizar(item['bairro']), alvo['bairro']
            lugar_ok = b1 in b2 or b2 in b1
        if lugar_ok:
            return 'nome'
        return 'texto'

    if alvo['frase']:
        texto = ' '.join(_tokens(f"{item.get('nome_anuncio') or ''} {item.get('descricao') or ''}"))
        if f" {alvo['frase']} " in f" {texto} ":
            return 'texto'

    if alvo['rua'] and rua == alvo['rua']:
        return 'rua'
    return None


def mesclar_coletados(historico: list[dict], coletados: list[dict]) -> list[dict]:
    """
    Junta ao histórico anúncios coletados agora e não gravados (busca da OLX
    pelo nome). Mesma URL: fica o dado novo, com a primeira aparição antiga.
    """
    agora = datetime.now()
    por_url = {chave_url(i['url_anuncio']) or i['url_anuncio']: i for i in historico}
    for novo in coletados:
        novo = dict(novo)
        revisar_empreendimento_gravado(novo)
        chave = chave_url(novo.get('url_anuncio') or '') or novo.get('url_anuncio')
        antigo = por_url.get(chave)
        novo.update(
            primeira_vez=antigo['primeira_vez'] if antigo else agora,
            ultima_vez=agora,
            grupos_gravados=antigo['grupos_gravados'] if antigo else set(),
        )
        por_url[chave] = novo
    return list(por_url.values())


async def procurar_empreendimento(
    db, cidade: str, nome: str | None, endereco: str | None, raio_m: float = 60.0,
    bairro: str | None = None, coletados: list[dict] | None = None,
) -> dict:
    from repositories.empreendimento_repo import historico_da_cidade
    from services.geocoding import geocodificar

    rua, numero = normalizar_rua(endereco)
    geo = await geocodificar(endereco, cidade) if endereco else None
    # Rua digitada sem número, mas o OSM achou o número: aproveita.
    if geo and not numero and geo.get('numero') and geo.get('rua'):
        rua2, numero2 = normalizar_rua(f"{geo['rua']}, {geo['numero']}")
        if rua2 == rua:
            numero = numero2
    alvo = {
        'rua': rua, 'numero': numero, 'geo': geo, 'raio_m': raio_m,
        'nome': normalizar_nome(nome), 'frase': _frase(nome),
        'bairro': normalizar(bairro or (geo or {}).get('bairro') or '') or None,
    }

    itens = preparar_historico(await historico_da_cidade(db, cidade))
    if coletados:
        itens = mesclar_coletados(itens, coletados)
    membros, anexos, resumos = _membros_por_grupo(itens)

    por_url_0 = {i['url_anuncio']: i for i in itens}
    motivos: dict[str, str] = {}
    for item in itens:
        motivo = pontuar(item, alvo)
        if motivo:
            motivos[item['url_anuncio']] = motivo

    fortes = {'endereco', 'coordenada', 'nome'}
    # Endereço com número e algum anúncio nele: só esse endereço é o prédio.
    # Quem apenas cai no mesmo ponto vira provável — o mesmo ponto já juntou
    # "Rua A, 298" e "Rua B, 100" (medido). Sem anúncio no endereço exato, o
    # ponto confirma, e a resposta sai como "mesmo local".
    if alvo['numero'] and 'endereco' in motivos.values():
        fortes = {'endereco', 'nome'}
    confirmados = {u for u, m in motivos.items() if m in fortes}
    # Nome sem lugar para conferir (nada de endereço nem bairro informados):
    # o bairro predominante entre os que casaram pelo nome decide; os demais
    # viram prováveis. Medido: "Reserva Arvoredo" trazia 3 anúncios do Eng.
    # Luciano Cavalcante confirmados junto com os 38 do Barroso.
    if not alvo['bairro'] and not geo:
        por_nome = [u for u in confirmados if motivos[u] == 'nome']
        contagem = Counter(normalizar(por_url_0[u].get('bairro') or '') for u in por_nome)
        contagem.pop('', None)
        if len(contagem) > 1:
            dominante = contagem.most_common(1)[0][0]
            for u in por_nome:
                b = normalizar(por_url_0[u].get('bairro') or '')
                if b and b != dominante:
                    confirmados.discard(u)
                    motivos[u] = 'texto'   # cita o nome, mas em outro lugar
    sinais = {motivos[u] for u in confirmados}
    # O resto do prédio de cada confirmado entra também.
    por_url = {i['url_anuncio']: i for i in itens}
    for u in list(confirmados):
        gid = por_url[u].get('grupo_id')
        if gid not in resumos or por_url[u].get('vinculo_grupo') == 'provavel':
            continue
        nivel_grupo = resumos[gid]['nivel']
        motivo_grupo = {NIVEL_PREDIO: 'mesmo_predio', NIVEL_LOCAL: 'mesmo_local'}.get(nivel_grupo, 'nome')
        for m in membros.get(gid, []):
            if m['url_anuncio'] not in confirmados:
                confirmados.add(m['url_anuncio'])
                motivos.setdefault(m['url_anuncio'], motivo_grupo)
        # Anexos do prédio: prováveis, fora do preço.
        for m in anexos.get(gid, []):
            if m['url_anuncio'] not in confirmados:
                motivos[m['url_anuncio']] = 'anexo'
        sinais |= set(resumos[gid]['sinais'])
    sinais &= {'endereco', 'coordenada', 'nome'}

    # O nome digitado no texto do anúncio ("Villa Venezia liga 9 87…", sem
    # prefixo que a extração reconheça) confirma quando está no mesmo bairro
    # dos já confirmados. Precisa de 2+ palavras: "Jardins" sozinho no texto
    # é adjetivo de metade dos anúncios.
    if confirmados and alvo['frase'] and len(alvo['frase'].split()) >= 2:
        bairros_conf = Counter(normalizar(por_url[u].get('bairro') or '') for u in confirmados)
        bairros_conf.pop('', None)
        dominante = bairros_conf.most_common(1)[0][0] if bairros_conf else None
        for u, m in motivos.items():
            if m == 'texto' and u not in confirmados and dominante \
                    and normalizar(por_url[u].get('bairro') or '') == dominante:
                confirmados.add(u)

    provaveis = sorted(
        (por_url[u] for u, m in motivos.items() if u not in confirmados),
        key=lambda i: (_ORDEM_MOTIVO.get(motivos[i['url_anuncio']], 9), i.get('preco_m2') or 0),
    )[:MAX_PROVAVEIS]

    nivel = _nivel_mais_fraco([motivos[u] for u in confirmados], NIVEL_NOME)
    resposta = await _montar_resposta(
        db, cidade, itens, [por_url[u] for u in confirmados], motivos, sinais, provaveis, nivel,
    )
    resposta['alvo'] = {
        'nome': nome, 'endereco': endereco,
        'latitude': geo['latitude'] if geo else None,
        'longitude': geo['longitude'] if geo else None,
        'endereco_encontrado': geo.get('descricao') if geo else None,
        # False = o mapa achou só a rua; a busca por raio não foi usada.
        'geocodificacao_precisa': bool(geo and geo.get('precisa')),
    }
    # Prédios onde caíram os prováveis — rua digitada sem número costuma ter
    # alguns poucos prédios com anúncio, e escolher um deles é mais útil que
    # ler 60 anúncios soltos. Cada sugestão abre o dossiê pelo grupo_id.
    contagem = Counter(
        por_url[u].get('grupo_id') for u, m in motivos.items()
        if u not in confirmados and por_url[u].get('grupo_id')
    )
    resposta['sugestoes'] = [resumos[g] for g, _ in contagem.most_common(8) if g in resumos]
    resposta['total_historico'] = len(itens)
    return resposta


def bairro_dominante(resposta: dict) -> str | None:
    """
    Bairro mais frequente no que a procura achou — confirmados primeiro,
    depois os prédios sugeridos, depois os prováveis. É o bairro da coleta
    direcionada: vem na divisão de bairros dos portais, não na do OSM.
    """
    for fonte in (
        [a.get('bairro') for a in resposta.get('anuncios') or []],
        [s.get('bairro') for s in resposta.get('sugestoes') or []],
        [a.get('bairro') for a in resposta.get('provaveis') or []],
    ):
        contagem = Counter(b for b in fonte if b)
        if contagem:
            return contagem.most_common(1)[0][0]
    return None
