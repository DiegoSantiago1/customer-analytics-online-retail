"""limpo: linhas classificadas e tipadas, códigos que não são produto e clientes

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

As regras de limpeza (docs/DECISOES.md) vivem aqui, em SQL versionado:

1. Sobreposição das abas. A aba "Year 2009-2010" vai até 09/12/2010 e a "Year
   2010-2011" começa em 01/12/2010. Medido: as 22.523 linhas desse período são
   idênticas nas duas abas, inclusive na contagem de repetições (EXCEPT ALL vazio
   nos dois sentidos). Fica só a aba mais nova; a da mais antiga sai inteira a partir
   do primeiro dia da mais nova. O dq confere a igualdade a cada carga.
2. Repetições DENTRO de uma aba são mantidas: 86% delas estão em linhas não vizinhas
   da mesma fatura, e o mesmo produto aparece de novo na mesma fatura também com
   quantidades diferentes (5.084 pares fatura+produto na aba 2010-2011). É o jeito de
   o sistema registrar o item adicionado mais de uma vez, não duplicação.
3. Cada linha recebe um tipo, e só 'venda' e 'cancelamento' entram nas análises:
   - venda: fatura numérica, quantidade > 0 e preço > 0;
   - cancelamento: fatura com prefixo C, quantidade < 0 e preço > 0;
   - sem_valor: fatura numérica com preço 0 (ajuste de estoque: "damages", "lost",
     "check"...; e brindes);
   - ajuste_divida: fatura com prefixo A ("Adjust bad debt");
   - anomalia: o que não se encaixa (1 linha medida: C496350, quantidade positiva).
   Os CHECKs da tabela garantem que um tipo nunca contradiz os sinais.
4. Códigos que não são produto (frete, taxas, desconto, manual...) ficam numa tabela
   de referência explícita e recebem eh_produto = false. Saem da receita de produto e
   são reportados à parte.
5. Horário: o texto da planilha é horário local do Reino Unido, convertido com
   AT TIME ZONE 'Europe/London' para timestamptz. Medido: as vendas vão de 06:10 a
   21:52, então nenhuma cai na hora ambígua da troca de horário de verão.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE limpo.codigo_nao_produto (
            codigo text PRIMARY KEY CHECK (codigo = btrim(codigo) AND codigo <> ''),
            tipo   text NOT NULL CHECK (tipo IN (
                'frete', 'taxa', 'desconto', 'manual', 'ajuste', 'amostra',
                'vale_presente', 'teste'
            )),
            motivo text NOT NULL
        );
        COMMENT ON TABLE limpo.codigo_nao_produto IS
            'StockCodes que não são mercadoria. Lista medida em 03/10/2026 (dq.verificar '
            'avisa se aparecer um código novo fora do padrão de produto).';

        INSERT INTO limpo.codigo_nao_produto (codigo, tipo, motivo) VALUES
            ('POST',         'frete',         'POSTAGE: frete cobrado do cliente'),
            ('DOT',          'frete',         'DOTCOM POSTAGE: frete das vendas do site'),
            ('C2',           'frete',         'CARRIAGE: transporte'),
            ('C3',           'frete',         'Sem descrição; só aparece com preço 0 (ajuste)'),
            ('BANK CHARGES', 'taxa',          'Tarifa bancária'),
            ('AMAZONFEE',    'taxa',          'AMAZON FEE: comissão da Amazon'),
            ('CRUK',         'taxa',          'CRUK Commission: comissão para a Cancer Research UK'),
            ('D',            'desconto',      'Discount'),
            ('M',            'manual',        'Manual: lançamento manual de valor, sem produto'),
            ('m',            'manual',        'Manual (minúsculo)'),
            ('ADJUST',       'ajuste',        'Adjustment by <pessoa>: ajuste manual'),
            ('ADJUST2',      'ajuste',        'Adjustment by <pessoa>: ajuste manual'),
            ('B',            'ajuste',        'Adjust bad debt (faturas A)'),
            ('S',            'amostra',       'SAMPLES: amostras'),
            ('GIFT',         'vale_presente', 'Sem descrição; só aparece com preço 0'),
            ('gift_0001_10', 'vale_presente', 'Dotcomgiftshop Gift Voucher £10'),
            ('gift_0001_20', 'vale_presente', 'Dotcomgiftshop Gift Voucher £20'),
            ('gift_0001_30', 'vale_presente', 'Dotcomgiftshop Gift Voucher £30'),
            ('gift_0001_40', 'vale_presente', 'Dotcomgiftshop Gift Voucher £40'),
            ('gift_0001_50', 'vale_presente', 'Dotcomgiftshop Gift Voucher £50'),
            ('gift_0001_60', 'vale_presente', 'Dotcomgiftshop Gift Voucher £60'),
            ('gift_0001_70', 'vale_presente', 'Dotcomgiftshop Gift Voucher £70'),
            ('gift_0001_80', 'vale_presente', 'Dotcomgiftshop Gift Voucher £80'),
            ('gift_0001_90', 'vale_presente', 'Dotcomgiftshop Gift Voucher £90'),
            ('TEST001',      'teste',         'This is a test product.'),
            ('TEST002',      'teste',         'This is a test product.');

        CREATE TABLE limpo.fatura_linha (
            aba            text          NOT NULL,
            linha_origem   integer       NOT NULL,
            fatura         text          NOT NULL CHECK (fatura ~ '^[CA]?[0-9]{6}$'),
            tipo           text          NOT NULL CHECK (tipo IN (
                'venda', 'cancelamento', 'sem_valor', 'ajuste_divida', 'anomalia'
            )),
            codigo_produto text          NOT NULL
                CHECK (codigo_produto = btrim(codigo_produto) AND codigo_produto <> ''),
            descricao      text,
            quantidade     integer       NOT NULL,
            data_fatura    timestamptz   NOT NULL,
            preco_unitario numeric(12, 3) NOT NULL,
            valor          numeric(14, 3) GENERATED ALWAYS AS (quantidade * preco_unitario) STORED,
            cliente_id     integer       CHECK (cliente_id BETWEEN 10000 AND 99999),
            pais           text          NOT NULL,
            eh_produto     boolean       NOT NULL,
            PRIMARY KEY (aba, linha_origem),
            CONSTRAINT venda_coerente CHECK (
                tipo <> 'venda'
                OR (fatura ~ '^[0-9]' AND quantidade > 0 AND preco_unitario > 0)
            ),
            CONSTRAINT cancelamento_coerente CHECK (
                tipo <> 'cancelamento'
                OR (fatura LIKE 'C%' AND quantidade < 0 AND preco_unitario > 0)
            ),
            CONSTRAINT sem_valor_coerente CHECK (
                tipo <> 'sem_valor' OR (fatura ~ '^[0-9]' AND preco_unitario = 0)
            ),
            CONSTRAINT ajuste_divida_coerente CHECK (
                tipo <> 'ajuste_divida' OR fatura LIKE 'A%'
            )
        );
        COMMENT ON TABLE limpo.fatura_linha IS
            'Linhas da planilha sem a sobreposição das abas, tipadas e classificadas. '
            'Reconstruída por limpo.recarregar().';
        CREATE INDEX ON limpo.fatura_linha (cliente_id, data_fatura)
            WHERE tipo IN ('venda', 'cancelamento');
        CREATE INDEX ON limpo.fatura_linha (data_fatura);

        CREATE TABLE limpo.cliente (
            cliente_id integer PRIMARY KEY CHECK (cliente_id BETWEEN 10000 AND 99999),
            pais       text    NOT NULL,
            n_paises   integer NOT NULL CHECK (n_paises >= 1)
        );
        COMMENT ON TABLE limpo.cliente IS
            'Um registro por cliente identificado. pais = o país mais frequente nas linhas '
            'dele (13 clientes aparecem em mais de um país).';

        CREATE FUNCTION limpo.recarregar() RETURNS void
        LANGUAGE sql AS $$
            TRUNCATE limpo.fatura_linha, limpo.cliente;

            INSERT INTO limpo.fatura_linha (
                aba, linha_origem, fatura, tipo, codigo_produto, descricao, quantidade,
                data_fatura, preco_unitario, cliente_id, pais, eh_produto
            )
            WITH tipada AS (
                SELECT b.aba, b.linha_origem, b.fatura,
                       btrim(b.codigo_produto) AS codigo_produto, b.descricao,
                       b.quantidade::integer AS quantidade,
                       b.data_fatura::timestamp AS data_local,
                       b.preco_unitario::numeric AS preco_unitario,
                       b.cliente_id::integer AS cliente_id, b.pais
                FROM bruto.fatura_linha b
            ),
            -- Primeiro dia da aba mais nova: daí em diante a aba antiga é cópia.
            -- Sem a aba nova, o corte seria NULL e o filtro abaixo descartaria a aba
            -- antiga inteira (NOT (x >= NULL) é NULL); 'infinity' mantém tudo.
            corte AS (
                SELECT coalesce(date_trunc('day', min(data_local)), 'infinity')
                           AS inicio_aba_nova
                FROM tipada WHERE aba = 'Year 2010-2011'
            )
            SELECT t.aba, t.linha_origem, t.fatura,
                   CASE
                       WHEN t.fatura LIKE 'A%' THEN 'ajuste_divida'
                       WHEN t.fatura LIKE 'C%' AND t.quantidade < 0 AND t.preco_unitario > 0
                           THEN 'cancelamento'
                       WHEN t.fatura ~ '^[0-9]' AND t.preco_unitario = 0 THEN 'sem_valor'
                       WHEN t.fatura ~ '^[0-9]' AND t.quantidade > 0 AND t.preco_unitario > 0
                           THEN 'venda'
                       ELSE 'anomalia'
                   END,
                   t.codigo_produto, t.descricao, t.quantidade,
                   t.data_local AT TIME ZONE 'Europe/London',
                   t.preco_unitario, t.cliente_id, t.pais,
                   NOT EXISTS (
                       SELECT 1 FROM limpo.codigo_nao_produto n
                       WHERE n.codigo = t.codigo_produto
                   )
            FROM tipada t CROSS JOIN corte c
            WHERE NOT (t.aba = 'Year 2009-2010' AND t.data_local >= c.inicio_aba_nova);

            INSERT INTO limpo.cliente (cliente_id, pais, n_paises)
            SELECT cliente_id,
                   mode() WITHIN GROUP (ORDER BY pais),
                   count(DISTINCT pais)
            FROM limpo.fatura_linha
            WHERE cliente_id IS NOT NULL
            GROUP BY cliente_id;

            ANALYZE limpo.fatura_linha;
            ANALYZE limpo.cliente;
        $$;
        COMMENT ON FUNCTION limpo.recarregar() IS
            'Reconstrói o schema limpo a partir do bruto (idempotente).';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION limpo.recarregar();
        DROP TABLE limpo.cliente;
        DROP TABLE limpo.fatura_linha;
        DROP TABLE limpo.codigo_nao_produto;
        """
    )
