import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.connection import Base


class BuscaSalva(Base):
    __tablename__ = "buscas"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    cidade           = Column(String, nullable=False, index=True)
    preco_min        = Column(Float, nullable=False)
    preco_max        = Column(Float, nullable=False)
    quartos          = Column(Integer, nullable=True)
    bairro           = Column(String, nullable=True)
    total_encontrado = Column(Integer, default=0)
    preco_m2_medio   = Column(Float, nullable=True)
    preco_m2_mediana = Column(Float, nullable=True)
    criado_em        = Column(DateTime, default=datetime.utcnow)
    usuario          = Column(String, nullable=True)

    empreendimentos = relationship("EmpreendimentoDB", back_populates="busca", cascade="all, delete-orphan")


class EmpreendimentoDB(Base):
    __tablename__ = "empreendimentos"

    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    busca_id            = Column(String, ForeignKey("buscas.id"), nullable=False, index=True)
    nome_anuncio        = Column(String, nullable=False)
    nome_empreendimento = Column(String, nullable=True)
    construtora         = Column(String, nullable=True, index=True)
    cidade              = Column(String, nullable=False, index=True)
    bairro              = Column(String, nullable=True)
    endereco            = Column(String, nullable=True)
    portal              = Column(String, nullable=False)
    preco               = Column(Float, nullable=False)
    area_m2             = Column(Float, nullable=False)
    preco_m2            = Column(Float, nullable=False, index=True)
    variacao_mrv_pct    = Column(Float, nullable=True)
    quartos             = Column(Integer, nullable=True)
    banheiros           = Column(Integer, nullable=True)
    vagas               = Column(Integer, nullable=True)
    descricao           = Column(Text, nullable=True)
    url_anuncio         = Column(String, nullable=False)
    data_coleta         = Column(DateTime, default=datetime.utcnow)
    rf_score            = Column(Float, nullable=True)

    busca = relationship("BuscaSalva", back_populates="empreendimentos")


class ReferencialMRV(Base):
    __tablename__ = "referencial_mrv"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    cidade        = Column(String, nullable=False, index=True)
    produto       = Column(String, nullable=False)
    quartos       = Column(Integer, nullable=True)
    preco_m2      = Column(Float, nullable=False)
    atualizado_em = Column(DateTime, default=datetime.utcnow)
