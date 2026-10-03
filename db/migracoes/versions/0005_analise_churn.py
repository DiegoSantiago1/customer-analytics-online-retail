"""analise: churn por regra (X dias sem comprar) com validação temporal

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03

Regra: o cliente está em churn se passou mais de X dias sem comprar.

Validação: numa data de corte, a regra marca os clientes usando só o passado; o
"real" é o cliente não ter comprado nos N meses seguintes. Precisão = dos marcados,
quantos de fato não voltaram; recall = dos que não voltaram, quantos foram marcados.
A comparação de vários X fica em analise.churn_validacao, e o X escolhido vai para
o parâmetro churn_dias (docs/DECISOES.md).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO analise.parametro (nome, valor, descricao) VALUES
            ('churn_dias', '90',
             'Cliente em churn: mais de X dias sem comprar. Escolhido pelo melhor F1 '
             'entre 90, 120 e 180 dias na validação de 10/06/2011.'),
            ('churn_janela_meses', '6',
             'Janela da validação: o cliente "não voltou" se não comprou nestes meses '
             'depois do corte.'),
            ('data_corte_robustez', '2010-12-10',
             'Segundo corte, para conferir se a escolha do X se mantém.');

        -- Intervalo (em dias de Londres) entre compras consecutivas de cada cliente.
        CREATE VIEW analise.vw_intervalo_compra AS
        WITH compras AS (
            SELECT cliente_id, (data AT TIME ZONE 'Europe/London')::date AS dia
            FROM analise.pedido
            WHERE eh_compra AND cliente_id IS NOT NULL
        )
        SELECT cliente_id, dia,
               dia - lag(dia) OVER (PARTITION BY cliente_id ORDER BY dia) AS dias_desde_anterior
        FROM compras;
        COMMENT ON VIEW analise.vw_intervalo_compra IS
            'Uma linha por compra; dias_desde_anterior é NULL na primeira compra.';

        -- Matriz de confusão da regra para cada X, num corte e numa janela.
        CREATE FUNCTION analise.validar_churn(
            p_corte timestamptz, p_meses integer, p_dias integer[]
        )
        RETURNS TABLE (
            dias integer, clientes integer, nao_voltaram integer, marcados integer,
            vp integer, fp integer, fn integer, vn integer,
            precisao numeric, recall numeric, f1 numeric, acuracia numeric
        )
        LANGUAGE sql STABLE AS $$
            WITH base AS (
                SELECT m.cliente_id, m.recencia_dias,
                       NOT EXISTS (
                           SELECT 1 FROM analise.pedido p
                           WHERE p.cliente_id = m.cliente_id AND p.eh_compra
                             AND p.data >= p_corte
                             AND p.data < p_corte + make_interval(months => p_meses)
                       ) AS nao_voltou
                FROM analise.metricas_cliente(p_corte) m
            ),
            matriz AS (
                SELECT x.dias,
                       count(*) AS n,
                       count(*) FILTER (WHERE b.nao_voltou) AS reais,
                       count(*) FILTER (WHERE b.recencia_dias > x.dias) AS marcados,
                       count(*) FILTER (WHERE b.recencia_dias > x.dias AND b.nao_voltou) AS vp,
                       count(*) FILTER (WHERE b.recencia_dias > x.dias AND NOT b.nao_voltou) AS fp,
                       count(*) FILTER (WHERE b.recencia_dias <= x.dias AND b.nao_voltou) AS fn,
                       count(*) FILTER (WHERE b.recencia_dias <= x.dias AND NOT b.nao_voltou) AS vn
                FROM base b CROSS JOIN unnest(p_dias) AS x(dias)
                GROUP BY x.dias
            )
            SELECT dias, n, reais, marcados, vp, fp, fn, vn,
                   round(vp::numeric / nullif(vp + fp, 0), 4),
                   round(vp::numeric / nullif(vp + fn, 0), 4),
                   round(2.0 * vp / nullif(2 * vp + fp + fn, 0), 4),
                   round((vp + vn)::numeric / nullif(n, 0), 4)
            FROM matriz
            ORDER BY dias
        $$;

        CREATE TABLE analise.churn_validacao (
            corte        date    NOT NULL,
            janela_meses integer NOT NULL,
            dias         integer NOT NULL,
            clientes     integer NOT NULL,
            nao_voltaram integer NOT NULL,
            marcados     integer NOT NULL,
            vp integer NOT NULL, fp integer NOT NULL, fn integer NOT NULL, vn integer NOT NULL,
            precisao     numeric(6, 4),
            recall       numeric(6, 4),
            f1           numeric(6, 4),
            acuracia     numeric(6, 4),
            escolhido    boolean NOT NULL,
            PRIMARY KEY (corte, dias),
            CHECK (vp + fp + fn + vn = clientes),
            CHECK (vp + fp = marcados),
            CHECK (vp + fn = nao_voltaram)
        );
        COMMENT ON TABLE analise.churn_validacao IS
            'Validação temporal da regra de churn para vários X, em dois cortes.';

        ALTER TABLE analise.cliente
            ADD COLUMN em_churn boolean,
            ADD COLUMN receita_12m numeric(14, 3);
        COMMENT ON COLUMN analise.cliente.em_churn IS
            'Mais de churn_dias dias sem comprar no fim da base.';
        COMMENT ON COLUMN analise.cliente.receita_12m IS
            'Receita líquida dos 12 meses antes do fim da base (base da "receita em risco").';

        CREATE FUNCTION analise.recarregar_churn() RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            v_x      integer := (SELECT valor::integer FROM analise.parametro WHERE nome = 'churn_dias');
            v_meses  integer := (SELECT valor::integer FROM analise.parametro WHERE nome = 'churn_janela_meses');
            v_fim    timestamptz := analise.data_param('data_fim');
            v_cortes timestamptz[] := ARRAY[
                analise.data_param('data_corte'), analise.data_param('data_corte_robustez')
            ];
            v_corte  timestamptz;
        BEGIN
            TRUNCATE analise.churn_validacao;
            FOREACH v_corte IN ARRAY v_cortes LOOP
                INSERT INTO analise.churn_validacao
                SELECT (v_corte AT TIME ZONE 'Europe/London')::date, v_meses, v.*, v.dias = v_x
                FROM analise.validar_churn(
                    v_corte, v_meses, ARRAY[30, 60, 90, 120, 150, 180, 240, 365]
                ) v;
            END LOOP;

            UPDATE analise.cliente c
            SET em_churn = c.recencia_dias > v_x,
                receita_12m = coalesce((
                    SELECT sum(p.receita_produto) FROM analise.pedido p
                    WHERE p.cliente_id = c.cliente_id
                      AND (p.eh_compra OR p.tipo = 'cancelamento')
                      AND p.data >= v_fim - interval '12 months' AND p.data < v_fim
                ), 0);
        END
        $$;
        COMMENT ON FUNCTION analise.recarregar_churn() IS
            'Valida a regra de churn nos cortes e marca os clientes no fim da base.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION analise.recarregar_churn();
        ALTER TABLE analise.cliente DROP COLUMN receita_12m, DROP COLUMN em_churn;
        DROP TABLE analise.churn_validacao;
        DROP FUNCTION analise.validar_churn(timestamptz, integer, integer[]);
        DROP VIEW analise.vw_intervalo_compra;
        DELETE FROM analise.parametro
        WHERE nome IN ('churn_dias', 'churn_janela_meses', 'data_corte_robustez');
        """
    )
