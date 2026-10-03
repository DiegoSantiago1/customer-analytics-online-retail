"""Testes unitários da configuração (não precisam do banco)."""

import pytest

from varejo.config import ConfigError, carregar_config_banco

ENV_VALIDO = {
    "VAREJO_DB_HOST": "127.0.0.1",
    "VAREJO_DB_PORT": "5432",
    "VAREJO_DB_NAME": "retail",
    "VAREJO_DB_NAME_TESTE": "retail_teste",
    "VAREJO_DB_USER": "varejo",
    "VAREJO_DB_PASSWORD": "senha_de_teste",
    "VAREJO_BI_USER": "varejo_bi",
    "VAREJO_BI_PASSWORD": "senha_bi_de_teste",
}


def env_com(**alteracoes: str) -> dict[str, str]:
    return {**ENV_VALIDO, **alteracoes}


def test_config_valida_monta_url_do_psycopg() -> None:
    url = carregar_config_banco(ENV_VALIDO).url()
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database, url.username) == (
        "127.0.0.1",
        5432,
        "retail",
        "varejo",
    )


def test_senha_nao_aparece_em_repr_nem_na_url_impressa() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    assert "senha_de_teste" not in repr(config)
    assert "senha_bi_de_teste" not in repr(config)
    assert "senha_de_teste" not in str(config.url())  # o SQLAlchemy mascara com ***


@pytest.mark.parametrize(
    "senha", ["p@ss:w/o#rd%", "aspa'simples", 'aspa"dupla', "ç ã ü", " espaço "]
)
def test_senha_com_caracteres_especiais_chega_intacta(senha: str) -> None:
    assert carregar_config_banco(env_com(VAREJO_DB_PASSWORD=senha)).url().password == senha


@pytest.mark.parametrize("variavel", list(ENV_VALIDO))
def test_variavel_ausente_gera_erro_claro(variavel: str) -> None:
    env = {k: v for k, v in ENV_VALIDO.items() if k != variavel}
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env)


@pytest.mark.parametrize("variavel", list(ENV_VALIDO))
def test_variavel_em_branco_gera_erro(variavel: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env_com(**{variavel: "   "}))


@pytest.mark.parametrize("porta", ["abc", "0", "-1", "65536", "5432.0", "99999999999999999999"])
def test_porta_invalida(porta: str) -> None:
    with pytest.raises(ConfigError, match="VAREJO_DB_PORT"):
        carregar_config_banco(env_com(VAREJO_DB_PORT=porta))


@pytest.mark.parametrize(
    "nome",
    [
        "retail; DROP DATABASE vendas_honda",  # tentativa de injeção
        'retail"',
        "Retail",  # maiúscula exigiria aspas no SQL
        "1retail",
        "retail-x",
        "retail x",
        "a" * 64,  # acima do limite de 63 do PostgreSQL
    ],
)
@pytest.mark.parametrize(
    "variavel", ["VAREJO_DB_NAME", "VAREJO_DB_NAME_TESTE", "VAREJO_DB_USER", "VAREJO_BI_USER"]
)
def test_identificador_invalido_e_recusado(variavel: str, nome: str) -> None:
    with pytest.raises(ConfigError, match=variavel):
        carregar_config_banco(env_com(**{variavel: nome}))


def test_banco_de_teste_igual_ao_principal_e_recusado() -> None:
    with pytest.raises(ConfigError, match="não pode ser igual"):
        carregar_config_banco(env_com(VAREJO_DB_NAME_TESTE="retail"))


@pytest.mark.parametrize("usuario_bi", ["varejo", "varejo_leitura"])
def test_usuario_bi_precisa_ser_proprio(usuario_bi: str) -> None:
    with pytest.raises(ConfigError, match="VAREJO_BI_USER"):
        carregar_config_banco(env_com(VAREJO_BI_USER=usuario_bi))


def test_do_banco_de_teste_e_como_bi() -> None:
    config = carregar_config_banco(ENV_VALIDO)
    assert config.do_banco_de_teste().nome == "retail_teste"
    bi = config.como_bi()
    assert (bi.usuario, bi.senha, bi.nome) == ("varejo_bi", "senha_bi_de_teste", "retail")
