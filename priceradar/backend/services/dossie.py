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


def _anuncio_saida(item: dict, mediana: float | None, ultimas: dict, motivo: str | None = None,
                   classe: str | None = None, evidencias: list[str] | None = None) -> dict:
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
        'classe_vinculo': classe or ('provavel' if motivo in {'texto', 'rua', 'anexo'} else 'direto'),
        'evidencias': evidencias or ([] if motivo is None else [motivo]),
        'fontes_identidade': sorted(set(item.get('fontes_identidade') or [f"listagem:{item.get('portal') or 'desconhecido'}"])),
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
                           nivel: str | None = None, classes: dict[str, str] | None = None,
                           evidencias: dict[str, list[str]] | None = None) -> dict:
    ultima = _ultimas_coletas(itens_hist)
    resumo = resumir_grupo(escolhidos, sinais, nivel, provaveis) if escolhidos else None
    mediana = resumo['preco_m2_mediana'] if resumo else None
    anuncios = sorted(
        (_anuncio_saida(i, mediana, ultima, motivos.get(i['url_anuncio']),
                        (classes or {}).get(i['url_anuncio']), (evidencias or {}).get(i['url_anuncio']))
         for i in escolhidos),
        key=lambda a: (not a['ativo'], a['preco_m2'] or 0),
    )
    urls = {chave_url(i['url_anuncio']) or i['url_anuncio'] for i in escolhidos}
    bairros = sorted({i['bairro'] for i in escolhidos if i.get('bairro')})
    return {
        'grupo': resumo,
        'anuncios': anuncios,
        'ativos': sum(1 for a in anuncios if a['ativo']),
        'provaveis': [
            _anuncio_saida(i, mediana, ultima, motivos.get(i['url_anuncio']),
                            (classes or {}).get(i['url_anuncio'], 'provavel'),
                            (evidencias or {}).get(i['url_anuncio']))
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


def _compativel_bairro(valor: str | None, alvos: set[str]) -> bool | None:
    if not valor or not alvos:
        return None
    atual = normalizar(valor)
    return any(atual in alvo or alvo in atual for alvo in alvos)


def avaliar_evidencias(item: dict, alvo: dict, referencia: dict | None = None) -> dict:
    """Registra todos os sinais e conflitos de uma linha, sem decidir isoladamente.

    A promoção para ``corroborado`` acontece depois, quando se conhece a
    convergência entre anúncios. Aqui só ``direto`` pode ser decidido.
    """
    rua, numero = normalizar_rua(item.get('endereco'))
    ruas = {r for r in (alvo.get('rua'), alvo.get('rua_referencia')) if r}
    numeros = {n for n in (alvo.get('numero'), alvo.get('numero_referencia')) if n}
    bairros = {b for b in (alvo.get('bairro'), alvo.get('bairro_referencia')) if b}
    nomes = [n for n in (alvo.get('nome'), *(alvo.get('aliases_normalizados') or [])) if n]
    frases = [f for f in (alvo.get('frase'), *(alvo.get('frases_aliases') or [])) if f]

    codigos: set[str] = set()
    conflitos: list[str] = []
    fontes = set(item.get('fontes_identidade') or [f"listagem:{item.get('portal') or 'desconhecido'}"])

    rua_ok = bool(rua and rua in ruas)
    numero_ok = bool(rua_ok and numero and numero in numeros)
    if rua_ok:
        codigos.add('rua')
    if numero_ok:
        codigos.add('numero')
    if rua_ok and numero and numeros and numero not in numeros:
        conflitos.append('número diferente na mesma rua')

    bairro_ok = _compativel_bairro(item.get('bairro'), bairros)
    if bairro_ok:
        codigos.add('bairro')
    elif bairro_ok is False:
        conflitos.append('bairro incompatível')

    geo = alvo.get('geo')
    tem_coord = item.get('origem_coordenada') == 'exata' and item.get('latitude') is not None \
        and item.get('longitude') is not None
    dist = (distancia_m(geo['latitude'], geo['longitude'], float(item['latitude']),
                        float(item['longitude'])) if geo and tem_coord else None)
    if geo and geo.get('precisa') and dist is not None and dist <= alvo['raio_m']:
        codigos.add('coordenada')
        if rua and ruas and rua not in ruas:
            conflitos.append('ponto próximo em rua diferente')
    elif dist is not None and dist > 200:
        conflitos.append('distância superior a 200 m')

    nome_item = normalizar_nome(item.get('nome_empreendimento'))
    nome_ok = bool(nome_item and nomes and max(similaridade_nome(nome_item, n) for n in nomes) >= .9)
    if nome_ok:
        codigos.add('nome_estruturado')
    elif nome_item and nomes and len(_tokens(nome_item)) >= 2 \
            and max(similaridade_nome(nome_item, n) for n in nomes) < .45:
        conflitos.append('nome específico conflitante')

    texto = ' '.join(_tokens(
        f"{item.get('nome_anuncio') or ''} {item.get('descricao') or ''}"
    ))
    if frases and any(f" {frase} " in f" {texto} " for frase in frases):
        codigos.add('mencao_nome')

    construtora_ref = normalizar((referencia or {}).get('construtora') or '')
    if construtora_ref and item.get('construtora') \
            and normalizar(item['construtora']) == construtora_ref:
        codigos.add('construtora')

    bloqueado = bool(conflitos)
    local_ok = numero_ok or 'coordenada' in codigos or rua_ok or bairro_ok is True
    direto = not bloqueado and (
        numero_ok
        or ('coordenada' in codigos)
        or (nome_ok and local_ok)
    )
    if referencia and codigos & {'nome_estruturado', 'mencao_nome', 'rua', 'numero', 'bairro'}:
        fontes.add(f"oficial:{referencia.get('fonte') or 'catalogo'}")

    rotulos = {
        'nome_estruturado': 'nome estruturado compatível',
        'mencao_nome': 'menção textual exata ao nome',
        'rua': 'rua compatível',
        'numero': 'número do endereço compatível',
        'coordenada': f"coordenada precisa a {round(dist or 0)} m",
        'bairro': 'bairro compatível',
        'construtora': 'construtora compatível',
    }
    evidencias = [rotulos[c] for c in ('nome_estruturado', 'mencao_nome', 'rua', 'numero',
                                        'coordenada', 'bairro', 'construtora') if c in codigos]
    evidencias.extend(f"conflito: {c}" for c in conflitos)
    legado = ('endereco' if numero_ok else 'coordenada' if 'coordenada' in codigos
              else 'nome' if nome_ok else 'texto' if 'mencao_nome' in codigos
              else 'rua' if rua_ok else None)
    return {
        'codigos': codigos, 'evidencias': evidencias, 'conflitos': conflitos,
        'classe': 'direto' if direto else 'provavel', 'motivo': legado,
        'fontes': sorted(fontes),
    }


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
    aprofundar: bool = False,
) -> dict:
    from repositories.empreendimento_repo import historico_da_cidade
    from services.catalogos_oficiais import buscar_referencia_oficial
    from services.detalhes_anuncios import enriquecer_candidatos
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
    diagnostico = {
        'candidatos_avaliados': len(itens), 'candidatos_detalhe': 0,
        'detalhes_lidos': 0, 'acertos_cache': 0, 'falhas_por_fonte': {},
    }
    referencia = None
    conflito_oficial = None
    if aprofundar:
        referencia = await buscar_referencia_oficial(db, cidade, nome, diagnostico)
    rua_ref, numero_ref = normalizar_rua((referencia or {}).get('endereco'))
    bairro_ref = normalizar((referencia or {}).get('bairro') or '') or None
    if referencia:
        if rua and rua_ref and rua != rua_ref:
            conflito_oficial = 'o endereço informado e o catálogo oficial indicam ruas diferentes'
        elif rua and rua_ref and rua == rua_ref and numero and numero_ref and numero != numero_ref:
            conflito_oficial = 'o endereço informado e o catálogo oficial indicam números diferentes'
        elif bairro and bairro_ref and not _compativel_bairro(bairro, {bairro_ref}):
            conflito_oficial = 'o bairro informado diverge do catálogo oficial'
    if conflito_oficial:
        # A referência continua visível, mas não fornece nenhum sinal para a
        # promoção. O endereço do usuário jamais é sobrescrito.
        alvo.update(rua_referencia=None, numero_referencia=None, bairro_referencia=None,
                    aliases_normalizados=[], frases_aliases=[])
    else:
        aliases = [(referencia or {}).get('nome'), *((referencia or {}).get('aliases') or [])]
        alvo.update(
            rua_referencia=rua_ref, numero_referencia=numero_ref,
            bairro_referencia=bairro_ref,
            aliases_normalizados=[normalizar_nome(n) for n in aliases if n],
            frases_aliases=[f for f in (_frase(n) for n in aliases if n) if f],
        )

    if aprofundar and itens:
        avaliacoes_pre = {i['url_anuncio']: avaliar_evidencias(i, alvo, referencia if not conflito_oficial else None)
                          for i in itens}
        candidatos = [i for i in itens if avaliacoes_pre[i['url_anuncio']]['codigos']]
        if alvo.get('bairro') or alvo.get('bairro_referencia'):
            bairros_alvo = {b for b in (alvo.get('bairro'), alvo.get('bairro_referencia')) if b}
            candidatos.extend(i for i in itens if i not in candidatos and _compativel_bairro(i.get('bairro'), bairros_alvo))
        await enriquecer_candidatos(db, candidatos or itens, diagnostico)

    membros, anexos, resumos = _membros_por_grupo(itens)
    por_url = {i['url_anuncio']: i for i in itens}
    avaliacoes = {u: avaliar_evidencias(item, alvo, referencia if not conflito_oficial else None)
                  for u, item in por_url.items()}
    motivos = {u: a['motivo'] for u, a in avaliacoes.items() if a['motivo']}
    classes = {u: a['classe'] for u, a in avaliacoes.items() if a['codigos']}
    evidencias = {u: list(a['evidencias']) for u, a in avaliacoes.items() if a['codigos']}
    for u, avaliacao in avaliacoes.items():
        por_url[u]['fontes_identidade'] = avaliacao['fontes']

    # Havendo pelo menos uma linha com rua+número exatos, ela prevalece sobre
    # anúncios apenas no mesmo ponto (uma esquina pode compartilhar coordenada).
    if (alvo.get('numero') or alvo.get('numero_referencia')) and any(
        'numero' in a['codigos'] and not a['conflitos'] for a in avaliacoes.values()
    ):
        for u, avaliacao in avaliacoes.items():
            if classes.get(u) == 'direto' and 'coordenada' in avaliacao['codigos'] \
                    and 'numero' not in avaliacao['codigos']:
                classes[u] = 'provavel'
                evidencias[u].append('fora do núcleo: há anúncio com rua e número exatos')

    # Nome sem localização: duas ou mais ocorrências no mesmo bairro se
    # corroboram. Uma ocorrência isolada continua provável.
    if alvo.get('nome') and not (alvo.get('rua') or alvo.get('rua_referencia') or alvo.get('bairro') or geo):
        por_nome = [u for u, a in avaliacoes.items() if 'nome_estruturado' in a['codigos'] and not a['conflitos']]
        contagem_bairro = Counter(normalizar(por_url[u].get('bairro') or '') for u in por_nome)
        contagem_bairro.pop('', None)
        if contagem_bairro:
            dominante, quantidade = contagem_bairro.most_common(1)[0]
            if quantidade >= 2:
                for u in por_nome:
                    if normalizar(por_url[u].get('bairro') or '') == dominante:
                        classes[u] = 'corroborado'
                        evidencias[u].append('nome repetido em anúncios do mesmo bairro')

    confirmados = {u for u, classe in classes.items() if classe in {'direto', 'corroborado'}}
    # O elo nome ↔ endereço é formado pelo alvo informado e, quando não há
    # divergência, pelo catálogo oficial. Sinais isolados só sobem quando há
    # convergência entre anúncios diferentes.
    nome_urls = {u for u, a in avaliacoes.items() if not a['conflitos'] and
                 a['codigos'] & {'nome_estruturado', 'mencao_nome'}}
    local_urls = {u for u, a in avaliacoes.items() if not a['conflitos'] and
                  a['codigos'] & {'rua', 'numero', 'coordenada'}}
    ponte = bool((referencia and not conflito_oficial) or
                 (alvo.get('nome') and (alvo.get('rua') or alvo.get('rua_referencia'))))
    if ponte and nome_urls and local_urls:
        for u in nome_urls | local_urls:
            if classes.get(u) != 'direto':
                classes[u] = 'corroborado'
                confirmados.add(u)
                evidencias.setdefault(u, []).append('nome e endereço corroborados entre anúncios relacionados')
                if referencia and not conflito_oficial:
                    evidencias[u].append(f"identidade confirmada pelo catálogo {referencia['fonte'].upper()}")

    # Uma menção textual entra quando converge com o bairro de um núcleo já
    # confirmado (comportamento antigo, agora explicitamente corroborado).
    bairros_conf = Counter(normalizar(por_url[u].get('bairro') or '') for u in confirmados)
    bairros_conf.pop('', None)
    dominante = bairros_conf.most_common(1)[0][0] if bairros_conf else None
    if dominante and alvo.get('frase') and len(alvo['frase'].split()) >= 2:
        for u, avaliacao in avaliacoes.items():
            if u not in confirmados and not avaliacao['conflitos'] and 'mencao_nome' in avaliacao['codigos'] \
                    and normalizar(por_url[u].get('bairro') or '') == dominante:
                classes[u] = 'corroborado'
                confirmados.add(u)
                evidencias[u].append('menção ao nome no mesmo bairro do núcleo confirmado')

    sinais = {motivos[u] for u in confirmados if u in motivos}
    # O resto do prédio de cada confirmado entra também, mas um conflito
    # explícito nunca é apagado pelo agrupamento.
    for u in list(confirmados):
        gid = por_url[u].get('grupo_id')
        if gid not in resumos or por_url[u].get('vinculo_grupo') == 'provavel':
            continue
        nivel_grupo = resumos[gid]['nivel']
        motivo_grupo = {NIVEL_PREDIO: 'mesmo_predio', NIVEL_LOCAL: 'mesmo_local'}.get(nivel_grupo, 'nome')
        for m in membros.get(gid, []):
            mu = m['url_anuncio']
            if mu not in confirmados and not avaliacoes[mu]['conflitos']:
                confirmados.add(mu)
                classes[mu] = 'corroborado'
                motivos.setdefault(mu, motivo_grupo)
                evidencias.setdefault(mu, []).append('ligado ao núcleo pelo agrupamento do mesmo empreendimento')
        # Anexos do prédio: prováveis, fora do preço.
        for m in anexos.get(gid, []):
            if m['url_anuncio'] not in confirmados:
                motivos[m['url_anuncio']] = 'anexo'
        sinais |= set(resumos[gid]['sinais'])
    sinais &= {'endereco', 'coordenada', 'nome'}

    provaveis = sorted(
        (por_url[u] for u in classes if u not in confirmados),
        # Bairro/construtora também são evidências, mas não têm equivalente no
        # campo legado `motivo`. Continuam prováveis e vão ao fim da lista.
        key=lambda i: (_ORDEM_MOTIVO.get(motivos.get(i['url_anuncio']), 9), i.get('preco_m2') or 0),
    )[:MAX_PROVAVEIS]

    nivel = _nivel_mais_fraco([motivos[u] for u in confirmados], NIVEL_NOME)
    resposta = await _montar_resposta(
        db, cidade, itens, [por_url[u] for u in confirmados], motivos, sinais, provaveis, nivel,
        classes, evidencias,
    )
    resposta['alvo'] = {
        'nome': nome, 'endereco': endereco,
        'latitude': geo['latitude'] if geo else None,
        'longitude': geo['longitude'] if geo else None,
        'endereco_encontrado': geo.get('descricao') if geo else None,
        # False = o mapa achou só a rua; a busca por raio não foi usada.
        'geocodificacao_precisa': bool(geo and geo.get('precisa')),
        'conflito_referencia_oficial': conflito_oficial,
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
    resposta['referencia_oficial'] = referencia
    resposta['resumo_vinculos'] = {
        'direto': sum(1 for u in confirmados if classes.get(u) == 'direto'),
        'corroborado': sum(1 for u in confirmados if classes.get(u) == 'corroborado'),
        'provavel': len(provaveis),
        'participam_mediana': len(confirmados),
    }
    resposta['diagnostico_especifico'] = diagnostico
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
