"""dq: checagens de qualidade de dados das três camadas

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03

dq.verificar() roda no fim do pipeline e grava uma linha por checagem em
dq.resultado (esperado, obtido, ok). O `python -m varejo.processar` falha (código 1)
se alguma checagem falhar: um número errado não chega ao Power BI em silêncio.

As restrições (CHECK, FK, NOT NULL) já impedem linhas impossíveis. O dq cobre o que
uma restrição de linha não enxerga: totais que precisam bater entre camadas,
premissas medidas que podem deixar de valer numa carga nova (a sobreposição idêntica
das abas, a lista de códigos que não são produto) e a forma das distribuições.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dq.resultado (
            verificacao   text PRIMARY KEY,
            camada        text NOT NULL CHECK (camada IN ('bruto', 'limpo', 'analise')),
            descricao     text NOT NULL,
            esperado      text NOT NULL,
            obtido        text NOT NULL,
            ok            boolean NOT NULL,
            verificado_em timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE dq.resultado IS
            'Resultado da última execução de dq.verificar(): uma linha por checagem.';

        CREATE FUNCTION dq.verificar() RETURNS integer
        LANGUAGE plpgsql AS $$
        DECLARE
            v_falhas integer;
        BEGIN
            TRUNCATE dq.resultado;

            -- Cada checagem: (nome, camada, descrição, esperado, obtido). ok = (esperado = obtido),
            -- exceto onde o esperado é uma condição (tratada no UPDATE do fim).
            INSERT INTO dq.resultado (verificacao, camada, descricao, esperado, obtido, ok)
            WITH
            corte AS (
                SELECT date_trunc('day', min(data_fatura::timestamp)) AS inicio
                FROM bruto.fatura_linha WHERE aba = 'Year 2010-2011'
            ),
            sobreposicao AS (
                SELECT b.* FROM bruto.fatura_linha b, corte c
                WHERE b.aba = 'Year 2009-2010' AND b.data_fatura::timestamp >= c.inicio
            ),
            antiga AS (
                SELECT fatura, codigo_produto, descricao, quantidade, data_fatura,
                       preco_unitario, cliente_id, pais
                FROM sobreposicao
            ),
            -- O mesmo período na aba nova: do início dela até a última data da antiga.
            nova AS (
                SELECT fatura, codigo_produto, descricao, quantidade, data_fatura,
                       preco_unitario, cliente_id, pais
                FROM bruto.fatura_linha
                WHERE aba = 'Year 2010-2011'
                  AND data_fatura::timestamp <= (SELECT max(data_fatura::timestamp)
                                                 FROM sobreposicao)
            ),
            checagens(verificacao, camada, descricao, esperado, obtido) AS (
                SELECT 'bruto_linhas_da_ultima_carga', 'bruto',
                       'Linhas no bruto = linhas registradas na última carga',
                       (SELECT linhas::text FROM bruto.carga ORDER BY id DESC LIMIT 1),
                       (SELECT count(*)::text FROM bruto.fatura_linha)
                UNION ALL
                SELECT 'bruto_formatos', 'bruto',
                       'Linhas com fatura, quantidade, preço, data ou cliente fora do formato',
                       '0',
                       (SELECT count(*)::text FROM bruto.fatura_linha
                        WHERE fatura !~ '^[CA]?[0-9]{6}$'
                           OR quantidade !~ '^-?[0-9]+$'
                           OR preco_unitario !~ '^-?[0-9]+(\\.[0-9]+)?$'
                           OR data_fatura !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
                           OR (cliente_id IS NOT NULL AND cliente_id !~ '^[0-9]{5}$'))
                UNION ALL
                SELECT 'sobreposicao_identica', 'limpo',
                       'Linhas da sobreposição das abas que existem só numa das abas (EXCEPT ALL)',
                       '0',
                       ((SELECT count(*) FROM (SELECT * FROM antiga EXCEPT ALL SELECT * FROM nova) x)
                        + (SELECT count(*) FROM (SELECT * FROM nova EXCEPT ALL SELECT * FROM antiga) y)
                       )::text
                UNION ALL
                SELECT 'limpo_linhas', 'limpo',
                       'Linhas no limpo = bruto - sobreposição',
                       ((SELECT count(*) FROM bruto.fatura_linha)
                        - (SELECT count(*) FROM sobreposicao))::text,
                       (SELECT count(*)::text FROM limpo.fatura_linha)
                UNION ALL
                SELECT 'limpo_valor_conservado', 'limpo',
                       'Soma de quantidade x preço: bruto sem sobreposição = limpo',
                       (SELECT round(sum(quantidade::numeric * preco_unitario::numeric), 3)::text
                        FROM bruto.fatura_linha b, corte c
                        WHERE NOT (b.aba = 'Year 2009-2010' AND b.data_fatura::timestamp >= c.inicio)),
                       (SELECT round(sum(valor), 3)::text FROM limpo.fatura_linha)
                UNION ALL
                SELECT 'limpo_anomalias_novas', 'limpo',
                       'Linhas do tipo anomalia além da conhecida (C496350)',
                       '0',
                       (SELECT count(*)::text FROM limpo.fatura_linha
                        WHERE tipo = 'anomalia' AND fatura <> 'C496350')
                UNION ALL
                SELECT 'limpo_codigo_nao_classificado', 'limpo',
                       'StockCodes fora do padrão de produto que não estão na lista de '
                       'não-produto nem nas exceções conhecidas (DCGS*, PADS, SP1002, 47503J)',
                       '0',
                       (SELECT count(DISTINCT codigo_produto)::text FROM limpo.fatura_linha
                        WHERE codigo_produto !~ '^[0-9]{5}[A-Za-z]{0,2}$'
                          AND codigo_produto NOT LIKE 'DCGS%'
                          AND codigo_produto NOT IN ('PADS', 'SP1002', '47503J')
                          AND codigo_produto NOT IN (SELECT codigo FROM limpo.codigo_nao_produto))
                UNION ALL
                SELECT 'limpo_hora_ambigua', 'limpo',
                       'Linhas entre 01:00 e 02:00 de Londres (hora ambígua/inexistente na '
                       'troca de horário de verão)',
                       '0',
                       (SELECT count(*)::text FROM limpo.fatura_linha
                        WHERE extract(hour FROM data_fatura AT TIME ZONE 'Europe/London') = 1)
                UNION ALL
                SELECT 'limpo_fatura_um_cliente', 'limpo',
                       'Faturas com mais de um cliente',
                       '0',
                       (SELECT count(*)::text FROM (
                            SELECT fatura FROM limpo.fatura_linha
                            GROUP BY fatura HAVING count(DISTINCT cliente_id) > 1) x)
                UNION ALL
                SELECT 'analise_pedidos_somam_o_limpo', 'analise',
                       'Soma dos pedidos = soma das linhas de venda e cancelamento do limpo',
                       (SELECT round(sum(valor), 3)::text FROM limpo.fatura_linha
                        WHERE tipo IN ('venda', 'cancelamento')),
                       (SELECT round(sum(receita_produto + receita_outros), 3)::text
                        FROM analise.pedido)
                UNION ALL
                SELECT 'analise_clientes_com_compra', 'analise',
                       'Clientes na foto final = clientes com ao menos uma compra',
                       (SELECT count(DISTINCT cliente_id)::text FROM analise.pedido
                        WHERE eh_compra AND cliente_id IS NOT NULL),
                       (SELECT count(*)::text FROM analise.cliente)
                UNION ALL
                SELECT 'analise_receita_liquida_bate', 'analise',
                       'Receita líquida dos clientes = compras - cancelamentos desses clientes',
                       (SELECT round(sum(p.receita_produto), 3)::text FROM analise.pedido p
                        WHERE (p.eh_compra OR p.tipo = 'cancelamento')
                          AND p.cliente_id IN (SELECT cliente_id FROM analise.cliente)),
                       (SELECT round(sum(receita_liquida), 3)::text FROM analise.cliente)
                UNION ALL
                SELECT 'analise_coortes_somam_clientes', 'analise',
                       'Soma dos tamanhos das coortes = clientes',
                       (SELECT count(*)::text FROM analise.cliente),
                       (SELECT coalesce(sum(tamanho), 0)::text FROM analise.coorte_retencao
                        WHERE meses_desde = 0)
                UNION ALL
                SELECT 'analise_quintis_r_e_m', 'analise',
                       'Maior grupo / menor grupo nas notas R e M (quintos de tamanho parecido)',
                       '<= 1.10',
                       (SELECT coalesce(round(greatest(
                            (SELECT max(n)::numeric / min(n) FROM (SELECT count(*) n FROM analise.cliente GROUP BY r) a),
                            (SELECT max(n)::numeric / min(n) FROM (SELECT count(*) n FROM analise.cliente GROUP BY m) b)
                        ), 2), 0)::text)
                UNION ALL
                SELECT 'analise_clv_preenchido', 'analise',
                       'Clientes sem CLV previsto ou sem marcação de churn',
                       '0',
                       (SELECT count(*)::text FROM analise.cliente
                        WHERE clv_previsto_6m IS NULL OR em_churn IS NULL)
                UNION ALL
                SELECT 'analise_churn_validado_nos_dois_cortes', 'analise',
                       'Cortes com a validação do X escolhido',
                       '2',
                       (SELECT count(*)::text FROM analise.churn_validacao WHERE escolhido)
            )
            SELECT verificacao, camada, descricao, coalesce(esperado, '(vazio)'),
                   coalesce(obtido, '(vazio)'), esperado IS NOT DISTINCT FROM obtido
            FROM checagens;

            -- Checagens cujo esperado é uma condição, e não um valor.
            UPDATE dq.resultado SET ok = obtido::numeric <= 1.10
            WHERE verificacao = 'analise_quintis_r_e_m';

            SELECT count(*) INTO v_falhas FROM dq.resultado WHERE NOT ok;
            RETURN v_falhas;
        END
        $$;
        COMMENT ON FUNCTION dq.verificar() IS
            'Roda as checagens de qualidade e devolve quantas falharam.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION dq.verificar();
        DROP TABLE dq.resultado;
        """
    )
