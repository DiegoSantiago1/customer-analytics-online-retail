"""revisão: fuso fixo nas funções, churn por faixa, ingênuo sazonal e correções do dq

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03

Correções vindas das três revisões independentes (engenharia, QA e dados):

1. Fuso fixo. `timestamptz + interval '6 months'` é calculado no fuso da SESSÃO: o
   mesmo cenário dava resultados diferentes em Europe/London e em UTC (achado do QA).
   Toda função do pipeline passa a rodar com `SET timezone = 'Europe/London'`.
2. Mapa R x F monotônico: (R5, F3) era "Potenciais leais" enquanto (R4, F3) e
   (R3, F3) eram "Leais"; comprar mais recentemente rebaixava o cliente. Vira "Leais".
3. Churn por faixa de recência: a precisão da regra vem sobretudo de quem já sumiu há
   muito (91-180 dias: 46% não voltam, abaixo da taxa base de 48%; mais de 365 dias:
   85%). O cliente ganha status_churn (ativo, em_risco, inativo) e analise.churn_faixa
   guarda a taxa de "não voltou" por faixa em cada corte.
4. CLV: novo modelo de comparação, o ingênuo sazonal (a mesma janela um ano antes),
   mais justo que repetir os 6 meses anteriores.
5. Coortes: cancelamento anterior à primeira compra entra no mês 0; antes ele sumia e
   as coortes somavam £3.325 a mais que os clientes.
6. dq: o corte NULL (sem a aba nova) dava falso alarme; duas checagens novas (fatura
   mista com e sem cliente; coortes somam a receita dos clientes). Total: 18.

O downgrade restaura as definições anteriores lendo-as das próprias migrations antigas
(que não mudam mais), em vez de copiá-las à mão.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Funções do pipeline que passam a rodar sempre no fuso de Londres.
FUNCOES = [
    "limpo.recarregar()",
    "analise.data_param(text)",
    "analise.metricas_cliente(timestamptz)",
    "analise.rfm(timestamptz)",
    "analise.recarregar()",
    "analise.validar_churn(timestamptz, integer, integer[])",
    "analise.recarregar_churn()",
    "analise.recarregar_coortes()",
    "analise.retencao_segmento(timestamptz, integer)",
    "analise.clv_previsto(timestamptz, integer)",
    "analise.recarregar_clv()",
    "dq.verificar()",
]

VW_CLIENTE = """
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
"""

VW_SEGMENTO_RESUMO = """
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
               count(c.cliente_id) FILTER (WHERE c.status_churn = 'em_risco') AS em_risco,
               count(c.cliente_id) FILTER (WHERE c.status_churn = 'inativo') AS inativos,
               coalesce(sum(c.receita_12m) FILTER (WHERE c.em_churn), 0) AS receita_12m_em_risco,
               coalesce(sum(c.clv_previsto_6m), 0) AS clv_previsto_6m,
               count(c.cliente_id) FILTER (WHERE c.eh_atacado) AS atacado
        FROM analise.segmento s
        LEFT JOIN analise.cliente c USING (segmento)
        GROUP BY s.ordem, s.segmento, s.acao;
        COMMENT ON VIEW analise.vw_segmento_resumo IS
            'Um segmento por linha: tamanho, receita, recência, churn (em risco e inativos) '
            'e CLV.';
"""


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE analise.cliente ADD COLUMN status_churn text
            CHECK (status_churn IN ('ativo', 'em_risco', 'inativo'));
        COMMENT ON COLUMN analise.cliente.status_churn IS
            'ativo: até churn_dias sem comprar; em_risco: até 365 dias; inativo: mais de 365.';

        CREATE TABLE analise.churn_faixa (
            corte           date     NOT NULL,
            ordem           smallint NOT NULL,
            faixa           text     NOT NULL,
            clientes        integer  NOT NULL CHECK (clientes > 0),
            nao_voltaram    integer  NOT NULL CHECK (nao_voltaram >= 0),
            taxa_nao_voltou numeric(6, 4) NOT NULL CHECK (taxa_nao_voltou BETWEEN 0 AND 1),
            PRIMARY KEY (corte, ordem),
            CHECK (nao_voltaram <= clientes)
        );
        COMMENT ON TABLE analise.churn_faixa IS
            'Em cada corte: por faixa de recência, quantos clientes não compraram na janela '
            'seguinte. Mostra onde a regra de churn tem sinal e onde não tem.';

        ALTER TABLE analise.clv_validacao_cliente
            ADD COLUMN ingenuo_sazonal numeric(14, 2) NOT NULL DEFAULT 0;
        ALTER TABLE analise.clv_validacao DROP CONSTRAINT clv_validacao_modelo_check;
        ALTER TABLE analise.clv_validacao ADD CONSTRAINT clv_validacao_modelo_check
            CHECK (modelo IN ('previsto', 'ingenuo', 'ingenuo_sazonal'));

        UPDATE analise.segmento_rfm SET segmento = 'Leais' WHERE r = 5 AND f = 3;

        DROP VIEW analise.vw_segmento_resumo;
        DROP VIEW analise.vw_cliente;
        """
        + VW_CLIENTE
        + VW_SEGMENTO_RESUMO
        + """
        CREATE OR REPLACE FUNCTION dq.verificar() RETURNS integer
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
                SELECT coalesce(date_trunc('day', min(data_fatura::timestamp)), 'infinity') AS inicio
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
                SELECT 'limpo_fatura_mista', 'limpo',
                       'Faturas com linhas com cliente e linhas sem cliente (o pedido seria '
                       'atribuído inteiro ao cliente)',
                       '0',
                       (SELECT count(*)::text FROM (
                            SELECT fatura FROM limpo.fatura_linha GROUP BY fatura
                            HAVING count(*) FILTER (WHERE cliente_id IS NULL) > 0
                               AND count(*) FILTER (WHERE cliente_id IS NOT NULL) > 0) x)
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
                SELECT 'analise_coortes_receita_bate', 'analise',
                       'Receita líquida somada nas coortes = receita líquida dos clientes',
                       (SELECT coalesce(round(sum(receita_liquida), 3), 0)::text FROM analise.cliente),
                       (SELECT coalesce(round(sum(receita_liquida), 3), 0)::text
                        FROM analise.coorte_retencao)
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

CREATE OR REPLACE FUNCTION analise.recarregar_coortes() RETURNS void
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
            -- Cancelamento anterior à primeira compra (de uma venda de antes de dez/2009)
            -- entra no mês 0: sem isso ele sumia da grade e as coortes não somavam a
            -- mesma receita líquida dos clientes (achado da revisão de QA).
            receita_coorte AS (
                SELECT k.coorte, greatest(r.mes, k.coorte) AS mes, sum(r.receita) AS receita
                FROM receita r
                JOIN (SELECT DISTINCT cliente_id, coorte FROM compras) k USING (cliente_id)
                GROUP BY k.coorte, greatest(r.mes, k.coorte)
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

CREATE OR REPLACE FUNCTION analise.recarregar_clv() RETURNS void
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
                (cliente_id, segmento, previsto, ingenuo, real, ingenuo_sazonal)
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
                               AND p.data < v_corte + make_interval(months => v_h_val)), 0),
                   -- Ingênuo sazonal: a mesma janela, um ano antes.
                   coalesce((SELECT sum(p.receita_produto) FROM analise.pedido p
                             WHERE p.cliente_id = c.cliente_id
                               AND (p.eh_compra OR p.tipo = 'cancelamento')
                               AND p.data >= v_corte - interval '12 months'
                               AND p.data < v_corte - interval '12 months'
                                            + make_interval(months => v_h_val)), 0)
            FROM analise.clv_previsto(v_corte, v_h_val) c;

            INSERT INTO analise.clv_validacao
            WITH longo AS (
                SELECT 'previsto' AS modelo, cliente_id, previsto AS estimativa, real
                FROM analise.clv_validacao_cliente
                UNION ALL
                SELECT 'ingenuo', cliente_id, ingenuo, real FROM analise.clv_validacao_cliente
                UNION ALL
                SELECT 'ingenuo_sazonal', cliente_id, ingenuo_sazonal, real
                FROM analise.clv_validacao_cliente
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

CREATE OR REPLACE FUNCTION analise.recarregar_churn() RETURNS void
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
            TRUNCATE analise.churn_validacao, analise.churn_faixa;
            FOREACH v_corte IN ARRAY v_cortes LOOP
                INSERT INTO analise.churn_validacao
                SELECT (v_corte AT TIME ZONE 'Europe/London')::date, v_meses, v.*, v.dias = v_x
                FROM analise.validar_churn(
                    v_corte, v_meses, ARRAY[30, 60, 90, 120, 150, 180, 240, 365]
                ) v;

                -- Taxa de "não voltou" por faixa de recência no corte (achado da revisão
                -- de dados: a precisão da regra vem sobretudo de quem já sumiu há muito).
                INSERT INTO analise.churn_faixa
                SELECT (v_corte AT TIME ZONE 'Europe/London')::date, f.ordem, f.faixa,
                       count(*), count(*) FILTER (WHERE b.nao_voltou),
                       round(avg(b.nao_voltou::int), 4)
                FROM (
                    SELECT m.recencia_dias,
                           NOT EXISTS (
                               SELECT 1 FROM analise.pedido p
                               WHERE p.cliente_id = m.cliente_id AND p.eh_compra
                                 AND p.data >= v_corte
                                 AND p.data < v_corte + make_interval(months => v_meses)
                           ) AS nao_voltou
                    FROM analise.metricas_cliente(v_corte) m
                ) b
                CROSS JOIN LATERAL (
                    SELECT * FROM (VALUES
                        (1, 'até 90 dias', 0, 90),
                        (2, '91 a 180 dias', 91, 180),
                        (3, '181 a 365 dias', 181, 365),
                        (4, 'mais de 365 dias', 366, 1000000)
                    ) AS t(ordem, faixa, de, ate)
                    WHERE b.recencia_dias BETWEEN t.de AND t.ate
                ) f
                GROUP BY f.ordem, f.faixa;
            END LOOP;

            UPDATE analise.cliente c
            SET em_churn = c.recencia_dias > v_x,
                status_churn = CASE
                    WHEN c.recencia_dias <= v_x THEN 'ativo'
                    WHEN c.recencia_dias <= 365 THEN 'em_risco'
                    ELSE 'inativo'
                END,
                receita_12m = coalesce((
                    SELECT sum(p.receita_produto) FROM analise.pedido p
                    WHERE p.cliente_id = c.cliente_id
                      AND (p.eh_compra OR p.tipo = 'cancelamento')
                      AND p.data >= v_fim - interval '12 months' AND p.data < v_fim
                ), 0);
        END
        $$;

        """
    )
    for funcao in FUNCOES:
        op.execute(f"ALTER FUNCTION {funcao} SET timezone TO 'Europe/London'")


def _definicao_antiga(arquivo: str, inicio: str) -> str:
    """Bloco SQL de uma migration anterior, de `inicio` até o fim do corpo ($$;)."""
    texto = (Path(__file__).parent / arquivo).read_text(encoding="utf-8")
    i = texto.index(inicio)
    j = texto.index("$$;", i) + 3
    return texto[i:j].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _view_antiga(nome: str) -> str:
    texto = (Path(__file__).parent / "0009_views_bi.py").read_text(encoding="utf-8")
    i = texto.index(f"CREATE VIEW {nome} AS")
    j = texto.index(f"COMMENT ON VIEW {nome}", i)
    return texto[i:j]


def downgrade() -> None:
    for funcao in FUNCOES:
        op.execute(f"ALTER FUNCTION {funcao} RESET timezone")
    op.execute("DROP VIEW analise.vw_segmento_resumo; DROP VIEW analise.vw_cliente;")
    for arquivo, inicio in [
        ("0008_dq.py", "CREATE FUNCTION dq.verificar()"),
        ("0006_analise_coortes.py", "CREATE FUNCTION analise.recarregar_coortes()"),
        ("0007_analise_clv.py", "CREATE FUNCTION analise.recarregar_clv()"),
        ("0005_analise_churn.py", "CREATE FUNCTION analise.recarregar_churn()"),
    ]:
        op.execute(_definicao_antiga(arquivo, inicio))
    op.execute(
        """
        UPDATE analise.segmento_rfm SET segmento = 'Potenciais leais' WHERE r = 5 AND f = 3;
        DELETE FROM analise.clv_validacao WHERE modelo = 'ingenuo_sazonal';
        ALTER TABLE analise.clv_validacao DROP CONSTRAINT clv_validacao_modelo_check;
        ALTER TABLE analise.clv_validacao ADD CONSTRAINT clv_validacao_modelo_check
            CHECK (modelo IN ('previsto', 'ingenuo'));
        ALTER TABLE analise.clv_validacao_cliente DROP COLUMN ingenuo_sazonal;
        DROP TABLE analise.churn_faixa;
        ALTER TABLE analise.cliente DROP COLUMN status_churn;
        """
    )
    op.execute(_view_antiga("analise.vw_cliente"))
    op.execute(_view_antiga("analise.vw_segmento_resumo"))
