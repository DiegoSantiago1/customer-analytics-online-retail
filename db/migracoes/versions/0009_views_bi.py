"""analise: views lidas pelo Power BI, pelos notebooks e pelo site

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03

As views só juntam e renomeiam o que já foi calculado; nenhuma regra nova nasce
aqui. Assim o Power BI, os notebooks e o site mostram exatamente os mesmos números.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- Uma linha por mês: receita por origem, pedidos, clientes ativos e novos.
        CREATE VIEW analise.vw_receita_mes AS
        WITH limites AS (SELECT max(mes) AS ultimo FROM analise.pedido),
        novos AS (
            SELECT date_trunc('month', primeira_compra AT TIME ZONE 'Europe/London')::date AS mes,
                   count(*) AS novos
            FROM analise.cliente GROUP BY 1
        )
        SELECT p.mes,
               p.mes = l.ultimo AS mes_parcial,
               sum(p.receita_produto) FILTER (WHERE p.tipo = 'venda' AND p.cliente_id IS NOT NULL)
                   AS venda_produto_com_cliente,
               sum(p.receita_produto) FILTER (WHERE p.tipo = 'venda' AND p.cliente_id IS NULL)
                   AS venda_produto_sem_cliente,
               sum(p.receita_produto) FILTER (WHERE p.tipo = 'cancelamento')
                   AS cancelamento_produto,
               sum(p.receita_produto) AS receita_produto_liquida,
               sum(p.receita_outros) AS frete_taxas_e_ajustes,
               count(*) FILTER (WHERE p.eh_compra) AS pedidos,
               count(*) FILTER (WHERE p.eh_compra AND p.cliente_id IS NOT NULL)
                   AS pedidos_com_cliente,
               count(DISTINCT p.cliente_id) FILTER (WHERE p.eh_compra) AS clientes_ativos,
               coalesce(max(n.novos), 0) AS clientes_novos
        FROM analise.pedido p
        CROSS JOIN limites l
        LEFT JOIN novos n ON n.mes = p.mes
        GROUP BY p.mes, l.ultimo;
        COMMENT ON VIEW analise.vw_receita_mes IS
            'Receita mensal por origem (com/sem cliente, cancelamentos, frete e taxas), '
            'pedidos, clientes ativos e novos. mes_parcial marca dez/2011 (até o dia 9).';

        -- Cliente com o segmento ordenado e a ação sugerida, e faixas para gráficos.
        CREATE VIEW analise.vw_cliente AS
        SELECT c.*,
               s.ordem AS segmento_ordem,
               s.acao AS segmento_acao,
               CASE WHEN c.eh_atacado THEN 'Atacado' ELSE 'Varejo' END AS perfil,
               CASE
                   WHEN c.recencia_dias <= 30 THEN '0-30 dias'
                   WHEN c.recencia_dias <= 90 THEN '31-90 dias'
                   WHEN c.recencia_dias <= 180 THEN '91-180 dias'
                   WHEN c.recencia_dias <= 365 THEN '181-365 dias'
                   ELSE 'Mais de 1 ano'
               END AS faixa_recencia,
               CASE
                   WHEN c.recencia_dias <= 30 THEN 1
                   WHEN c.recencia_dias <= 90 THEN 2
                   WHEN c.recencia_dias <= 180 THEN 3
                   WHEN c.recencia_dias <= 365 THEN 4
                   ELSE 5
               END AS faixa_recencia_ordem
        FROM analise.cliente c
        JOIN analise.segmento s USING (segmento);
        COMMENT ON VIEW analise.vw_cliente IS
            'analise.cliente com ordem e ação do segmento, perfil (atacado/varejo) e faixa '
            'de recência, prontos para o Power BI.';

        -- Resumo por segmento (o mesmo que a página de segmentos mostra).
        CREATE VIEW analise.vw_segmento_resumo AS
        SELECT s.ordem, s.segmento, s.acao,
               count(c.cliente_id) AS clientes,
               -- nullif: com a base vazia, a divisão daria erro em vez de NULL.
               round(count(c.cliente_id)::numeric
                     / nullif(sum(count(c.cliente_id)) OVER (), 0), 4) AS pct_clientes,
               coalesce(sum(c.receita_liquida), 0) AS receita_liquida,
               round(coalesce(sum(c.receita_liquida), 0)
                     / nullif(sum(sum(c.receita_liquida)) OVER (), 0), 4) AS pct_receita,
               round(avg(c.recencia_dias), 0) AS recencia_media,
               round(avg(c.frequencia), 1) AS frequencia_media,
               round(avg(c.ticket_medio), 2) AS ticket_medio,
               count(c.cliente_id) FILTER (WHERE c.em_churn) AS em_churn,
               coalesce(sum(c.receita_12m) FILTER (WHERE c.em_churn), 0) AS receita_12m_em_risco,
               coalesce(sum(c.clv_previsto_6m), 0) AS clv_previsto_6m,
               count(c.cliente_id) FILTER (WHERE c.eh_atacado) AS atacado
        FROM analise.segmento s
        LEFT JOIN analise.cliente c USING (segmento)
        GROUP BY s.ordem, s.segmento, s.acao;
        COMMENT ON VIEW analise.vw_segmento_resumo IS
            'Um segmento por linha: tamanho, receita, recência, churn e CLV.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW analise.vw_segmento_resumo;
        DROP VIEW analise.vw_cliente;
        DROP VIEW analise.vw_receita_mes;
        """
    )
