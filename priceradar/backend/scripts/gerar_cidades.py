"""Gera a lista de cidades usada no autocomplete do frontend.

Fonte: IBGE (APIs públicas e gratuitas).
  - localidades/municipios  → 5.571 municípios com UF e região
  - agregados/4714 (Censo 2022) → população por município

Por que gerar um arquivo em vez de consultar a API em tempo de execução:
o navegador teria problema de CORS, a busca ficaria dependente do IBGE estar
no ar, e o dado só muda a cada censo.

Rode sob demanda:
    venv/Scripts/python.exe scripts/gerar_cidades.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.texto import sem_acento  # noqa: E402

# O PriceRadar atende o Nordeste. Sugerir município de outra região só ocupa
# espaço na lista e no bundle — e a busca continua aceitando qualquer cidade
# digitada por extenso, o autocomplete apenas não a sugere.
REGIAO = "Nordeste"

# Sem corte de população: com o recorte regional a lista inteira cabe em ~75 KB,
# e um corte deixaria PI, SE e RN com 5, 7 e 9 cidades — praças onde o time
# atua ficariam de fora da sugestão.
POPULACAO_MINIMA = 0

URL_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
URL_POPULACAO = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/4714"
    "/periodos/2022/variaveis/93?localidades=N6[all]"
)

DESTINO = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "cidades.ts"


def _uf_bruta(m: dict) -> dict:
    """O nó `UF` fica em caminhos diferentes conforme a época do cadastro."""
    micro = m.get("microrregiao") or {}
    meso = micro.get("mesorregiao") or {}
    uf = meso.get("UF") or {}
    if uf.get("sigla"):
        return uf
    imediata = m.get("regiao-imediata") or {}
    intermediaria = imediata.get("regiao-intermediaria") or {}
    return intermediaria.get("UF") or {}


def uf_do_municipio(m: dict) -> str:
    return _uf_bruta(m).get("sigla", "")


def regiao_do_municipio(m: dict) -> str:
    """Nome da região ("Nordeste", "Sudeste", ...) — vem junto com a UF."""
    return (_uf_bruta(m).get("regiao") or {}).get("nome", "")


def baixar_populacoes() -> dict[str, int]:
    """Mapa "Cidade - UF" → população."""
    dados = httpx.get(URL_POPULACAO, timeout=120).json()
    series = dados[0]["resultados"][0]["series"]
    populacoes: dict[str, int] = {}
    for s in series:
        nome = s["localidade"]["nome"]
        try:
            populacoes[nome] = int(next(iter(s["serie"].values())))
        except (StopIteration, TypeError, ValueError):
            continue
    return populacoes


def main() -> int:
    print("Baixando municípios do IBGE...")
    municipios = httpx.get(URL_MUNICIPIOS, timeout=120).json()
    print(f"  {len(municipios)} municípios")

    print("Baixando população (Censo 2022)...")
    populacoes = baixar_populacoes()
    print(f"  {len(populacoes)} com população")

    cidades = []
    sem_populacao: list[str] = []
    for m in municipios:
        uf = uf_do_municipio(m)
        if not uf or regiao_do_municipio(m) != REGIAO:
            continue
        nome = m["nome"]
        pop = populacoes.get(f"{nome} - {uf}")
        if pop is None:
            # O join é por chave textual ("Nome - UF"): uma grafia divergente
            # entre as duas APIs do IBGE derruba o município. Ele entra mesmo
            # assim, no fim da lista — sumir calado de uma praça é pior que
            # aparecer fora de ordem.
            sem_populacao.append(f"{nome}/{uf}")
            pop = 0
        if pop >= POPULACAO_MINIMA:
            cidades.append((nome, uf, pop))

    # Ordena por população: quem digita "sao" quer São Luís antes de São
    # Sebastião do Passé.
    cidades.sort(key=lambda c: -c[2])

    linhas = ",\n".join(
        f'  ["{nome}","{uf}","{sem_acento(nome).lower()}"]' for nome, uf, _ in cidades
    )
    conteudo = f"""// GERADO POR backend/scripts/gerar_cidades.py — não edite à mão.
//
// Todos os municípios do {REGIAO} (IBGE, Censo 2022), ordenados por população.
// Formato: [nome, UF, nome sem acento para busca].
//
// O PriceRadar atende o {REGIAO} — por isso o recorte regional. Ainda assim
// esta lista SUGERE, não restringe: o campo de cidade continua aceitando
// qualquer município do país digitado por extenso.
export const CIDADES: readonly (readonly [string, string, string])[] = [
{linhas},
]
"""

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(conteudo, encoding="utf-8")

    por_uf: dict[str, int] = {}
    for _, uf, _ in cidades:
        por_uf[uf] = por_uf.get(uf, 0) + 1

    print(f"\n{len(cidades)} municípios do {REGIAO}")
    print(f"  por UF: {dict(sorted(por_uf.items()))}")
    if sem_populacao:
        print(f"  SEM população no Censo (mantidos, ordenados por último): {sem_populacao}")
    print(f"  arquivo: {DESTINO}  ({DESTINO.stat().st_size / 1024:.0f} KB)")
    print(f"  maiores: {', '.join(f'{n}/{u}' for n, u, _ in cidades[:5])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
