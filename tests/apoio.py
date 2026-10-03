"""Funções de apoio usadas pelos testes e pelas fixtures."""

from collections.abc import Iterator, Mapping
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
    linha = con.execute(comando, parametros).fetchone()
    assert linha is not None, f"consulta sem resultado: {comando}"
    return linha[0]
