"""Pedidos, métricas por cliente e RFM (schema analise), com cenários montados à mão.

A data de fim da base é 10/12/2011 (parâmetro data_fim); as compras dos cenários
ficam antes dela.
"""

from decimal import Decimal

import pytest

from varejo.banco import Conexao

from .apoio import cenario, compra, espera_erro, valor

pytestmark = pytest.mark.integracao

FIM = "analise.data_param('data_fim')"


def metricas(bd: Conexao, cliente: int, data_ref: str = FIM) -> dict[str, object]:
    cur = bd.execute(
        f"SELECT * FROM analise.metricas_cliente({data_ref}) WHERE cliente_id = %s",  # noqa: S608
        (cliente,),
    )
    linha = cur.fetchone()
    assert linha is not None, f"cliente {cliente} sem métricas"
    assert cur.description is not None
    return {d.name: v for d, v in zip(cur.description, linha, strict=True)}


def test_pedido_separa_produto_de_frete_e_frete_sozinho_nao_e_compra(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(12345, "536001", "2011-01-10", quantidade=2, preco="10.00"),
            compra(12345, "536001", "2011-01-10", quantidade=1, preco="15.00", codigo="POST"),
            compra(12345, "536002", "2011-02-10", quantidade=1, preco="15.00", codigo="POST"),
        ],
    )
    pedidos = bd.execute(
        "SELECT fatura, receita_produto, receita_outros, unidades, eh_compra, mes "
        "FROM analise.pedido ORDER BY fatura"
    ).fetchall()
    assert [(f, rp, ro, u, c) for f, rp, ro, u, c, _ in pedidos] == [
        ("536001", Decimal("20.000"), Decimal("15.000"), 2, True),
        ("536002", Decimal("0.000"), Decimal("15.000"), 0, False),
    ]
    assert str(pedidos[0][5]) == "2011-01-01"
    assert metricas(bd, 12345)["frequencia"] == 1


def test_metricas_com_cancelamento(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(12345, "536001", "2011-01-10", quantidade=10, preco="10.00"),
            compra(12345, "536002", "2011-03-10", quantidade=5, preco="10.00"),
            compra(12345, "C536003", "2011-03-11", quantidade=-3, preco="10.00"),
        ],
    )
    m = metricas(bd, 12345)
    assert m["frequencia"] == 2  # o cancelamento não é compra
    assert m["receita_bruta"] == Decimal("150.000")
    assert m["valor_cancelado"] == Decimal("30.000")
    assert m["receita_liquida"] == Decimal("120.000")
    assert m["ticket_medio"] == Decimal("60.00")
    assert m["taxa_cancelamento"] == Decimal("0.2000")
    assert m["unidades_por_pedido"] == Decimal("7.5")
    # Última compra em 10/03/2011; fim em 10/12/2011 = 275 dias.
    assert m["recencia_dias"] == 275


def test_metricas_nao_olham_o_futuro(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(12345, "536001", "2011-01-10"),
            compra(12345, "536002", "2011-06-09 21:00:00"),  # antes do corte
            compra(12345, "536003", "2011-06-10 08:00:00"),  # depois do corte
            compra(12345, "C536004", "2011-07-01", quantidade=-1),  # cancelamento futuro
            compra(54321, "536005", "2011-08-01"),  # cliente que só existe depois
        ],
    )
    m = metricas(bd, 12345, "analise.data_param('data_corte')")
    assert (m["frequencia"], m["valor_cancelado"], m["recencia_dias"]) == (2, 0, 1)
    corte = "SELECT count(*) FROM analise.metricas_cliente(analise.data_param('data_corte'))"
    assert valor(bd, corte) == 1


def test_recencia_conta_dias_de_londres(bd: Conexao) -> None:
    # 09/12/2011 23:30 em Londres ainda é dia 9: recência 1 no fim (10/12).
    cenario(bd, [compra(12345, "536001", "2011-12-09 21:30:00")])
    bd.execute("SET LOCAL timezone = 'America/Sao_Paulo'")  # não pode depender da sessão
    assert metricas(bd, 12345)["recencia_dias"] == 1


def test_cliente_so_com_cancelamento_fica_fora(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(12345, "536001", "2011-01-10"),
            compra(54321, "C536002", "2011-01-10", quantidade=-1),
        ],
    )
    clientes = [c for (c,) in bd.execute("SELECT cliente_id FROM analise.cliente")]
    assert clientes == [12345]


def test_cliente_sem_id_nao_entra_mas_o_pedido_sim(bd: Conexao) -> None:
    cenario(bd, [compra(None, "536001", "2011-01-10"), compra(12345, "536002", "2011-01-10")])
    assert valor(bd, "SELECT count(*) FROM analise.pedido") == 2
    assert valor(bd, "SELECT count(*) FROM analise.cliente") == 1


def notas(bd: Conexao) -> dict[int, tuple[int, int, int, str]]:
    return {
        c: (r, f, m, s)
        for c, r, f, m, s in bd.execute("SELECT cliente_id, r, f, m, segmento FROM analise.cliente")
    }


def test_empates_recebem_a_mesma_nota(bd: Conexao) -> None:
    # 10 clientes: 4 com 1 compra (empatados), os outros com 2 a 7 compras.
    linhas = []
    for i, n in enumerate([1, 1, 1, 1, 2, 3, 4, 5, 6, 7]):
        cliente = 10001 + i
        linhas += [
            compra(cliente, f"{cliente - 10000:03d}{k:03d}", f"2011-0{k + 1}-15") for k in range(n)
        ]
    cenario(bd, linhas)
    resultado = notas(bd)
    assert {resultado[c][1] for c in (10001, 10002, 10003, 10004)} == {1}
    # Quem tem mais compras nunca tem nota F menor.
    fs = [resultado[10001 + i][1] for i in range(10)]
    assert fs == sorted(fs)
    assert fs[-1] == 5


def test_nota_r_maior_para_quem_comprou_mais_recente(bd: Conexao) -> None:
    datas = ["2010-01-10", "2010-06-10", "2011-01-10", "2011-06-10", "2011-12-01"]
    cenario(bd, [compra(10001 + i, f"53600{i}", d) for i, d in enumerate(datas)])
    resultado = notas(bd)
    assert [resultado[10001 + i][0] for i in range(5)] == [1, 2, 3, 4, 5]


def test_liquido_nao_positivo_fica_com_m_minimo_e_flag(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-10", quantidade=1, preco="500.00"),
            compra(10001, "C536002", "2011-01-11", quantidade=-1, preco="500.00"),
            compra(10002, "536003", "2011-01-10", quantidade=1, preco="5.00"),
            compra(10003, "536004", "2011-01-10", quantidade=1, preco="50.00"),
        ],
    )
    linha = bd.execute(
        "SELECT receita_liquida, m, liquido_nao_positivo FROM analise.cliente "
        "WHERE cliente_id = 10001"
    ).fetchone()
    assert linha == (Decimal("0.000"), 1, True)
    assert valor(bd, "SELECT count(*) FROM analise.cliente WHERE liquido_nao_positivo") == 1


@pytest.mark.parametrize(("unidades", "atacado"), [(399, False), (400, True), (1000, True)])
def test_flag_de_atacado_no_limite(bd: Conexao, unidades: int, atacado: bool) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10", quantidade=unidades, preco="1.00")])
    assert valor(bd, "SELECT eh_atacado FROM analise.cliente") is atacado


def test_segmentos_extremos(bd: Conexao) -> None:
    # Campeão: compra muito e recente. Perdido: uma compra antiga.
    linhas = [compra(10001, f"5300{k:02d}", f"2011-{k + 1:02d}-20") for k in range(11)]
    linhas += [compra(10002, "536100", "2010-01-05")]
    linhas += [compra(10003 + i, f"5362{i:02d}", "2011-05-05") for i in range(8)]
    cenario(bd, linhas)
    resultado = notas(bd)
    assert resultado[10001][3] == "Campeões"
    assert resultado[10002][3] == "Perdidos"


def test_mapa_rfm_cobre_as_25_combinacoes(bd: Conexao) -> None:
    assert valor(bd, "SELECT count(*) FROM analise.segmento_rfm") == 25
    sem_ordem = (
        "SELECT count(*) FROM analise.segmento_rfm "
        "LEFT JOIN analise.segmento USING (segmento) WHERE ordem IS NULL"
    )
    assert valor(bd, sem_ordem) == 0


def test_cliente_bate_com_a_funcao_rfm(bd: Conexao) -> None:
    linhas = [
        compra(10001 + i % 7, f"5{i:05d}", f"2011-{1 + i % 11:02d}-0{1 + i % 9}") for i in range(40)
    ]
    cenario(bd, linhas)
    diferentes = valor(
        bd,
        "SELECT count(*) FROM (SELECT cliente_id, r, f, m, segmento FROM analise.cliente "
        "EXCEPT SELECT cliente_id, r, f, m, segmento "
        "FROM analise.rfm(analise.data_param('data_fim'))) x",
    )
    assert diferentes == 0


def test_checks_do_cliente(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10")])
    with espera_erro(bd, "23514"):
        bd.execute("UPDATE analise.cliente SET receita_liquida = receita_liquida + 1")
    with espera_erro(bd, "23503"):
        bd.execute("UPDATE analise.cliente SET segmento = 'Inventado'")


def test_recarregar_e_idempotente(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10"), compra(10002, "536002", "2011-02-10")])
    bd.execute("SELECT analise.recarregar()")
    assert valor(bd, "SELECT count(*) FROM analise.pedido") == 2
    assert valor(bd, "SELECT count(*) FROM analise.cliente") == 2
