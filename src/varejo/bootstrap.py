"""Cria o usuário e os bancos do projeto no container PostgreSQL (executa db/bootstrap.sql).

Uso (com o Docker Desktop aberto e o container compartilhado rodando):
    python -m varejo.bootstrap

Por que docker exec: dentro do container o psql conecta ao superusuário pelo socket
local, sem senha. Assim este projeto não precisa guardar a senha de superusuário. A
senha do usuário novo vai pela entrada padrão (stdin) do psql, e não pela linha de
comando, para não aparecer na lista de processos.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping

from dotenv import load_dotenv

from varejo.config import (
    RAIZ_PROJETO,
    ConfigBanco,
    ConfigError,
    carregar_config_banco,
    validar_identificador,
)

ARQUIVO_SQL = RAIZ_PROJETO / "db" / "bootstrap.sql"

# Nomes de container aceitos pelo Docker.
_NOME_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def citar_valor_psql(valor: str) -> str:
    r"""Cita um valor para o meta-comando \set do psql.

    Entre aspas simples o psql processa escapes com barra invertida (\n, \t...) e
    representa uma aspa simples como ''. Dobrando a barra e a aspa, o valor chega
    literal. Quebra de linha é recusada porque encerra o meta-comando.
    """
    if any(c in valor for c in "\r\n\0"):
        raise ConfigError("O valor não pode conter quebra de linha nem caractere nulo.")
    return "'" + valor.replace("\\", "\\\\").replace("'", "''") + "'"


def montar_entrada_psql(config: ConfigBanco, sql: str) -> str:
    """Texto enviado ao psql: define as variáveis e em seguida o bootstrap.sql."""
    variaveis = {
        "usuario": config.usuario,
        "senha": config.senha,
        "banco": config.nome,
        "banco_teste": config.nome_teste,
        "bi_usuario": config.usuario_bi,
        "bi_senha": config.senha_bi,
    }
    definicoes = "".join(f"\\set {nome} {citar_valor_psql(v)}\n" for nome, v in variaveis.items())
    return definicoes + sql


def comando_psql(docker: str, container: str, superusuario: str) -> list[str]:
    """Linha de comando do psql no container. Não contém a senha."""
    return [
        docker,
        "exec",
        "-i",
        container,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        superusuario,
        "-d",
        "postgres",
    ]


def config_docker(env: Mapping[str, str]) -> tuple[str, str]:
    container = env.get("VAREJO_DOCKER_CONTAINER", "").strip()
    if not _NOME_CONTAINER.fullmatch(container):
        raise ConfigError(f"VAREJO_DOCKER_CONTAINER={container!r} inválido ou não definido.")
    superusuario = validar_identificador(
        env.get("VAREJO_DOCKER_SUPERUSER", "").strip(), "VAREJO_DOCKER_SUPERUSER"
    )
    return container, superusuario


def conferir_usuarios(config: ConfigBanco, superusuario: str) -> None:
    """O bootstrap rebaixa os usuários do projeto (NOSUPERUSER...): nunca o superusuário."""
    for variavel, usuario in (
        ("VAREJO_DB_USER", config.usuario),
        ("VAREJO_BI_USER", config.usuario_bi),
    ):
        if usuario == superusuario:
            raise ConfigError(
                f"{variavel}={usuario!r} é o superusuário do container: o bootstrap tiraria "
                "os privilégios dele. Use um usuário próprio do projeto."
            )


def _docker() -> str:
    caminho = shutil.which("docker")
    if caminho is None:
        raise ConfigError("Comando 'docker' não encontrado. O Docker Desktop está instalado?")
    return caminho


def _container_rodando(docker: str, container: str) -> bool:
    resultado = subprocess.run(  # noqa: S603 (argumentos validados, sem shell)
        [docker, "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    return resultado.returncode == 0 and resultado.stdout.strip() == "true"


def main() -> int:
    load_dotenv(RAIZ_PROJETO / ".env", override=False)
    try:
        banco = carregar_config_banco()
        container, superusuario = config_docker(os.environ)
        conferir_usuarios(banco, superusuario)
        docker = _docker()
        entrada = montar_entrada_psql(banco, ARQUIVO_SQL.read_text(encoding="utf-8"))
    except ConfigError as erro:
        print(f"Erro de configuração: {erro}", file=sys.stderr)
        return 2

    if not _container_rodando(docker, container):
        print(
            f"Container {container!r} não está rodando. Abra o Docker Desktop e suba o "
            "container compartilhado.",
            file=sys.stderr,
        )
        return 1

    # flush: sem ele a mensagem fica no buffer e aparece depois da saída do psql.
    print(
        f"Criando/atualizando o usuário {banco.usuario!r} e os bancos "
        f"{banco.nome!r} e {banco.nome_teste!r}...",
        flush=True,
    )
    resultado = subprocess.run(  # noqa: S603 (argumentos validados, sem shell)
        comando_psql(docker, container, superusuario),
        input=entrada.encode("utf-8"),
        check=False,
    )
    if resultado.returncode != 0:
        print("Falhou: veja a mensagem do psql acima.", file=sys.stderr)
        return resultado.returncode
    print("Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
