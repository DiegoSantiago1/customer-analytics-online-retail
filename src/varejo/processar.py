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

from varejo.banco import conectar
from varejo.config import ConfigBanco, ConfigError, carregar_config_banco

# (descrição, comando). A ordem importa: cada etapa lê o resultado da anterior.
ETAPAS: list[tuple[str, str]] = [
    ("limpo: classificar e tipar as linhas", "SELECT limpo.recarregar()"),
    ("analise: pedidos, métricas e RFM", "SELECT analise.recarregar()"),
    ("analise: validação e marcação de churn", "SELECT analise.recarregar_churn()"),
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


def main() -> int:
    try:
        config = carregar_config_banco()
        processar(config)
    except (ConfigError, psycopg.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    print("Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
