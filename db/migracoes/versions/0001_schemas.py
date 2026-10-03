"""schemas bruto, limpo, analise e dq, com a leitura do Power BI

Revision ID: 0001
Revises:
Create Date: 2026-10-03

Quatro camadas, uma por schema:
- bruto: a planilha exatamente como veio (texto, sem restrições);
- limpo: depois das regras de limpeza, com tipos e restrições no banco;
- analise: RFM, churn, coortes, CLV e as views lidas pelo Power BI;
- dq: checagens de qualidade de dados.

O grupo varejo_leitura (criado pelo bootstrap) lê só analise e dq: o Power BI não
enxerga as linhas brutas nem as limpas, só o que foi preparado para ele.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA bruto;
        COMMENT ON SCHEMA bruto IS
            'Planilha Online Retail II como veio (texto, sem restrições), antes da limpeza.';
        CREATE SCHEMA limpo;
        COMMENT ON SCHEMA limpo IS
            'Linhas deduplicadas e tipadas, com as regras de limpeza garantidas pelo banco.';
        CREATE SCHEMA analise;
        COMMENT ON SCHEMA analise IS
            'RFM, churn, coortes, CLV e as views lidas pelo Power BI.';
        CREATE SCHEMA dq;
        COMMENT ON SCHEMA dq IS 'Checagens de qualidade de dados.';

        -- Leitura do Power BI: USAGE nos schemas e SELECT em tudo que o dono criar
        -- neles daqui para frente (default privileges), sem GRANT tabela a tabela.
        GRANT USAGE ON SCHEMA analise, dq TO varejo_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA analise GRANT SELECT ON TABLES TO varejo_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA dq GRANT SELECT ON TABLES TO varejo_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA analise
            GRANT EXECUTE ON FUNCTIONS TO varejo_leitura;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA analise
            REVOKE EXECUTE ON FUNCTIONS FROM varejo_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA dq REVOKE SELECT ON TABLES FROM varejo_leitura;
        ALTER DEFAULT PRIVILEGES IN SCHEMA analise REVOKE SELECT ON TABLES FROM varejo_leitura;
        DROP SCHEMA dq CASCADE;
        DROP SCHEMA analise CASCADE;
        DROP SCHEMA limpo CASCADE;
        DROP SCHEMA bruto CASCADE;
        """
    )
