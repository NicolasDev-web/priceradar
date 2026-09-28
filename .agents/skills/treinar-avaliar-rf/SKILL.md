# Skill: treinar-avaliar-rf

Treina e avalia os modelos Random Forest (dedup de pares e qualidade/enriquecimento)
com métricas reais. Garante que o modelo não está descartando anúncios válidos.

## Como usar

```
/treinar-avaliar-rf [dedup|qualidade]
```

## Avaliação do RF Refiner (qualidade)

Execute em `priceradar/backend/` com o venv ativado:

```python
import asyncio, os, sys, json
from pathlib import Path

for linha in Path('.env').read_text().splitlines():
    if '=' in linha and not linha.startswith('#'):
        k, v = linha.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, '.')
from services.rf_refiner import refinar_com_random_forest

# Carrega listings de uma busca recente ou gera mock
from scraper.chavesnamao import scrape_chavesnamao
listings = asyncio.run(scrape_chavesnamao("Fortaleza, CE", 200000, 800000, None))
print(f"Entradas: {len(listings)}")

if len(listings) >= 5:
    filtrados = refinar_com_random_forest(listings[:])
    taxa_descarte = 1 - len(filtrados) / len(listings)
    print(f"Aprovados : {len(filtrados)}")
    print(f"Descartados: {len(listings) - len(filtrados)} ({taxa_descarte:.1%})")
    scores = [l.get('rf_score', 0) for l in filtrados]
    print(f"Score médio: {sum(scores)/len(scores):.3f}")
    # Alerta se taxa de descarte > 20% com poucos dados
    if taxa_descarte > 0.20 and len(listings) < 30:
        print("ALERTA: taxa de descarte alta para amostra pequena — revisar limiares")
```

## Avaliação do Deduplicador (pares)

```python
from services.deduplicador import deduplicar_cross_portal, _score_determinista

# Simula duplicata cross-portal
dup_a = {'portal': 'vivareal', 'preco': 350000, 'area_m2': 65, 'quartos': 2, 'bairro': 'Meireles', 'nome_anuncio': 'Apt 2q Meireles'}
dup_b = {'portal': 'zapimoveis', 'preco': 351000, 'area_m2': 65, 'quartos': 2, 'bairro': 'Meireles', 'nome_anuncio': 'Apartamento 2 quartos Meireles'}
dif = {'portal': 'chavesnamao', 'preco': 420000, 'area_m2': 80, 'quartos': 3, 'bairro': 'Aldeota', 'nome_anuncio': 'Apto 3q Aldeota'}

score_dup = _score_determinista(dup_a, dup_b)
score_dif = _score_determinista(dup_a, dif)
print(f"Score par duplicado  : {score_dup:.3f} (esperado > 0.85)")
print(f"Score par diferente  : {score_dif:.3f} (esperado < 0.50)")

resultado = deduplicar_cross_portal([dup_a, dup_b, dif])
print(f"Antes: 3, Depois: {len(resultado)} (esperado: 2)")
```

## Critério de sucesso

- Taxa de descarte do RF Refiner < 20% para amostras < 30 anúncios
- Score de par duplicado > 0.85
- Score de par diferente < 0.50
- Número de empreendimentos únicos não cai indevidamente após dedup
