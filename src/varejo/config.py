"""Configuração de acesso ao banco, lida de variáveis de ambiente (arquivo .env).

Tudo que é segredo (senha) vem do ambiente e nunca do código. A validação acontece
aqui, na borda: um valor ausente ou inválido gera um erro claro na hora de carregar,
e não um erro confuso lá dentro do driver do PostgreSQL.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
PASTA_DADOS = RAIZ_PROJETO / "data" / "raw"

# Grupo (role sem login) que recebe SELECT nos schemas lidos pelo Power BI.
GRUPO_LEITURA = "varejo_leitura"

# Nome de banco e de usuário: só minúsculas, dígitos e "_", começando por letra ou "_".
# Limite de 63 caracteres do PostgreSQL. Evita nomes que exigiriam aspas no SQL.
_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]{0,62}")


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class ConfigBanco:
    host: str
    porta: int
    nome: str
    usuario: str
    # Banco usado pelos testes automatizados; é apagado e recriado a cada execução.
    nome_teste: str
    # Usuário somente leitura do Power BI (membro do grupo varejo_leitura).
    usuario_bi: str
    # repr=False: as senhas não aparecem se o objeto for impresso num log ou traceback.
    senha: str = field(repr=False)
    senha_bi: str = field(repr=False)

    def do_banco_de_teste(self) -> ConfigBanco:
        """Mesma configuração, apontando para o banco de testes."""
        return replace(self, nome=self.nome_teste)

    def como_bi(self) -> ConfigBanco:
        """Mesma configuração, conectando como o usuário somente leitura do Power BI."""
        return replace(self, usuario=self.usuario_bi, senha=self.senha_bi)

    def url(self) -> URL:
        """URL do SQLAlchemy. URL.create trata caracteres especiais da senha sem escape manual."""
        return URL.create(
            "postgresql+psycopg",
            username=self.usuario,
            password=self.senha,
            host=self.host,
            port=self.porta,
            database=self.nome,
        )


def _obrigatoria(env: Mapping[str, str], nome: str) -> str:
    valor = env.get(nome)
    if valor is None or not valor.strip():
        raise ConfigError(f"Variável {nome} não definida. Copie .env.example para .env e preencha.")
    return valor


def validar_identificador(valor: str, nome_variavel: str) -> str:
    if not _IDENTIFICADOR.fullmatch(valor):
        raise ConfigError(
            f"{nome_variavel}={valor!r} inválido: use só letras minúsculas, dígitos e '_', "
            "começando por letra ou '_' (máx. 63 caracteres)."
        )
    return valor


def _porta(texto: str) -> int:
    try:
        porta = int(texto)
    except ValueError:
        raise ConfigError(f"VAREJO_DB_PORT={texto!r} não é um número.") from None
    if not 1 <= porta <= 65535:
        raise ConfigError(f"VAREJO_DB_PORT={porta} fora do intervalo 1-65535.")
    return porta


def carregar_config_banco(env: Mapping[str, str] | None = None) -> ConfigBanco:
    """Lê a configuração do banco.

    Sem argumento, usa o ambiente do processo mais o .env da raiz do projeto (variáveis
    já definidas no ambiente têm prioridade sobre o .env). Os testes passam um dicionário.
    """
    if env is None:
        load_dotenv(RAIZ_PROJETO / ".env", override=False)
        env = os.environ

    nome = validar_identificador(_obrigatoria(env, "VAREJO_DB_NAME"), "VAREJO_DB_NAME")
    nome_teste = validar_identificador(
        _obrigatoria(env, "VAREJO_DB_NAME_TESTE"), "VAREJO_DB_NAME_TESTE"
    )
    # Trava de segurança: os testes APAGAM e recriam o banco de testes. Se ele tivesse
    # o mesmo nome do banco principal, rodar os testes destruiria os dados do projeto.
    if nome_teste == nome:
        raise ConfigError(
            "VAREJO_DB_NAME_TESTE não pode ser igual a VAREJO_DB_NAME: os testes apagam o "
            "banco de testes a cada execução."
        )

    usuario = validar_identificador(_obrigatoria(env, "VAREJO_DB_USER"), "VAREJO_DB_USER")
    usuario_bi = validar_identificador(_obrigatoria(env, "VAREJO_BI_USER"), "VAREJO_BI_USER")
    if usuario_bi in (usuario, GRUPO_LEITURA):
        raise ConfigError(
            "VAREJO_BI_USER precisa ser um usuário próprio, diferente do dono do banco e do "
            f"grupo {GRUPO_LEITURA}."
        )

    return ConfigBanco(
        host=_obrigatoria(env, "VAREJO_DB_HOST"),
        porta=_porta(_obrigatoria(env, "VAREJO_DB_PORT")),
        nome=nome,
        usuario=usuario,
        senha=_obrigatoria(env, "VAREJO_DB_PASSWORD"),
        nome_teste=nome_teste,
        usuario_bi=usuario_bi,
        senha_bi=_obrigatoria(env, "VAREJO_BI_PASSWORD"),
    )
