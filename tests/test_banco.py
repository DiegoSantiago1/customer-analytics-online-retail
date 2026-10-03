"""Testes de integração do banco criado pelo bootstrap e da migração dos schemas."""

import pytest
from psycopg import errors, sql

from varejo.banco import Conexao, conectar
from varejo.config import ConfigBanco

from .apoio import espera_erro, valor

pytestmark = pytest.mark.integracao

SCHEMAS = ("bruto", "limpo", "analise", "dq")


def test_conecta_como_usuario_do_projeto(bd: Conexao, banco_teste: ConfigBanco) -> None:
    assert valor(bd, "SELECT current_user") == banco_teste.usuario
    assert valor(bd, "SELECT current_database()") == banco_teste.nome


def test_fuso_do_banco_e_londres(bd: Conexao) -> None:
    assert valor(bd, "SHOW timezone") == "Europe/London"


def test_horario_de_verao_de_londres(bd: Conexao) -> None:
    # 01/07/2010 12:00 em Londres é BST (UTC+1); 01/12/2010 12:00 é GMT (UTC+0).
    assert valor(bd, "SELECT '2010-07-01 12:00'::timestamptz = '2010-07-01 11:00Z'") is True
    assert valor(bd, "SELECT '2010-12-01 12:00'::timestamptz = '2010-12-01 12:00Z'") is True


def test_banco_usa_utf8(bd: Conexao) -> None:
    assert valor(bd, "SHOW server_encoding") == "UTF8"


def test_usuario_nao_tem_privilegios_de_servidor(bd: Conexao) -> None:
    linha = bd.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert linha == (False, False, False, False, False)


def test_usuario_nao_consegue_criar_role(bd: Conexao) -> None:
    with espera_erro(bd, "42501"):
        bd.execute("CREATE ROLE intruso LOGIN")


def test_usuario_nao_consegue_criar_banco(banco_teste: ConfigBanco) -> None:
    # CREATE DATABASE não roda dentro de transação: precisa de autocommit.
    with conectar(banco_teste) as con:
        con.autocommit = True
        with pytest.raises(errors.InsufficientPrivilege):
            con.execute("CREATE DATABASE intruso")


def test_publico_nao_conecta(bd: Conexao) -> None:
    # Só o dono e o grupo de leitura têm CONNECT; o PUBLIC foi revogado.
    sql = "SELECT has_database_privilege('public', current_database(), 'CONNECT')"
    assert valor(bd, sql) is False


def test_schemas_existem(bd: Conexao) -> None:
    linhas = bd.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%(s)s)", {"s": list(SCHEMAS)}
    )
    assert {linha[0] for linha in linhas} == set(SCHEMAS)


def _tabela(schema: str) -> sql.Identifier:
    return sql.Identifier(schema, "t_permissao")


def test_bi_le_analise_e_dq_mas_nao_bruto_nem_limpo(bd: Conexao, bd_bi: Conexao) -> None:
    # As tabelas precisam ser confirmadas (COMMIT) para a outra conexão enxergar.
    for schema in SCHEMAS:
        bd.execute(sql.SQL("CREATE TABLE {} (x int)").format(_tabela(schema)))
        bd.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(_tabela(schema)))
    bd.commit()
    try:
        assert valor(bd_bi, "SELECT x FROM analise.t_permissao") == 1
        assert valor(bd_bi, "SELECT x FROM dq.t_permissao") == 1
        for schema in ("bruto", "limpo"):
            with espera_erro(bd_bi, "42501"):
                bd_bi.execute(sql.SQL("SELECT x FROM {}").format(_tabela(schema)))
        with espera_erro(bd_bi, "42501"):
            bd_bi.execute("INSERT INTO analise.t_permissao VALUES (2)")
    finally:
        # Encerra a transação do BI: ela segura um lock de leitura nas tabelas e o
        # DROP TABLE ficaria esperando para sempre (o teste travou assim na 1ª versão).
        bd_bi.rollback()
        for schema in SCHEMAS:
            bd.execute(sql.SQL("DROP TABLE {}").format(_tabela(schema)))
        bd.commit()
