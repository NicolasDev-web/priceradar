from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models_db import EmpreendimentoDB, ReferencialMRV


async def listar_por_cidade(db: AsyncSession, cidade: str, limit: int = 100) -> list[EmpreendimentoDB]:
    q = (
        select(EmpreendimentoDB)
        .where(EmpreendimentoDB.cidade.ilike(f"%{cidade.lower()}%"))
        .order_by(EmpreendimentoDB.data_coleta.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def preco_m2_historico(db: AsyncSession, cidade: str, quartos: int | None) -> list[dict]:
    q = (
        select(
            func.strftime('%Y-W%W', EmpreendimentoDB.data_coleta).label('semana'),
            func.avg(EmpreendimentoDB.preco_m2).label('preco_m2_medio'),
            func.count(EmpreendimentoDB.id).label('total'),
        )
        .where(EmpreendimentoDB.cidade.ilike(f"%{cidade.lower()}%"))
        .group_by(text("semana"))
        .order_by(text("semana"))
    )
    if quartos:
        q = q.where(EmpreendimentoDB.quartos == quartos)
    result = await db.execute(q)
    return [
        {"semana": row.semana, "preco_m2_medio": round(row.preco_m2_medio, 2), "total": row.total}
        for row in result.all()
    ]


async def upsert_referencial_mrv(
    db: AsyncSession, cidade: str, produto: str, quartos: int | None, preco_m2: float
) -> None:
    from datetime import datetime
    q = select(ReferencialMRV).where(
        ReferencialMRV.cidade.ilike(f"%{cidade.lower()}%"),
        ReferencialMRV.quartos == quartos,
    )
    result = await db.execute(q)
    existente = result.scalar_one_or_none()

    if existente:
        existente.produto = produto
        existente.preco_m2 = preco_m2
        existente.atualizado_em = datetime.utcnow()
    else:
        db.add(ReferencialMRV(cidade=cidade.lower(), produto=produto, quartos=quartos, preco_m2=preco_m2))

    await db.commit()


async def get_referencial_mrv(db: AsyncSession, cidade: str, quartos: int | None) -> float | None:
    q = (
        select(ReferencialMRV.preco_m2)
        .where(ReferencialMRV.cidade.ilike(f"%{cidade.split(',')[0].strip().lower()}%"))
        .order_by(ReferencialMRV.atualizado_em.desc())
        .limit(1)
    )
    if quartos:
        q = q.where(ReferencialMRV.quartos == quartos)
    result = await db.execute(q)
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None
