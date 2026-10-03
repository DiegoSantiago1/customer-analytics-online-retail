"""Ambiente do Alembic, adaptado do template oficial (`alembic init`).

Diferenças em relação ao template:
- A URL do banco vem do .env (varejo.config), e não do alembic.ini, que é versionado.
- Sem autogenerate: target_metadata = None. As migrações são SQL escrito à mão
  (op.execute), de propósito.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, create_engine, pool

from varejo.config import carregar_config_banco

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _url() -> URL:
    """URL do banco. Os testes injetam a URL do banco de testes via config.attributes
    (mecanismo do Alembic para passar objetos ao env.py); sem isso, vale o .env."""
    injetada = config.attributes.get("url")
    return injetada if isinstance(injetada, URL) else carregar_config_banco().url()


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade --sql`): só gera o SQL, sem conectar ao banco."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo normal: conecta e aplica as migrações.

    No PostgreSQL o DDL é transacional: se uma migração falhar no meio, nada dela fica
    aplicado.
    """
    # connect_timeout: com o banco fora do ar, falha em 5 s com mensagem clara, em vez de
    # esperar o tempo limite do sistema operacional (mais de 2 minutos no Windows).
    connectable = create_engine(
        _url(), poolclass=pool.NullPool, connect_args={"connect_timeout": 5}
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
