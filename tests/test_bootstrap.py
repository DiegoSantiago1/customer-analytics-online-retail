"""Testes unitários do bootstrap: citação de valores para o psql e linha de comando."""

import pytest

from varejo.bootstrap import (
    citar_valor_psql,
    comando_psql,
    conferir_usuarios,
    config_docker,
    montar_entrada_psql,
)
from varejo.config import ConfigError, carregar_config_banco

from .test_config import ENV_VALIDO


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("simples", "'simples'"),
        ("aspa'dentro", "'aspa''dentro'"),
        ("barra\\n", "'barra\\\\n'"),
        ("'; DROP ROLE honda; --", "'''; DROP ROLE honda; --'"),
    ],
)
def test_citar_valor_psql(valor: str, esperado: str) -> None:
    assert citar_valor_psql(valor) == esperado


@pytest.mark.parametrize("valor", ["linha\nnova", "retorno\r", "nulo\0"])
def test_quebra_de_linha_e_recusada(valor: str) -> None:
    # Uma quebra de linha encerraria o \set e o resto viraria comando do psql.
    with pytest.raises(ConfigError):
        citar_valor_psql(valor)


def test_entrada_define_todas_as_variaveis_antes_do_sql() -> None:
    entrada = montar_entrada_psql(carregar_config_banco(ENV_VALIDO), "SELECT 1;")
    linhas = entrada.splitlines()
    assert linhas[-1] == "SELECT 1;"
    nomes = [linha.split()[1] for linha in linhas[:-1]]
    assert nomes == ["usuario", "senha", "banco", "banco_teste", "bi_usuario", "bi_senha"]


def test_comando_psql_nao_leva_senha() -> None:
    comando = comando_psql("docker", "honda-vendas-db", "honda")
    assert "senha_de_teste" not in " ".join(comando)
    assert comando[:4] == ["docker", "exec", "-i", "honda-vendas-db"]


@pytest.mark.parametrize("container", ["", "-x", "a b", "a;rm"])
def test_container_invalido(container: str) -> None:
    env = {"VAREJO_DOCKER_CONTAINER": container, "VAREJO_DOCKER_SUPERUSER": "honda"}
    with pytest.raises(ConfigError, match="VAREJO_DOCKER_CONTAINER"):
        config_docker(env)


def test_superusuario_invalido() -> None:
    env = {"VAREJO_DOCKER_CONTAINER": "honda-vendas-db", "VAREJO_DOCKER_SUPERUSER": "Honda;"}
    with pytest.raises(ConfigError, match="VAREJO_DOCKER_SUPERUSER"):
        config_docker(env)


@pytest.mark.parametrize("variavel", ["VAREJO_DB_USER", "VAREJO_BI_USER"])
def test_usuario_do_projeto_nao_pode_ser_o_superusuario(variavel: str) -> None:
    config = carregar_config_banco({**ENV_VALIDO, variavel: "honda"})
    with pytest.raises(ConfigError, match="superusuário"):
        conferir_usuarios(config, "honda")


def test_usuarios_proprios_passam() -> None:
    conferir_usuarios(carregar_config_banco(ENV_VALIDO), "honda")
