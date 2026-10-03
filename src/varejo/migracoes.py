"""Operações de migração (Alembic) usadas pelos testes e pela carga de dados.

Também serve de linha de comando para atualizar o schema do banco de testes (o
`alembic upgrade head` atua só no banco principal):
    python -m varejo.migracoes teste
"""

from __future__ import annotations

import argparse
import sys

import psycopg
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from varejo.config import RAIZ_PROJETO, ConfigError, carregar_config_banco


def config_alembic(url: URL) -> Config:
    """Config do Alembic apontando para a URL informada (em vez da URL do .env)."""
    config = Config(str(RAIZ_PROJETO / "alembic.ini"))
    config.attributes["url"] = url
    return config


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aplica as migrações pendentes (upgrade head).")
    parser.add_argument("banco", choices=["principal", "teste"])
    args = parser.parse_args(argumentos)
    try:
        config = carregar_config_banco()
        if args.banco == "teste":
            config = config.do_banco_de_teste()
        command.upgrade(config_alembic(config.url()), "head")
    except ConfigError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except (psycopg.OperationalError, sqlalchemy.exc.OperationalError) as erro:
        # O Alembic passa pelo SQLAlchemy, que embrulha o erro do psycopg no dele:
        # sem pegar os dois, o banco fora do ar vira um traceback.
        print(f"Erro: banco inacessível ({erro}).", file=sys.stderr)
        return 1
    print(f"Banco {config.nome!r} no schema mais recente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
