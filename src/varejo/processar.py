"""Roda as etapas em SQL do pipeline, na ordem, depois da carga do bruto.

Uso:
    python -m varejo.processar

Cada etapa é uma função do banco que reconstrói o próprio schema a partir do anterior
(bruto → limpo → analise → dq). O Python só chama, mede o tempo e mostra o resultado:
as regras ficam em SQL versionado nas migrations.
"""

from __future__ import annotations

import sys
import time

import psycopg

from varejo.banco import Conexao, conectar
from varejo.config import ConfigBanco, ConfigError, carregar_config_banco

# (descrição, comando). A ordem importa: cada etapa lê o resultado da anterior.
ETAPAS: list[tuple[str, str]] = [
    ("limpo: classificar e tipar as linhas", "SELECT limpo.recarregar()"),
    ("analise: pedidos, métricas e RFM", "SELECT analise.recarregar()"),
    ("analise: validação e marcação de churn", "SELECT analise.recarregar_churn()"),
    ("analise: coortes de retenção", "SELECT analise.recarregar_coortes()"),
    ("analise: CLV (validação e previsão)", "SELECT analise.recarregar_clv()"),
    ("dq: checagens de qualidade", "SELECT dq.verificar()"),
]


def processar(config: ConfigBanco, saida: bool = True) -> dict[str, float]:
    """Executa todas as etapas numa transação só: ou o pipeline inteiro vale, ou nada muda."""
    tempos: dict[str, float] = {}
    with conectar(config) as con:
        for descricao, comando in ETAPAS:
            inicio = time.perf_counter()
            con.execute(comando)
            tempos[descricao] = time.perf_counter() - inicio
            if saida:
                print(f"{descricao}: {tempos[descricao]:.1f} s", flush=True)
    return tempos


def falhas_dq(con: Conexao) -> list[tuple[str, str, str]]:
    """Checagens de qualidade que falharam na última verificação: (nome, esperado, obtido)."""
    return [
        (nome, esperado, obtido)
        for nome, esperado, obtido in con.execute(
            "SELECT verificacao, esperado, obtido FROM dq.resultado WHERE NOT ok "
            "ORDER BY verificacao"
        )
    ]


def main() -> int:
    try:
        config = carregar_config_banco()
        processar(config)
        with conectar(config) as con:
            falhas = falhas_dq(con)
            total = con.execute("SELECT count(*) FROM dq.resultado").fetchone()
    except (ConfigError, psycopg.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    if falhas:
        print(f"{len(falhas)} checagem(ns) de qualidade falharam:", file=sys.stderr)
        for nome, esperado, obtido in falhas:
            print(f"  {nome}: esperado {esperado}, obtido {obtido}", file=sys.stderr)
        return 1
    print(f"Pronto. {total[0] if total else 0} checagens de qualidade, todas ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
