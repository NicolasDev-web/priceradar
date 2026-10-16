"""Diagnóstico manual da procura específica sobre a base real.

Exemplo:
  python -m scripts.diagnosticar_empreendimento --cidade "Fortaleza, CE" \
    --nome "Parque Marista" --endereco "Rua Conselheiro Tristão, 60"
"""
from __future__ import annotations

import argparse
import asyncio
import json

from database.connection import AsyncSessionLocal, init_db
from repositories.empreendimento_repo import historico_da_cidade
from services.dossie import procurar_empreendimento


async def executar(args) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        antes = {i["url_anuncio"]: i for i in await historico_da_cidade(db, args.cidade)}
        resposta = await procurar_empreendimento(
            db, args.cidade, args.nome, args.endereco, bairro=args.bairro,
            aprofundar=not args.sem_aprofundar,
        )
    linhas = []
    for anuncio in [*resposta["anuncios"], *resposta["provaveis"]]:
        original = antes.get(anuncio["url_anuncio"], {})
        linhas.append({
            "url": anuncio["url_anuncio"],
            "portal": anuncio["portal"],
            "antes": {k: original.get(k) for k in ("nome_empreendimento", "endereco", "bairro", "descricao")},
            "depois": {k: anuncio.get(k) for k in ("nome_empreendimento", "endereco", "bairro")},
            "classe_final": anuncio["classe_vinculo"],
            "evidencias": anuncio["evidencias"],
            "fontes_identidade": anuncio["fontes_identidade"],
        })
    print(json.dumps({
        "referencia_oficial": resposta.get("referencia_oficial"),
        "resumo_vinculos": resposta.get("resumo_vinculos"),
        "diagnostico_especifico": resposta.get("diagnostico_especifico"),
        "candidatos": linhas,
    }, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cidade", required=True)
    parser.add_argument("--nome")
    parser.add_argument("--endereco")
    parser.add_argument("--bairro")
    parser.add_argument("--sem-aprofundar", action="store_true")
    args = parser.parse_args()
    if not args.nome and not args.endereco:
        parser.error("informe --nome ou --endereco")
    asyncio.run(executar(args))


if __name__ == "__main__":
    main()

