"""bruto: linhas da planilha como vieram, e o registro de cada carga

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03

As 8 colunas entram como TEXTO, sem nenhuma restrição: a planilha tem descrições
numéricas, clientes vazios, quantidades negativas e linhas duplicadas, e tudo isso
precisa conseguir entrar para ser medido e tratado na limpeza. Os nomes já estão em
português (o dicionário com os nomes originais está no README).

A chave é (aba, linha_origem): a linha da planilha de onde o registro veio. Com ela,
qualquer número da limpeza pode ser rastreado até a célula original.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bruto.carga (
            id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            arquivo       text        NOT NULL,
            sha256        text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            linhas        integer     NOT NULL CHECK (linhas >= 0),
            carregada_em  timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE bruto.carga IS
            'Uma linha por carga da planilha: qual arquivo (hash) gerou os dados atuais.';

        CREATE TABLE bruto.fatura_linha (
            aba            text    NOT NULL,
            linha_origem   integer NOT NULL,
            fatura         text,   -- Invoice
            codigo_produto text,   -- StockCode
            descricao      text,   -- Description
            quantidade     text,   -- Quantity
            data_fatura    text,   -- InvoiceDate (horário local do Reino Unido, sem fuso)
            preco_unitario text,   -- Price (libras)
            cliente_id     text,   -- Customer ID
            pais           text,   -- Country
            PRIMARY KEY (aba, linha_origem)
        );
        COMMENT ON TABLE bruto.fatura_linha IS
            'Online Retail II (UCI 502) célula a célula, como texto. Chave = aba + linha '
            'da planilha (a linha 1 é o cabeçalho, então os dados começam na 2).';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE bruto.fatura_linha;
        DROP TABLE bruto.carga;
        """
    )
