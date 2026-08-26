"""Normalização de texto compartilhada — antes reimplementada, de forma
divergente, em mais de dez arquivos do backend.

Duas funções, não uma: `sem_acento` só remove acento (preserva caixa) e é o
que a maioria dos scrapers usa para montar slug de URL, encadeando `.lower()`
conforme cada caso precisa. `normalizar` acrescenta minúsculo + trim — é o que
os módulos de comparação (bairro, dedup, cache de fontes) usam para decidir
se dois textos "são o mesmo".
"""
import unicodedata


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    try:
        return sem_acento(texto).lower().strip()
    except Exception:
        # Mesma rede de segurança que scraper/parser.py::normalizar_cidade já
        # tinha: um texto que não é string não pode derrubar o chamador.
        return texto.lower().strip()
