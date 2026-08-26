"""Progresso de uma busca em andamento, para o frontend fazer polling durante
o scraping (30-90s). Registro em memória — processo único (uvicorn sem
--workers>1), mesmo padrão de `threading.Lock` + dict de módulo já usado em
`services/bairros.py`. Não precisa de Redis nem de fila: o volume é de uma
busca por vez, de um usuário por vez.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Jobs concluídos somem do registro depois disso — sem essa purga, o dict
# cresceria para sempre num processo de vida longa.
_TTL_SEGUNDOS = 15 * 60


@dataclass
class StatusPortal:
    esperadas: int = 0
    concluidas: int = 0
    itens: int = 0
    erro: bool = False


@dataclass
class Job:
    portais: dict[str, StatusPortal]
    criado_em: float = field(default_factory=time.time)
    concluido_em: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _purgar() -> None:
    limite = time.time() - _TTL_SEGUNDOS
    for job_id in [j for j, job in _jobs.items() if job.concluido_em and job.concluido_em < limite]:
        del _jobs[job_id]


def criar(job_id: str, portais_esperados: dict[str, int]) -> None:
    with _lock:
        _purgar()
        _jobs[job_id] = Job(portais={
            portal: StatusPortal(esperadas=n) for portal, n in portais_esperados.items()
        })


def marcar_tarefa_concluida(job_id: str, portal: str, itens: int | None, erro: bool) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        status = job.portais.setdefault(portal, StatusPortal())
        status.concluidas += 1
        if erro:
            status.erro = True
        else:
            status.itens += itens or 0


def marcar_concluido(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.concluido_em = time.time()


def obter(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)
