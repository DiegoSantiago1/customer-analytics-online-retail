"""Funções de apoio usadas pelos testes e pelas fixtures."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

import psycopg
import pytest

from varejo.banco import Conexao


@contextmanager
def espera_erro(con: Conexao, sqlstate: str) -> Iterator[None]:
    """Exige que o bloco falhe no banco com o SQLSTATE informado.

    O bloco roda num savepoint: a falha desfaz só o bloco, e o teste pode continuar
    usando a conexão (sem o savepoint, a transação inteira ficaria abortada).
    """
    with pytest.raises(psycopg.Error) as info, con.transaction():
        yield
    assert info.value.sqlstate == sqlstate, (
        f"esperado {sqlstate}, veio {info.value.sqlstate}: {info.value}"
    )


def valor(con: Conexao, comando: str, parametros: Mapping[str, object] | None = None) -> object:
    """Primeira coluna da primeira linha de uma consulta."""
    resultado = con.execute(comando, parametros).fetchone()
    assert resultado is not None, f"consulta sem resultado: {comando}"
    return resultado[0]


# ---------------------------------------------------------------- cenários
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


def compra(
    cliente: int | None,
    fatura: str,
    data: str,
    quantidade: int = 1,
    preco: str = "10.00",
    codigo: str = "85123A",
    pais: str = "United Kingdom",
) -> tuple[str, str, str | None, str, str, str, str | None, str, str]:
    """Linha de venda (ou de cancelamento, com fatura "C..." e quantidade negativa)."""
    return linha(
        fatura=fatura,
        codigo=codigo,
        quantidade=str(quantidade),
        data=data if " " in data else f"{data} 10:00:00",
        preco=preco,
        cliente=None if cliente is None else str(cliente),
        pais=pais,
    )


def cenario(bd: Conexao, linhas: Sequence[tuple[object, ...]]) -> None:
    """Carrega o bruto e reconstrói limpo e analise dentro da transação do teste."""
    carregar_bruto(bd, linhas)
    bd.execute("SELECT analise.recarregar()")
