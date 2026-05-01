# -*- coding: utf-8 -*-
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///qwenpaw-data/rag.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class Source(Base):
    __tablename__ = "rag_sources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    filename = Column(String(1024))
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "rag_chunks"
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("rag_sources.id"))
    text = Column(Text)
    page = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    vector_id = Column(String(255), nullable=True)
    source = relationship("Source", back_populates="chunks")


def init_db():
    Base.metadata.create_all(bind=engine)
