"""Acesso ao banco: conexão do psycopg e engine do SQLAlchemy."""

from __future__ import annotations

import psycopg
from psycopg.rows import TupleRow
from sqlalchemy import Engine, create_engine

from varejo.config import ConfigBanco

type Conexao = psycopg.Connection[TupleRow]


def conectar(config: ConfigBanco) -> Conexao:
    """Conecta com o usuário e o banco da config."""
    return psycopg.connect(
        host=config.host,
        port=config.porta,
        dbname=config.nome,
        user=config.usuario,
        password=config.senha,
        connect_timeout=5,
    )


def engine(config: ConfigBanco) -> Engine:
    """Engine do SQLAlchemy (usada pelo Pandas para ler consultas em DataFrames)."""
    return create_engine(config.url(), pool_pre_ping=True)
