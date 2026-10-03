"""Regras de limpeza (schema limpo), com linhas montadas à mão e casos hostis.

Cada teste esvazia o bruto dentro da transação do `bd`, insere só as linhas do
cenário e roda limpo.recarregar(). O ROLLBACK do fim do teste devolve tudo.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from varejo.banco import Conexao

from .apoio import espera_erro, valor

pytestmark = pytest.mark.integracao

ANTIGA = "Year 2009-2010"
NOVA = "Year 2010-2011"


def linha(
    aba: str = NOVA,
    fatura: str = "536365",
    codigo: str = "85123A",
    quantidade: str = "6",
    data: str = "2011-01-10 10:00:00",
    preco: str = "2.55",
    cliente: str | None = "17850",
    pais: str = "United Kingdom",
    descricao: str | None = "WHITE HANGING HEART T-LIGHT HOLDER",
) -> tuple[str, str, str | None, str, str, str, str | None, str, str]:
    return (fatura, codigo, descricao, quantidade, data, preco, cliente, pais, aba)


def carregar_bruto(bd: Conexao, linhas: Sequence[tuple[object, ...]]) -> None:
    bd.execute("TRUNCATE bruto.fatura_linha")
    with bd.cursor() as cur:
        cur.executemany(
            "INSERT INTO bruto.fatura_linha (linha_origem, fatura, codigo_produto, descricao, "
            "quantidade, data_fatura, preco_unitario, cliente_id, pais, aba) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(i + 2, *dados) for i, dados in enumerate(linhas)],
        )
    bd.execute("SELECT limpo.recarregar()")


def tipos(bd: Conexao) -> list[tuple[str, str]]:
    return [
        (f, t)
        for f, t in bd.execute(
            "SELECT fatura, tipo FROM limpo.fatura_linha ORDER BY aba, linha_origem"
        )
    ]


def test_sobreposicao_fica_so_na_aba_nova(bd: Conexao) -> None:
    carregar_bruto(
        bd,
        [
            linha(ANTIGA, fatura="536000", data="2010-11-30 18:00:00"),  # antes do corte
            linha(ANTIGA, fatura="536365", data="2010-12-01 08:26:00"),  # cópia
            linha(NOVA, fatura="536365", data="2010-12-01 08:26:00"),  # original
            linha(NOVA, fatura="536400", data="2010-12-09 10:00:00"),
        ],
    )
    abas = bd.execute("SELECT aba, fatura FROM limpo.fatura_linha ORDER BY data_fatura").fetchall()
    assert abas == [(ANTIGA, "536000"), (NOVA, "536365"), (NOVA, "536400")]


def test_sem_a_aba_nova_a_aba_antiga_fica_inteira(bd: Conexao) -> None:
    # Hostil: sem a aba nova o corte seria NULL e descartaria tudo (bug evitado).
    carregar_bruto(bd, [linha(ANTIGA, data="2010-12-05 10:00:00"), linha(ANTIGA)])
    assert valor(bd, "SELECT count(*) FROM limpo.fatura_linha") == 2


def test_repeticao_dentro_da_aba_e_mantida(bd: Conexao) -> None:
    carregar_bruto(bd, [linha(), linha(), linha(quantidade="2")])
    assert valor(bd, "SELECT count(*) FROM limpo.fatura_linha") == 3


@pytest.mark.parametrize(
    ("fatura", "quantidade", "preco", "esperado"),
    [
        ("536365", "6", "2.55", "venda"),
        ("C536379", "-1", "27.50", "cancelamento"),
        ("536414", "56", "0", "sem_valor"),  # brinde / ajuste
        ("536415", "-96", "0", "sem_valor"),  # "damages", "lost"...
        ("A563185", "1", "11062.06", "ajuste_divida"),
        ("A563186", "1", "-11062.06", "ajuste_divida"),
        ("C496350", "1", "373.57", "anomalia"),  # cancelamento com quantidade positiva
        ("536500", "-5", "2.10", "anomalia"),  # venda com quantidade negativa
        ("536501", "5", "-2.10", "anomalia"),  # venda com preço negativo
    ],
)
def test_tipo_da_linha(
    bd: Conexao, fatura: str, quantidade: str, preco: str, esperado: str
) -> None:
    carregar_bruto(bd, [linha(fatura=fatura, quantidade=quantidade, preco=preco)])
    assert tipos(bd) == [(fatura, esperado)]


@pytest.mark.parametrize(
    ("codigo", "codigo_limpo", "eh_produto"),
    [
        ("85123A", "85123A", True),
        ("47503J ", "47503J", True),  # espaço no fim (1 caso real)
        ("PADS", "PADS", True),  # almofada vendida a £0,001: é produto
        ("DCGS0058", "DCGS0058", True),  # produto da loja do site
        ("POST", "POST", False),
        (" POST ", "POST", False),
        ("M", "M", False),
        ("m", "m", False),
        ("gift_0001_20", "gift_0001_20", False),
        ("AMAZONFEE", "AMAZONFEE", False),
    ],
)
def test_codigo_nao_produto(bd: Conexao, codigo: str, codigo_limpo: str, eh_produto: bool) -> None:
    carregar_bruto(bd, [linha(codigo=codigo)])
    linha_limpa = bd.execute("SELECT codigo_produto, eh_produto FROM limpo.fatura_linha").fetchone()
    assert linha_limpa == (codigo_limpo, eh_produto)


def test_horario_de_londres_vira_timestamptz(bd: Conexao) -> None:
    carregar_bruto(
        bd,
        [
            linha(fatura="536001", data="2010-07-01 12:00:00"),  # BST, UTC+1
            linha(fatura="536002", data="2010-12-01 12:00:00"),  # GMT, UTC+0
        ],
    )
    bd.execute("SET LOCAL timezone = 'UTC'")  # o resultado não pode depender da sessão
    datas = [d for (d,) in bd.execute("SELECT data_fatura FROM limpo.fatura_linha ORDER BY 1")]
    assert datas == [
        datetime(2010, 7, 1, 11, 0, tzinfo=UTC),
        datetime(2010, 12, 1, 12, 0, tzinfo=UTC),
    ]


def test_valor_e_tipos_numericos(bd: Conexao) -> None:
    carregar_bruto(
        bd, [linha(quantidade="3", preco="0.001"), linha(quantidade="-2", fatura="C536379")]
    )
    # numeric exato: 3 x 0,001 = 0,003 (em float seria 0,0030000000000000005)
    assert valor(bd, "SELECT valor FROM limpo.fatura_linha WHERE linha_origem = 2") == Decimal(
        "0.003"
    )
    assert valor(bd, "SELECT valor FROM limpo.fatura_linha WHERE linha_origem = 3") == Decimal(
        "-5.100"  # cancelamento: valor negativo, abate da receita
    )


def test_cliente_nulo_fica_nulo_e_cliente_ganha_pais_mais_frequente(bd: Conexao) -> None:
    carregar_bruto(
        bd,
        [
            linha(cliente=None),
            linha(cliente="12345", pais="France"),
            linha(cliente="12345", pais="France"),
            linha(cliente="12345", pais="Belgium"),
        ],
    )
    assert valor(bd, "SELECT count(*) FROM limpo.fatura_linha WHERE cliente_id IS NULL") == 1
    cliente = bd.execute("SELECT cliente_id, pais, n_paises FROM limpo.cliente").fetchall()
    assert cliente == [(12345, "France", 2)]


@pytest.mark.parametrize(
    ("estragada", "sqlstate"),
    [
        (linha(quantidade="abc"), "22P02"),
        (linha(quantidade="1.5"), "22P02"),
        (linha(preco="R$ 2"), "22P02"),
        (linha(cliente="17850.0"), "22P02"),
        (linha(data="31/12/2010"), "22008"),
        (linha(fatura="C1"), "23514"),  # formato de fatura recusado pelo CHECK
    ],
)
def test_texto_invalido_no_bruto_falha_e_nao_deixa_nada_pela_metade(
    bd: Conexao, estragada: tuple[object, ...], sqlstate: str
) -> None:
    carregar_bruto(bd, [linha(fatura="536001")])
    with espera_erro(bd, sqlstate):
        bd.execute("TRUNCATE bruto.fatura_linha")
        bd.execute(
            "INSERT INTO bruto.fatura_linha (linha_origem, fatura, codigo_produto, descricao, "
            "quantidade, data_fatura, preco_unitario, cliente_id, pais, aba) "
            "VALUES (2, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            estragada,
        )
        bd.execute("SELECT limpo.recarregar()")
    # A falha desfez a recarga inteira: o limpo anterior continua lá.
    assert tipos(bd) == [("536001", "venda")]


LINHA_LIMPA_OK: dict[str, object] = {
    "fatura": "536365",
    "tipo": "venda",
    "codigo_produto": "85123A",
    "quantidade": 6,
    "preco_unitario": 2.55,
    "cliente_id": 17850,
}


@pytest.mark.parametrize(
    ("coluna", "valor_ruim"),
    [
        ("fatura", "X536365"),
        ("fatura", "C536365"),  # venda com fatura de cancelamento
        ("cliente_id", 123),
        ("quantidade", -1),  # venda com quantidade negativa
        ("preco_unitario", 0),  # venda sem preço
        ("codigo_produto", " 85123A"),
        ("codigo_produto", ""),
        ("tipo", "devolucao"),
    ],
)
def test_checks_recusam_linha_incoerente(bd: Conexao, coluna: str, valor_ruim: object) -> None:
    valores = {**LINHA_LIMPA_OK, coluna: valor_ruim}
    with espera_erro(bd, "23514"):
        bd.execute(
            "INSERT INTO limpo.fatura_linha (aba, linha_origem, fatura, tipo, codigo_produto, "
            "quantidade, data_fatura, preco_unitario, cliente_id, pais, eh_produto) VALUES "
            "('t', 1, %(fatura)s, %(tipo)s, %(codigo_produto)s, %(quantidade)s, now(), "
            "%(preco_unitario)s, %(cliente_id)s, 'UK', true)",
            valores,
        )


def test_linha_coerente_entra(bd: Conexao) -> None:
    bd.execute(
        "INSERT INTO limpo.fatura_linha (aba, linha_origem, fatura, tipo, codigo_produto, "
        "quantidade, data_fatura, preco_unitario, cliente_id, pais, eh_produto) VALUES "
        "('t', 1, %(fatura)s, %(tipo)s, %(codigo_produto)s, %(quantidade)s, now(), "
        "%(preco_unitario)s, %(cliente_id)s, 'UK', true)",
        LINHA_LIMPA_OK,
    )


def test_recarregar_e_idempotente(bd: Conexao) -> None:
    carregar_bruto(bd, [linha(), linha(fatura="C536379", quantidade="-1")])
    bd.execute("SELECT limpo.recarregar()")
    bd.execute("SELECT limpo.recarregar()")
    assert valor(bd, "SELECT count(*) FROM limpo.fatura_linha") == 2
    assert valor(bd, "SELECT count(*) FROM limpo.cliente") == 1
