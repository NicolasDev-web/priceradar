"""Gera a lista de cidades usada no autocomplete do frontend.

Fonte: IBGE (APIs públicas e gratuitas).
  - localidades/municipios  → 5.571 municípios com UF
  - agregados/4714 (Censo 2022) → população por município

Por que gerar um arquivo em vez de consultar a API em tempo de execução:
o navegador teria problema de CORS, a busca ficaria dependente do IBGE estar
no ar, e o dado só muda a cada censo. 657 cidades cabem em ~15 KB no bundle.

Rode sob demanda:
    venv/Scripts/python.exe scripts/gerar_cidades.py
"""
import json
import sys
import unicodedata
from pathlib import Path

import httpx

# Abaixo deste corte praticamente não há mercado de apartamento, e sugerir
# municípios sem oferta só atrapalha quem digita. Baixe o valor se aparecer
# uma praça menor recorrente — a busca continua aceitando qualquer cidade
# digitada por extenso, o autocomplete apenas não a sugere.
POPULACAO_MINIMA = 50_000

URL_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
URL_POPULACAO = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/4714"
    "/periodos/2022/variaveis/93?localidades=N6[all]"
)

DESTINO = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "cidades.ts"


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _uf_do_municipio(m: dict) -> str:
    """A UF fica em caminhos diferentes conforme a época do cadastro."""
    micro = m.get("microrregiao") or {}
    meso = micro.get("mesorregiao") or {}
    uf = (meso.get("UF") or {}).get("sigla")
    if uf:
        return uf
    imediata = m.get("regiao-imediata") or {}
    intermediaria = imediata.get("regiao-intermediaria") or {}
    return (intermediaria.get("UF") or {}).get("sigla", "")


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
    sem_populacao = 0
    for m in municipios:
        uf = _uf_do_municipio(m)
        if not uf:
            continue
        nome = m["nome"]
        pop = populacoes.get(f"{nome} - {uf}")
        if pop is None:
            sem_populacao += 1
            continue
        if pop >= POPULACAO_MINIMA:
            cidades.append((nome, uf, pop))

    # Ordena por população: quem digita "sao" quer São Paulo antes de São
    # Sebastião do Passé.
    cidades.sort(key=lambda c: -c[2])

    linhas = ",\n".join(
        f'  ["{nome}","{uf}","{_sem_acento(nome).lower()}"]' for nome, uf, _ in cidades
    )
    conteudo = f"""// GERADO POR backend/scripts/gerar_cidades.py — não edite à mão.
//
// Municípios brasileiros com {POPULACAO_MINIMA:,} habitantes ou mais (IBGE, Censo 2022),
// ordenados por população. Formato: [nome, UF, nome sem acento para busca].
//
// Esta lista SUGERE, não restringe: o campo de cidade continua aceitando
// qualquer município digitado por extenso.
export const CIDADES: readonly (readonly [string, string, string])[] = [
{linhas},
]
""".replace("{:,}".format(POPULACAO_MINIMA), f"{POPULACAO_MINIMA:,}".replace(",", "."))

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(conteudo, encoding="utf-8")

    print(f"\n{len(cidades)} cidades com {POPULACAO_MINIMA:,} hab ou mais".replace(",", "."))
    print(f"  descartadas por falta de população: {sem_populacao}")
    print(f"  arquivo: {DESTINO}  ({DESTINO.stat().st_size / 1024:.0f} KB)")
    print(f"  maiores: {', '.join(f'{n}/{u}' for n, u, _ in cidades[:5])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
