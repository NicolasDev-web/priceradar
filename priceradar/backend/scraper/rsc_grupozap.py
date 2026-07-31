"""Coordenada e bairro estruturado das páginas do Grupo ZAP (VivaReal e Zap).

As duas páginas trazem, além do JSON-LD que os scrapers já leem, o payload
React Server Components do Next.js, espalhado em chamadas
`self.__next_f.push([1,"..."])`. Cada anúncio aparece ali com bem mais dado do
que no JSON-LD:

    "href":"https://www.vivareal.com.br/imovel/...-id-2585905966/",
    "address":{"city":"Fortaleza","stateAcronym":"CE","neighborhood":"Meireles",
               "isApproximateLocation":false,"streetNumber":"1000",
               "street":"Travessa Antônio Augusto",
               "coordinates":{"latitude":-3.724628,"longitude":-38.511239}}

Duas coisas que o JSON-LD não dá:

1. **Coordenada.** Sem ela não há mapa — nem geocodificando, porque o
   `streetAddress` do JSON-LD costuma vir sem número.
2. **Bairro de verdade.** No JSON-LD, `addressLocality` é a cidade e o bairro
   não existe em campo nenhum — por isso `extrair_bairro_do_slug()` o adivinha
   a partir da URL, acertando ~83% e sempre sem acento. Aqui ele vem
   estruturado e acentuado: "Aracapé", "Cocó", "Parquelândia".

Medido em 30/07/2026, Fortaleza, 1 página: 41 objetos no RSC do VivaReal e 37
no do Zap, contra 30 anúncios no JSON-LD de cada. O join por `href` fechou
30/30 nos dois portais.

Por que regex e não `json.loads`: o payload é quebrado em dezenas de chunks
que só formam JSON válido depois de reconstruídos na ordem certa pelo runtime
do Next — um deles pode cortar no meio de um objeto. A varredura por padrão
com janela limitada não depende dessa reconstrução, e o formato não é
documentado: se a Grupo ZAP mudar o payload, isto precisa falhar devolvendo
vazio, não explodindo. Quem chama trata dict vazio como "sem coordenada" e
segue com o comportamento antigo.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Os chunks do RSC. O conteúdo vem com aspas escapadas (\") porque está dentro
# de uma string JavaScript.
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', re.S)

# href → ... → neighborhood → ... → isApproximateLocation → ... → coordinates.
# As janelas são limitadas de propósito: sem o teto, um anúncio sem coordenada
# casaria com a coordenada do anúncio seguinte e plotaria o pin no lugar errado.
# `isApproximateLocation` é opcional — nem todo anúncio traz.
_ANUNCIO = re.compile(
    r'"href":"(?P<href>https://[^"]+)".{0,600}?'
    r'"neighborhood":"(?P<bairro>[^"]*)"'
    r'(?:.{0,200}?"isApproximateLocation":(?P<aproximada>true|false))?'
    r'.{0,300}?"coordinates":\{"latitude":(?P<lat>-?\d+\.?\d*),'
    r'"longitude":(?P<lng>-?\d+\.?\d*)\}',
    re.S,
)

# Fortaleza fica em -3.7, -38.5; Salvador em -12.9, -38.5. O Brasil inteiro
# cabe nesta caixa. Serve para barrar (0,0) e coordenada de outro país, que
# apareceriam no mapa como um pin no Golfo da Guiné.
_LAT_BR = (-34.0, 6.0)
_LNG_BR = (-74.0, -34.0)


def chave_url(url: str) -> str:
    """Normaliza a URL para servir de chave de join: sem query, sem barra final."""
    return (url or "").split("?")[0].split("#")[0].rstrip("/")


def _payload_rsc(html: str) -> str:
    """Concatena os chunks do RSC e desfaz o escape das aspas."""
    return "".join(c.replace('\\"', '"') for c in _CHUNK.findall(html))


def indexar_localizacoes(html: str) -> dict[str, dict]:
    """
    Mapa `chave_url(href)` → `{latitude, longitude, bairro, aproximada}`.

    Devolve `{}` quando o HTML não tem payload RSC ou quando o formato mudou —
    nunca levanta exceção. Sem localização o anúncio continua valendo para o
    preço/m², que é o número que sustenta o produto.
    """
    try:
        payload = _payload_rsc(html)
        if not payload:
            return {}

        indice: dict[str, dict] = {}
        for m in _ANUNCIO.finditer(payload):
            try:
                lat = float(m.group("lat"))
                lng = float(m.group("lng"))
            except (TypeError, ValueError):
                continue
            if not (_LAT_BR[0] <= lat <= _LAT_BR[1] and _LNG_BR[0] <= lng <= _LNG_BR[1]):
                continue

            bairro = (m.group("bairro") or "").strip()
            indice[chave_url(m.group("href"))] = {
                "latitude": lat,
                "longitude": lng,
                "bairro": bairro or None,
                # O portal declara quando o pin é do bairro e não do endereço.
                "aproximada": m.group("aproximada") == "true",
            }
        return indice
    except Exception as e:  # o formato não é documentado; degradar é a regra
        logger.warning(f"RSC Grupo ZAP: não foi possível indexar localizações: {e}")
        return {}


def aplicar_localizacao(item: dict, indice: dict[str, dict]) -> None:
    """
    Enriquece um anúncio já montado com o que o RSC souber sobre ele.

    O bairro estruturado tem precedência sobre o extraído do slug: vem do
    portal em vez de heurística, e vem acentuado. Se o RSC não conhece a URL,
    nada muda — o item segue exatamente como o JSON-LD o montou.
    """
    loc = indice.get(chave_url(item.get("url_anuncio", "")))
    if not loc:
        return

    item["latitude"] = loc["latitude"]
    item["longitude"] = loc["longitude"]
    item["origem_coordenada"] = "aproximada_portal" if loc["aproximada"] else "exata"
    if loc["bairro"]:
        item["bairro"] = loc["bairro"]
