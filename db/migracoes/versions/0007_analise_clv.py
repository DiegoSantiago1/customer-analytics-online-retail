"""analise: CLV histórico e preditivo simples, com validação contra o real

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03

CLV histórico = receita líquida acumulada (já em analise.cliente).

CLV previsto para os próximos H meses, numa data de referência T:
    clv = p_ativo(segmento) x ticket médio líquido x compras por mês x H
- ticket médio vem do histórico do cliente antes de T;
- compras por mês = (compras + b x taxa da base) / (meses de vida + b): a média de
  uma Gamma-Poisson. Sem a suavização, um cliente com 1 compra há 10 dias teria
  "1 compra por mês" e o CLV dos Novos saía 2,8x o real na validação. Com b = 3
  meses, quem tem pouca história fica perto da taxa média da base e quem tem muita
  fica com a própria taxa;
- p_ativo é a fração dos clientes do mesmo segmento RFM que compraram de novo numa
  janela de H meses, medida na MESMA ÉPOCA DO ANO ANTERIOR (de T - 12 meses a
  T - 12 meses + H). A sazonalidade é forte (D18): calibrar numa janela de outra época
  distorceria a previsão.

Validação: a previsão feita no corte (10/06/2011, H = 6) é comparada à receita real
de 10/06 a 10/12/2011 e a um modelo ingênuo: "os próximos 6 meses repetem os 6
anteriores". Se o modelo não ganhar do ingênuo, isso é reportado.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO analise.parametro (nome, valor, descricao) VALUES
            ('clv_horizonte_meses', '6',
             'Horizonte do CLV previsto no fim da base: o mesmo horizonte validado no '
             'corte (12 meses não teriam como ser validados com 2 anos de dados).'),
            ('clv_validacao_meses', '6',
             'Horizonte da validação do CLV a partir da data de corte.'),
            ('clv_prior_meses', '3',
             'Meses de "história média" somados a cada cliente ao estimar compras por mês '
             '(suavização Gamma-Poisson). Sensibilidade em docs/DECISOES.md.');

        -- Fração dos clientes de cada segmento (no início da janela) que compraram
        -- de novo dentro da janela.
        CREATE FUNCTION analise.retencao_segmento(p_inicio timestamptz, p_meses integer)
        RETURNS TABLE (segmento text, clientes integer, voltaram integer, p_ativo numeric)
        LANGUAGE sql STABLE AS $$
            SELECT r.segmento, count(*)::integer,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM analise.pedido p
                       WHERE p.cliente_id = r.cliente_id AND p.eh_compra
                         AND p.data >= p_inicio
                         AND p.data < p_inicio + make_interval(months => p_meses)
                   ))::integer,
                   round(count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM analise.pedido p
                       WHERE p.cliente_id = r.cliente_id AND p.eh_compra
                         AND p.data >= p_inicio
                         AND p.data < p_inicio + make_interval(months => p_meses)
                   ))::numeric / count(*), 4)
            FROM analise.rfm(p_inicio) r
            GROUP BY r.segmento
        $$;

        -- CLV previsto por cliente para os H meses seguintes a p_data_ref.
        CREATE FUNCTION analise.clv_previsto(p_data_ref timestamptz, p_meses integer)
        RETURNS TABLE (
            cliente_id      integer,
            segmento        text,
            p_ativo         numeric,
            ticket_medio    numeric,
            compras_por_mes numeric,
            clv_previsto    numeric
        )
        LANGUAGE sql STABLE AS $$
            WITH metricas AS (SELECT * FROM analise.metricas_cliente(p_data_ref)),
            calibracao AS (
                SELECT * FROM analise.retencao_segmento(
                    p_data_ref - interval '12 months', p_meses
                )
            ),
            geral AS (
                SELECT
                    -- Taxa média de compras por mês da base, na própria data de referência.
                    (SELECT sum(frequencia)::numeric / sum(meses_de_vida) FROM metricas) AS taxa,
                    -- Segmento sem ninguém na calibração (raro): usa a retenção geral.
                    (SELECT sum(voltaram)::numeric / nullif(sum(clientes), 0) FROM calibracao)
                        AS p_geral,
                    (SELECT valor::numeric FROM analise.parametro WHERE nome = 'clv_prior_meses')
                        AS b
            ),
            estimativa AS (
                SELECT m.cliente_id, r.segmento,
                       coalesce(c.p_ativo, g.p_geral, 0) AS p_ativo,
                       m.ticket_medio,
                       (m.frequencia + g.b * g.taxa) / (m.meses_de_vida + g.b) AS compras_por_mes
                FROM metricas m
                JOIN analise.rfm(p_data_ref) r USING (cliente_id)
                LEFT JOIN calibracao c ON c.segmento = r.segmento
                CROSS JOIN geral g
            )
            SELECT cliente_id, segmento, p_ativo, ticket_medio, round(compras_por_mes, 4),
                   round(greatest(0, p_ativo * ticket_medio * compras_por_mes * p_meses), 2)
            FROM estimativa
        $$;

        -- Por cliente, no corte: previsto, ingênuo e real (para o gráfico previsto x real).
        CREATE TABLE analise.clv_validacao_cliente (
            cliente_id    integer PRIMARY KEY,
            segmento      text    NOT NULL REFERENCES analise.segmento (segmento),
            previsto      numeric(14, 2) NOT NULL CHECK (previsto >= 0),
            ingenuo       numeric(14, 2) NOT NULL,
            real          numeric(14, 2) NOT NULL
        );
        COMMENT ON TABLE analise.clv_validacao_cliente IS
            'Validação do CLV: previsão feita no corte para os 6 meses seguintes, o modelo '
            'ingênuo (repete os 6 meses anteriores) e a receita líquida real.';

        CREATE TABLE analise.clv_validacao (
            modelo           text PRIMARY KEY CHECK (modelo IN ('previsto', 'ingenuo')),
            clientes         integer NOT NULL,
            total_previsto   numeric(14, 2) NOT NULL,
            total_real       numeric(14, 2) NOT NULL,
            -- NULL quando a receita real é zero: o erro percentual não existe.
            erro_total_pct   numeric(8, 2),
            erro_medio_abs   numeric(14, 2) NOT NULL,
            -- Fração da receita real que está nos 20% de clientes com maior previsão,
            -- dividida pela fração que estaria num top 20% perfeito.
            captura_top20    numeric(6, 4)
        );
        COMMENT ON TABLE analise.clv_validacao IS
            'Resumo da validação do CLV: erro no total, erro médio por cliente e quanto '
            'da receita real os 20% maiores previstos capturam (1 = perfeito).';

        ALTER TABLE analise.cliente
            ADD COLUMN clv_previsto_6m numeric(14, 2),
            ADD COLUMN p_ativo_6m numeric(6, 4);
        COMMENT ON COLUMN analise.cliente.clv_previsto_6m IS
            'Receita líquida esperada nos 6 meses seguintes ao fim da base.';

        CREATE FUNCTION analise.recarregar_clv() RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            v_corte timestamptz := analise.data_param('data_corte');
            v_fim   timestamptz := analise.data_param('data_fim');
            v_h_val integer := (SELECT valor::integer FROM analise.parametro
                                WHERE nome = 'clv_validacao_meses');
            v_h     integer := (SELECT valor::integer FROM analise.parametro
                                WHERE nome = 'clv_horizonte_meses');
        BEGIN
            TRUNCATE analise.clv_validacao_cliente, analise.clv_validacao;

            INSERT INTO analise.clv_validacao_cliente
            SELECT c.cliente_id, c.segmento, c.clv_previsto,
                   coalesce((SELECT sum(p.receita_produto) FROM analise.pedido p
                             WHERE p.cliente_id = c.cliente_id
                               AND (p.eh_compra OR p.tipo = 'cancelamento')
                               AND p.data >= v_corte - make_interval(months => v_h_val)
                               AND p.data < v_corte), 0),
                   coalesce((SELECT sum(p.receita_produto) FROM analise.pedido p
                             WHERE p.cliente_id = c.cliente_id
                               AND (p.eh_compra OR p.tipo = 'cancelamento')
                               AND p.data >= v_corte
                               AND p.data < v_corte + make_interval(months => v_h_val)), 0)
            FROM analise.clv_previsto(v_corte, v_h_val) c;

            INSERT INTO analise.clv_validacao
            WITH longo AS (
                SELECT 'previsto' AS modelo, cliente_id, previsto AS estimativa, real
                FROM analise.clv_validacao_cliente
                UNION ALL
                SELECT 'ingenuo', cliente_id, ingenuo, real FROM analise.clv_validacao_cliente
            ),
            ordenado AS (
                SELECT l.*,
                       row_number() OVER (PARTITION BY modelo ORDER BY estimativa DESC, cliente_id)
                           AS pos_estimado,
                       row_number() OVER (PARTITION BY modelo ORDER BY real DESC, cliente_id)
                           AS pos_real,
                       count(*) OVER (PARTITION BY modelo) AS n
                FROM longo l
            )
            SELECT modelo, max(n),
                   sum(estimativa), sum(real),
                   round(100 * (sum(estimativa) - sum(real)) / nullif(sum(real), 0), 2),
                   round(avg(abs(estimativa - real)), 2),
                   round(sum(real) FILTER (WHERE pos_estimado <= ceil(0.2 * n))
                         / nullif(sum(real) FILTER (WHERE pos_real <= ceil(0.2 * n)), 0), 4)
            FROM ordenado
            GROUP BY modelo;

            UPDATE analise.cliente c
            SET clv_previsto_6m = coalesce(p.clv_previsto, 0),
                p_ativo_6m = p.p_ativo
            FROM analise.clv_previsto(v_fim, v_h) p
            WHERE p.cliente_id = c.cliente_id;
        END
        $$;
        COMMENT ON FUNCTION analise.recarregar_clv() IS
            'Valida o CLV no corte e calcula o CLV previsto de 6 meses no fim da base.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION analise.recarregar_clv();
        ALTER TABLE analise.cliente DROP COLUMN p_ativo_6m, DROP COLUMN clv_previsto_6m;
        DROP TABLE analise.clv_validacao;
        DROP TABLE analise.clv_validacao_cliente;
        DROP FUNCTION analise.clv_previsto(timestamptz, integer);
        DROP FUNCTION analise.retencao_segmento(timestamptz, integer);
        DELETE FROM analise.parametro
        WHERE nome IN ('clv_horizonte_meses', 'clv_validacao_meses', 'clv_prior_meses');
        """
    )
