"""Coortes de retenção (analise.coorte_retencao), com cenários montados à mão."""

from decimal import Decimal

import pytest

from varejo.banco import Conexao

from .apoio import cenario, compra, espera_erro, valor

pytestmark = pytest.mark.integracao


def coortes(bd: Conexao) -> dict[tuple[str, int], tuple[int, int, Decimal, Decimal]]:
    bd.execute("SELECT analise.recarregar_coortes()")
    return {
        (str(c), m): (t, a, r, rec)
        for c, m, t, a, r, rec in bd.execute(
            "SELECT coorte, meses_desde, tamanho, ativos, retencao, receita_liquida "
            "FROM analise.coorte_retencao"
        )
    }


def test_retencao_por_coorte_com_meses_vazios(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-05"),
            compra(10001, "536002", "2011-03-20"),  # volta no mês 2
            compra(10002, "536003", "2011-01-25"),  # não volta
            compra(10003, "536004", "2011-02-10"),  # outra coorte
            compra(10003, "536005", "2011-03-01"),
        ],
    )
    c = coortes(bd)
    assert c[("2011-01-01", 0)][:3] == (2, 2, Decimal("1.0000"))
    assert c[("2011-01-01", 1)][:3] == (2, 0, Decimal("0.0000"))  # mês sem compra = 0
    assert c[("2011-01-01", 2)][:3] == (2, 1, Decimal("0.5000"))
    assert c[("2011-02-01", 1)][:3] == (1, 1, Decimal("1.0000"))
    # A grade vai de cada coorte até o último mês da base (mar/2011): 3 + 2 linhas.
    assert len(c) == 5


def test_varias_compras_no_mes_contam_um_cliente(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-05"),
            compra(10001, "536002", "2011-01-06"),
            compra(10001, "536003", "2011-01-07"),
        ],
    )
    assert coortes(bd)[("2011-01-01", 0)][:2] == (1, 1)


def test_receita_liquida_abate_cancelamento_do_mes(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-05", quantidade=10),
            compra(10001, "C536002", "2011-02-05", quantidade=-3),
            compra(10001, "536003", "2011-02-07", quantidade=1),
        ],
    )
    c = coortes(bd)
    assert c[("2011-01-01", 0)][3] == Decimal("100.000")
    assert c[("2011-01-01", 1)][3] == Decimal("-20.000")  # 10 - 30


def test_primeiro_mes_da_base_e_pre_existente_e_ultimo_e_parcial(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2009-12-05"),
            compra(10002, "536002", "2010-01-05"),
            compra(10002, "536003", "2010-02-05"),
        ],
    )
    bd.execute("SELECT analise.recarregar_coortes()")
    flags = bd.execute(
        "SELECT coorte, bool_or(pre_existente), "
        "array_agg(mes ORDER BY mes) FILTER (WHERE mes_parcial) "
        "FROM analise.coorte_retencao GROUP BY coorte ORDER BY coorte"
    ).fetchall()
    assert [(str(c), p, [str(m) for m in parciais]) for c, p, parciais in flags] == [
        ("2009-12-01", True, ["2010-02-01"]),
        ("2010-01-01", False, ["2010-02-01"]),
    ]


def test_mes_de_londres_na_virada(bd: Conexao) -> None:
    # 31/07/2011 23:30 em Londres (BST) = 22:30 UTC: ainda é julho.
    cenario(bd, [compra(10001, "536001", "2011-07-31 23:30:00")])
    bd.execute("SET LOCAL timezone = 'UTC'")
    assert str(coortes(bd).popitem()[0][0]) == "2011-07-01"


def test_cliente_sem_id_nao_entra(bd: Conexao) -> None:
    cenario(bd, [compra(None, "536001", "2011-01-05"), compra(10001, "536002", "2011-01-05")])
    assert coortes(bd)[("2011-01-01", 0)][0] == 1


def test_checks(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-05"), compra(10001, "536002", "2011-02-05")])
    bd.execute("SELECT analise.recarregar_coortes()")
    with espera_erro(bd, "23514"):
        bd.execute("UPDATE analise.coorte_retencao SET ativos = tamanho + 1")
    with espera_erro(bd, "23514"):
        bd.execute("UPDATE analise.coorte_retencao SET ativos = 0 WHERE meses_desde = 0")
    assert valor(bd, "SELECT count(*) FROM analise.coorte_retencao") == 2


def test_cancelamento_antes_da_primeira_compra_entra_no_mes_zero(bd: Conexao) -> None:
    # Cancelamento de uma venda de antes da base (jan) e primeira compra em fev: a receita
    # somada nas coortes precisa bater com a receita líquida do cliente (revisão de QA).
    cenario(
        bd,
        [
            compra(10001, "C536001", "2011-01-10", quantidade=-2),
            compra(10001, "536002", "2011-02-10", quantidade=5),
        ],
    )
    c = coortes(bd)
    assert c[("2011-02-01", 0)][3] == Decimal("30.000")  # 50 - 20
    soma = valor(bd, "SELECT sum(receita_liquida) FROM analise.coorte_retencao")
    assert soma == valor(bd, "SELECT receita_liquida FROM analise.cliente")
