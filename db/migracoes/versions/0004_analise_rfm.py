"""analise: pedidos, métricas por cliente numa data de referência e segmentação RFM

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

Tudo é calculado "numa data de referência": a mesma função responde "como estava a
base em 10/06/2011?" (usada para validar o churn e o CLV) e "como está no fim?"
(10/12/2011, o dia seguinte à última fatura). Assim a validação usa exatamente o
mesmo código da análise final, sem olhar o futuro.

Definições (docs/DECISOES.md):
- compra = fatura de venda com receita de produto > 0 (frete sozinho não é compra);
- receita líquida = receita de produto das compras - valor dos cancelamentos;
- R = dias desde a última compra; F = número de compras; M = receita líquida.

Notas 1 a 5 por percent_rank, e não NTILE(5): 1.618 clientes têm exatamente 1 compra,
e o NTILE espalharia esses empatados em notas diferentes por ordem arbitrária. Com
percent_rank, valores iguais recebem sempre a mesma nota.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- Datas e limites usados em todo o schema, num lugar só (e visíveis no BI).
        CREATE TABLE analise.parametro (
            nome      text PRIMARY KEY,
            valor     text NOT NULL,
            descricao text NOT NULL
        );
        INSERT INTO analise.parametro (nome, valor, descricao) VALUES
            ('data_fim',   '2011-12-10',
             'Data de referência final: dia seguinte à última fatura (09/12/2011).'),
            ('data_corte', '2011-06-10',
             'Data de corte para validar churn e CLV: dados até 09/06/2011.'),
            ('atacado_unidades_por_pedido', '400',
             'Média de unidades por compra a partir da qual o cliente é marcado como '
             'atacado (≈ p90 dos clientes, medido em 03/10/2026).');

        CREATE FUNCTION analise.data_param(p_nome text) RETURNS timestamptz
        LANGUAGE sql STABLE AS $$
            -- Meia-noite de Londres do dia guardado no parâmetro.
            SELECT (valor::date)::timestamp AT TIME ZONE 'Europe/London'
            FROM analise.parametro WHERE nome = p_nome
        $$;

        CREATE TABLE analise.pedido (
            fatura          text          PRIMARY KEY,
            cliente_id      integer,
            tipo            text          NOT NULL CHECK (tipo IN ('venda', 'cancelamento')),
            data            timestamptz   NOT NULL,
            mes             date          NOT NULL CHECK (extract(day FROM mes) = 1),
            receita_produto numeric(14, 3) NOT NULL,
            receita_outros  numeric(14, 3) NOT NULL,
            unidades        integer       NOT NULL,
            linhas          integer       NOT NULL CHECK (linhas > 0),
            eh_compra       boolean       GENERATED ALWAYS AS
                                (tipo = 'venda' AND receita_produto > 0) STORED,
            -- Linha de venda tem quantidade e preço > 0; de cancelamento, quantidade < 0.
            CHECK (tipo <> 'venda' OR (receita_produto >= 0 AND receita_outros >= 0)),
            CHECK (tipo <> 'cancelamento' OR (receita_produto <= 0 AND receita_outros <= 0))
        );
        COMMENT ON TABLE analise.pedido IS
            'Uma linha por fatura de venda ou cancelamento. receita_produto exclui frete, '
            'taxas e descontos (limpo.codigo_nao_produto). data = primeiro horário da fatura.';
        CREATE INDEX ON analise.pedido (cliente_id, data) WHERE cliente_id IS NOT NULL;
        CREATE INDEX ON analise.pedido (mes);

        -- Mapa R x F -> segmento (25 combinações, todas preenchidas).
        CREATE TABLE analise.segmento_rfm (
            r        smallint NOT NULL CHECK (r BETWEEN 1 AND 5),
            f        smallint NOT NULL CHECK (f BETWEEN 1 AND 5),
            segmento text     NOT NULL,
            PRIMARY KEY (r, f)
        );
        INSERT INTO analise.segmento_rfm (r, f, segmento)
        SELECT r, f, (ARRAY[
            -- f:  1                      2                      3                 4                 5
            ARRAY['Perdidos',            'Perdidos',            'Em risco',       'Em risco',       'Não pode perder'],  -- r=1
            ARRAY['Hibernando',          'Hibernando',          'Em risco',       'Em risco',       'Não pode perder'],  -- r=2
            ARRAY['Precisam de atenção', 'Precisam de atenção', 'Leais',          'Leais',          'Leais'],            -- r=3
            ARRAY['Promissores',         'Potenciais leais',    'Leais',          'Campeões',       'Campeões'],         -- r=4
            ARRAY['Novos',               'Potenciais leais',    'Potenciais leais','Campeões',      'Campeões']          -- r=5
        ])[r][f]
        FROM generate_series(1, 5) r, generate_series(1, 5) f;

        -- Ordem de exibição e a ação sugerida para o CRM.
        CREATE TABLE analise.segmento (
            segmento text     PRIMARY KEY,
            ordem    smallint NOT NULL UNIQUE,
            acao     text     NOT NULL
        );
        INSERT INTO analise.segmento (segmento, ordem, acao) VALUES
            ('Campeões',            1,  'Recompensar; pedir indicação; lançamentos em primeira mão.'),
            ('Leais',               2,  'Programa de fidelidade; oferecer itens de maior valor.'),
            ('Potenciais leais',    3,  'Incentivar a próxima compra; sugerir categorias novas.'),
            ('Novos',               4,  'Boas-vindas e segunda compra rápida.'),
            ('Promissores',         5,  'Lembrar da loja; oferta leve.'),
            ('Precisam de atenção', 6,  'Oferta por tempo limitado; reativar antes de esfriar.'),
            ('Não pode perder',     7,  'Contato pessoal: bons clientes parados há muito tempo.'),
            ('Em risco',            8,  'Campanha de reativação personalizada.'),
            ('Hibernando',          9,  'Campanha barata de reativação.'),
            ('Perdidos',            10, 'Não investir; só comunicação de massa.');
        ALTER TABLE analise.segmento_rfm
            ADD FOREIGN KEY (segmento) REFERENCES analise.segmento (segmento);

        -- Métricas de cada cliente com compra antes de p_data_ref (sem olhar o futuro).
        CREATE FUNCTION analise.metricas_cliente(p_data_ref timestamptz)
        RETURNS TABLE (
            cliente_id         integer,
            primeira_compra    timestamptz,
            ultima_compra      timestamptz,
            recencia_dias      integer,
            frequencia         integer,
            receita_bruta      numeric,
            valor_cancelado    numeric,
            receita_liquida    numeric,
            ticket_medio       numeric,
            taxa_cancelamento  numeric,
            unidades_por_pedido numeric,
            meses_de_vida      numeric
        )
        LANGUAGE sql STABLE AS $$
            WITH antes AS (
                SELECT * FROM analise.pedido
                WHERE cliente_id IS NOT NULL AND data < p_data_ref
            ),
            compras AS (
                SELECT cliente_id,
                       min(data) AS primeira, max(data) AS ultima, count(*) AS n,
                       sum(receita_produto) AS bruta, sum(unidades) AS unidades
                FROM antes WHERE eh_compra GROUP BY cliente_id
            ),
            cancelamentos AS (
                SELECT cliente_id, -sum(receita_produto) AS cancelado
                FROM antes WHERE tipo = 'cancelamento' GROUP BY cliente_id
            )
            SELECT c.cliente_id, c.primeira, c.ultima,
                   ((p_data_ref AT TIME ZONE 'Europe/London')::date
                    - (c.ultima AT TIME ZONE 'Europe/London')::date),
                   c.n::integer,
                   c.bruta,
                   coalesce(x.cancelado, 0),
                   c.bruta - coalesce(x.cancelado, 0),
                   round((c.bruta - coalesce(x.cancelado, 0)) / c.n, 2),
                   round(coalesce(x.cancelado, 0) / c.bruta, 4),
                   round(c.unidades::numeric / c.n, 1),
                   -- Meses desde a primeira compra (mínimo 1, para não dividir por ~0).
                   greatest(1, round(extract(epoch FROM p_data_ref - c.primeira)
                                     / (86400 * 30.4375), 2))
            FROM compras c LEFT JOIN cancelamentos x USING (cliente_id)
        $$;

        -- RFM numa data de referência: notas 1-5, segmento e flags.
        CREATE FUNCTION analise.rfm(p_data_ref timestamptz)
        RETURNS TABLE (
            cliente_id           integer,
            recencia_dias        integer,
            frequencia           integer,
            receita_liquida      numeric,
            r                    smallint,
            f                    smallint,
            m                    smallint,
            segmento             text,
            eh_atacado           boolean,
            liquido_nao_positivo boolean
        )
        LANGUAGE sql STABLE AS $$
            WITH base AS (SELECT * FROM analise.metricas_cliente(p_data_ref)),
            notas AS (
                SELECT b.*,
                       -- percent_rank vai de 0 a 1 e dá o mesmo valor a empates.
                       -- Nota = 1 + floor(5 * pr), limitada a 5 (pr = 1 daria 6).
                       least(5, 1 + floor(5 * percent_rank() OVER (ORDER BY b.recencia_dias DESC)))::smallint AS r,
                       least(5, 1 + floor(5 * percent_rank() OVER (ORDER BY b.frequencia)))::smallint AS f,
                       least(5, 1 + floor(5 * percent_rank() OVER (ORDER BY b.receita_liquida)))::smallint AS m
                FROM base b
            )
            SELECT n.cliente_id, n.recencia_dias, n.frequencia, n.receita_liquida,
                   n.r, n.f,
                   -- Quem cancelou tudo (líquido <= 0) fica com a nota mínima de valor.
                   CASE WHEN n.receita_liquida <= 0 THEN 1::smallint ELSE n.m END,
                   s.segmento,
                   n.unidades_por_pedido >= (
                       SELECT valor::numeric FROM analise.parametro
                       WHERE nome = 'atacado_unidades_por_pedido'
                   ),
                   n.receita_liquida <= 0
            FROM notas n JOIN analise.segmento_rfm s USING (r, f)
        $$;

        -- Foto no fim da base, materializada para o Power BI e para as outras análises.
        CREATE TABLE analise.cliente (
            cliente_id           integer PRIMARY KEY,
            pais                 text    NOT NULL,
            primeira_compra      timestamptz NOT NULL,
            ultima_compra        timestamptz NOT NULL,
            recencia_dias        integer NOT NULL CHECK (recencia_dias >= 0),
            frequencia           integer NOT NULL CHECK (frequencia >= 1),
            receita_bruta        numeric(14, 3) NOT NULL CHECK (receita_bruta > 0),
            valor_cancelado      numeric(14, 3) NOT NULL CHECK (valor_cancelado >= 0),
            receita_liquida      numeric(14, 3) NOT NULL,
            ticket_medio         numeric(14, 2) NOT NULL,
            taxa_cancelamento    numeric(8, 4)  NOT NULL CHECK (taxa_cancelamento >= 0),
            unidades_por_pedido  numeric(10, 1) NOT NULL,
            r                    smallint NOT NULL CHECK (r BETWEEN 1 AND 5),
            f                    smallint NOT NULL CHECK (f BETWEEN 1 AND 5),
            m                    smallint NOT NULL CHECK (m BETWEEN 1 AND 5),
            segmento             text NOT NULL REFERENCES analise.segmento (segmento),
            eh_atacado           boolean NOT NULL,
            liquido_nao_positivo boolean NOT NULL,
            CHECK (receita_liquida = receita_bruta - valor_cancelado),
            CHECK (ultima_compra >= primeira_compra)
        );
        COMMENT ON TABLE analise.cliente IS
            'Um cliente por linha, no fim da base (parâmetro data_fim): métricas, RFM, '
            'segmento e flags. Reconstruída por analise.recarregar().';

        CREATE FUNCTION analise.recarregar() RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            v_fim timestamptz := analise.data_param('data_fim');
        BEGIN
            TRUNCATE analise.pedido, analise.cliente;

            INSERT INTO analise.pedido (
                fatura, cliente_id, tipo, data, mes, receita_produto, receita_outros,
                unidades, linhas
            )
            SELECT fatura, min(cliente_id), min(tipo), min(data_fatura),
                   date_trunc('month', min(data_fatura) AT TIME ZONE 'Europe/London')::date,
                   coalesce(sum(valor) FILTER (WHERE eh_produto), 0),
                   coalesce(sum(valor) FILTER (WHERE NOT eh_produto), 0),
                   coalesce(sum(quantidade) FILTER (WHERE eh_produto), 0),
                   count(*)
            FROM limpo.fatura_linha
            WHERE tipo IN ('venda', 'cancelamento')
            GROUP BY fatura;
            ANALYZE analise.pedido;

            INSERT INTO analise.cliente
            SELECT m.cliente_id, c.pais, m.primeira_compra, m.ultima_compra,
                   m.recencia_dias, m.frequencia, m.receita_bruta, m.valor_cancelado,
                   m.receita_liquida, m.ticket_medio, m.taxa_cancelamento,
                   m.unidades_por_pedido, r.r, r.f, r.m, r.segmento, r.eh_atacado,
                   r.liquido_nao_positivo
            FROM analise.metricas_cliente(v_fim) m
            JOIN analise.rfm(v_fim) r USING (cliente_id)
            JOIN limpo.cliente c USING (cliente_id);
            ANALYZE analise.cliente;
        END
        $$;
        COMMENT ON FUNCTION analise.recarregar() IS
            'Reconstrói pedidos e a foto de clientes a partir do limpo (idempotente).';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION analise.recarregar();
        DROP TABLE analise.cliente;
        DROP FUNCTION analise.rfm(timestamptz);
        DROP FUNCTION analise.metricas_cliente(timestamptz);
        DROP TABLE analise.segmento_rfm;
        DROP TABLE analise.segmento;
        DROP TABLE analise.pedido;
        DROP FUNCTION analise.data_param(text);
        DROP TABLE analise.parametro;
        """
    )
