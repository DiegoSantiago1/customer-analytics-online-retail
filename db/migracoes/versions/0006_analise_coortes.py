"""analise: coortes de retenção pelo mês da primeira compra

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03

Cada cliente pertence à coorte do mês da primeira compra. Para cada coorte e cada
"mês desde a primeira compra" (0, 1, 2...), conta quantos clientes compraram naquele
mês. Retenção = ativos / tamanho da coorte.

Dez/2009 é o primeiro mês da base: quem compra nele não é necessariamente cliente
novo, só é o primeiro registro que temos. Essa coorte é marcada como
'pré-existentes' e fica separada nas médias. Dez/2011 vai só até o dia 9 e é marcado
como mês parcial.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analise.coorte_retencao (
            coorte           date     NOT NULL CHECK (extract(day FROM coorte) = 1),
            pre_existente    boolean  NOT NULL,
            tamanho          integer  NOT NULL CHECK (tamanho > 0),
            meses_desde      integer  NOT NULL CHECK (meses_desde >= 0),
            mes              date     NOT NULL,
            mes_parcial      boolean  NOT NULL,
            ativos           integer  NOT NULL CHECK (ativos >= 0),
            retencao         numeric(6, 4) NOT NULL CHECK (retencao BETWEEN 0 AND 1),
            receita_liquida  numeric(14, 3) NOT NULL,
            PRIMARY KEY (coorte, meses_desde),
            CHECK (ativos <= tamanho),
            -- No mês 0 todos os clientes da coorte compraram (é a definição de coorte).
            CHECK (meses_desde <> 0 OR ativos = tamanho)
        );
        COMMENT ON TABLE analise.coorte_retencao IS
            'Retenção mensal por coorte (mês da primeira compra). Meses sem compra '
            'aparecem com 0 ativos, para o heatmap não ter buracos.';

        CREATE FUNCTION analise.recarregar_coortes() RETURNS void
        LANGUAGE sql AS $$
            TRUNCATE analise.coorte_retencao;

            INSERT INTO analise.coorte_retencao
            WITH compras AS (
                SELECT cliente_id, mes,
                       -- Coorte = primeiro mês de compra do cliente (window function).
                       min(mes) OVER (PARTITION BY cliente_id) AS coorte
                FROM analise.pedido
                WHERE eh_compra AND cliente_id IS NOT NULL
            ),
            -- Receita líquida do mês: compras menos cancelamentos daquele mês.
            receita AS (
                SELECT cliente_id, mes, sum(receita_produto) AS receita
                FROM analise.pedido
                WHERE cliente_id IS NOT NULL AND (eh_compra OR tipo = 'cancelamento')
                GROUP BY cliente_id, mes
            ),
            tamanho AS (
                SELECT coorte, count(DISTINCT cliente_id) AS tamanho
                FROM compras GROUP BY coorte
            ),
            ativos AS (
                SELECT c.coorte, c.mes, count(DISTINCT c.cliente_id) AS ativos
                FROM compras c GROUP BY c.coorte, c.mes
            ),
            receita_coorte AS (
                SELECT k.coorte, r.mes, sum(r.receita) AS receita
                FROM receita r
                JOIN (SELECT DISTINCT cliente_id, coorte FROM compras) k USING (cliente_id)
                GROUP BY k.coorte, r.mes
            ),
            limites AS (
                SELECT min(mes) AS primeiro, max(mes) AS ultimo FROM analise.pedido
            ),
            -- Grade completa: cada coorte x cada mês dela até o último mês da base.
            grade AS (
                SELECT t.coorte, t.tamanho, m::date AS mes
                FROM tamanho t, limites l,
                     generate_series(t.coorte, l.ultimo, interval '1 month') AS m
            )
            SELECT g.coorte,
                   g.coorte = l.primeiro,
                   g.tamanho,
                   (extract(year FROM age(g.mes, g.coorte)) * 12
                    + extract(month FROM age(g.mes, g.coorte)))::integer,
                   g.mes,
                   g.mes = l.ultimo,
                   coalesce(a.ativos, 0),
                   round(coalesce(a.ativos, 0)::numeric / g.tamanho, 4),
                   coalesce(r.receita, 0)
            FROM grade g
            CROSS JOIN limites l
            LEFT JOIN ativos a ON a.coorte = g.coorte AND a.mes = g.mes
            LEFT JOIN receita_coorte r ON r.coorte = g.coorte AND r.mes = g.mes;

            ANALYZE analise.coorte_retencao;
        $$;
        COMMENT ON FUNCTION analise.recarregar_coortes() IS
            'Reconstrói a tabela de coortes a partir de analise.pedido.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION analise.recarregar_coortes();
        DROP TABLE analise.coorte_retencao;
        """
    )
