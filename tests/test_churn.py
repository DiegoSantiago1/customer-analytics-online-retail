"""Regra de churn e validação temporal, com cenários montados à mão.

Corte principal: 10/06/2011 (dados até 09/06), janela de 6 meses (até 09/12/2011).
"""

from decimal import Decimal

import pytest

from varejo.banco import Conexao

from .apoio import cenario, compra, espera_erro, valor

pytestmark = pytest.mark.integracao


def matriz(bd: Conexao, dias: int, meses: int = 6) -> tuple[int, ...]:
    linha = bd.execute(
        "SELECT clientes, nao_voltaram, marcados, vp, fp, fn, vn "
        "FROM analise.validar_churn(analise.data_param('data_corte'), %s, ARRAY[%s])",
        (meses, dias),
    ).fetchone()
    assert linha is not None
    return tuple(linha)


@pytest.fixture
def quatro_clientes(bd: Conexao) -> None:
    """No corte (10/06/2011): A e B parados há 100 dias, C e D há 10 dias.
    A não volta, B volta; C volta, D não volta."""
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-03-02"),  # A: 100 dias antes do corte
            compra(10002, "536002", "2011-03-02"),  # B
            compra(10002, "536003", "2011-07-01"),  # B volta
            compra(10003, "536004", "2011-05-31"),  # C: 10 dias antes
            compra(10003, "536005", "2011-11-30"),  # C volta
            compra(10004, "536006", "2011-05-31"),  # D: não volta
            compra(10005, "536007", "2011-08-01"),  # E: só aparece depois do corte
        ],
    )


@pytest.mark.usefixtures("quatro_clientes")
def test_matriz_de_confusao(bd: Conexao) -> None:
    # X = 90: marcados A e B. Reais (não voltaram): A e D.
    # VP = A; FP = B; FN = D; VN = C. E não existia no corte.
    assert matriz(bd, 90) == (4, 2, 2, 1, 1, 1, 1)


@pytest.mark.usefixtures("quatro_clientes")
def test_metricas_da_validacao(bd: Conexao) -> None:
    linha = bd.execute(
        "SELECT precisao, recall, f1, acuracia "
        "FROM analise.validar_churn(analise.data_param('data_corte'), 6, ARRAY[90])"
    ).fetchone()
    assert linha == (Decimal("0.5000"),) * 4


@pytest.mark.usefixtures("quatro_clientes")
def test_limite_do_x_e_estrito(bd: Conexao) -> None:
    # Recência de A e B é exatamente 100: com X = 100 não estão em churn (> X, não >=).
    assert matriz(bd, 100)[2] == 0
    assert matriz(bd, 99)[2] == 2


def test_janela_exclui_o_ultimo_instante(bd: Conexao) -> None:
    # Volta em 10/12/2011 00:00 (Londres) = fora da janela de 6 meses.
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-10"),
            compra(10001, "536002", "2011-12-10 00:00:00"),
            compra(10002, "536003", "2011-01-10"),
            compra(10002, "536004", "2011-12-09 23:59:00"),
        ],
    )
    # Ambos marcados (151 dias); só o 10001 conta como "não voltou".
    assert matriz(bd, 90)[:4] == (2, 1, 2, 1)


def test_sem_marcados_precisao_e_nula_e_nao_divide_por_zero(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-06-01")])
    linha = bd.execute(
        "SELECT marcados, precisao, recall "
        "FROM analise.validar_churn(analise.data_param('data_corte'), 6, ARRAY[365])"
    ).fetchone()
    assert linha == (0, None, Decimal("0.0000"))


@pytest.mark.usefixtures("quatro_clientes")
def test_recarregar_churn_marca_clientes_no_fim(bd: Conexao) -> None:
    bd.execute("SELECT analise.recarregar_churn()")
    churn: dict[int, bool] = dict(
        bd.execute("SELECT cliente_id, em_churn FROM analise.cliente").fetchall()
    )
    # Fim = 10/12/2011. A: 283 dias; B: 162; C: 10; D: 193; E: 131.
    assert churn == {10001: True, 10002: True, 10003: False, 10004: True, 10005: True}
    escolhido = bd.execute(
        "SELECT corte, dias FROM analise.churn_validacao WHERE escolhido ORDER BY corte"
    ).fetchall()
    # O corte de dez/2010 não gera linhas: nenhum cliente do cenário existia antes dele.
    assert [(str(c), d) for c, d in escolhido] == [("2011-06-10", 90)]


def test_receita_12m_considera_cancelamentos_e_so_os_ultimos_12_meses(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-12-09", quantidade=10),  # fora dos 12 meses
            compra(10001, "536002", "2010-12-10 08:00:00", quantidade=5),  # dentro
            compra(10001, "C536003", "2011-02-01", quantidade=-2),
        ],
    )
    bd.execute("SELECT analise.recarregar_churn()")
    assert valor(bd, "SELECT receita_12m FROM analise.cliente") == Decimal("30.000")


@pytest.mark.usefixtures("quatro_clientes")
def test_checks_da_validacao(bd: Conexao) -> None:
    bd.execute("SELECT analise.recarregar_churn()")
    with espera_erro(bd, "23514"):
        bd.execute("UPDATE analise.churn_validacao SET vp = vp + 1")


def test_intervalo_entre_compras(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-10"),
            compra(10001, "536002", "2011-01-10 15:00:00"),  # mesmo dia
            compra(10001, "536003", "2011-02-09"),
        ],
    )
    dias = [
        d
        for (d,) in bd.execute(
            "SELECT dias_desde_anterior FROM analise.vw_intervalo_compra "
            "ORDER BY dia, dias_desde_anterior NULLS FIRST"
        )
    ]
    assert dias == [None, 0, 30]


@pytest.mark.parametrize(
    ("ultima", "status"),
    [
        ("2011-09-11", "ativo"),  # 90 dias antes do fim: ainda ativo (> 90 é churn)
        ("2011-09-10", "em_risco"),  # 91 dias
        ("2010-12-10", "em_risco"),  # 365 dias
        ("2010-12-09", "inativo"),  # 366 dias
    ],
)
def test_status_do_churn_por_faixa(bd: Conexao, ultima: str, status: str) -> None:
    cenario(bd, [compra(10001, "536001", ultima)])
    bd.execute("SELECT analise.recarregar_churn()")
    linha = bd.execute("SELECT status_churn, em_churn FROM analise.cliente").fetchone()
    assert linha == (status, status != "ativo")


@pytest.mark.usefixtures("quatro_clientes")
def test_taxa_de_nao_voltou_por_faixa(bd: Conexao) -> None:
    bd.execute("SELECT analise.recarregar_churn()")
    faixas = bd.execute(
        "SELECT faixa, clientes, nao_voltaram, taxa_nao_voltou FROM analise.churn_faixa "
        "WHERE corte = '2011-06-10' ORDER BY ordem"
    ).fetchall()
    # C e D a 10 dias (C volta); A e B a 100 dias (B volta).
    assert faixas == [
        ("até 90 dias", 2, 1, Decimal("0.5000")),
        ("91 a 180 dias", 2, 1, Decimal("0.5000")),
    ]
