"""Views do Power BI e permissões do usuário somente leitura."""

from decimal import Decimal

import pytest
from psycopg import sql

from varejo.banco import Conexao

from .apoio import cenario, compra, espera_erro, valor

pytestmark = pytest.mark.integracao


def objetos(bd: Conexao, schema: str) -> list[str]:
    return [
        nome
        for (nome,) in bd.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s "
            "ORDER BY table_name",
            (schema,),
        )
    ]


@pytest.mark.parametrize("schema", ["analise", "dq"])
def test_bi_le_todas_as_tabelas_e_views(bd: Conexao, bd_bi: Conexao, schema: str) -> None:
    nomes = objetos(bd, schema)
    assert nomes, f"schema {schema} vazio"
    for nome in nomes:
        bd_bi.execute(sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(schema, nome)))


@pytest.mark.parametrize(
    "comando",
    [
        "SELECT limpo.recarregar()",
        "SELECT analise.recarregar()",
        "SELECT analise.recarregar_churn()",
        "SELECT dq.verificar()",
        "DELETE FROM analise.cliente",
        "UPDATE analise.parametro SET valor = '30' WHERE nome = 'churn_dias'",
    ],
)
def test_bi_nao_altera_nada(bd_bi: Conexao, comando: str) -> None:
    with espera_erro(bd_bi, "42501"):
        bd_bi.execute(comando)


def test_receita_mes_separa_as_origens(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(12345, "536001", "2011-01-10", quantidade=10),
            compra(12345, "536001", "2011-01-10", quantidade=1, preco="5.00", codigo="POST"),
            compra(None, "536002", "2011-01-11", quantidade=3),
            compra(12345, "C536003", "2011-01-12", quantidade=-2),
            compra(54321, "536004", "2011-02-01", quantidade=1),
        ],
    )
    jan = bd.execute(
        "SELECT venda_produto_com_cliente, venda_produto_sem_cliente, cancelamento_produto, "
        "receita_produto_liquida, frete_taxas_e_ajustes, pedidos, pedidos_com_cliente, "
        "clientes_ativos, clientes_novos, mes_parcial "
        "FROM analise.vw_receita_mes WHERE mes = '2011-01-01'"
    ).fetchone()
    assert jan == (
        Decimal("100.000"),
        Decimal("30.000"),
        Decimal("-20.000"),
        Decimal("110.000"),
        Decimal("5.000"),
        2,
        1,
        1,
        1,
        False,
    )
    assert valor(bd, "SELECT mes_parcial FROM analise.vw_receita_mes WHERE mes = '2011-02-01'")


def test_resumo_de_segmentos_soma_100_e_mostra_segmentos_vazios(bd: Conexao) -> None:
    cenario(bd, [compra(10001 + i, f"53600{i}", f"2011-0{1 + i}-10") for i in range(5)])
    bd.execute("SELECT analise.recarregar_churn(); SELECT analise.recarregar_clv()")
    linhas, pct_cli, pct_rec, clientes = bd.execute(
        "SELECT count(*), sum(pct_clientes), sum(pct_receita), sum(clientes) "
        "FROM analise.vw_segmento_resumo"
    ).fetchone()  # type: ignore[misc]
    assert linhas == 10  # todos os segmentos, mesmo os sem cliente
    assert clientes == 5
    assert abs(pct_cli - 1) < Decimal("0.001")
    assert abs(pct_rec - 1) < Decimal("0.001")


@pytest.mark.parametrize(
    ("dias", "faixa"),
    [(0, "0-30 dias"), (30, "0-30 dias"), (31, "31-90 dias"), (366, "Mais de 1 ano")],
)
def test_faixa_de_recencia(bd: Conexao, dias: int, faixa: str) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10")])
    bd.execute("UPDATE analise.cliente SET recencia_dias = %s", (dias,))
    assert valor(bd, "SELECT faixa_recencia FROM analise.vw_cliente") == faixa


def test_resumo_de_segmentos_com_base_vazia(bd: Conexao) -> None:
    # Hostil: sem clientes, a view não pode dividir por zero.
    cenario(bd, [])
    linha = bd.execute(
        "SELECT count(*), sum(clientes), max(pct_clientes) FROM analise.vw_segmento_resumo"
    ).fetchone()
    assert linha == (10, 0, None)
