"""Carrega a planilha Online Retail II no schema bruto.

Uso (depois do bootstrap, das migrations e do download):
    python -m varejo.carga

O Python só lê e copia: nenhuma regra de limpeza acontece aqui. Cada célula vira
texto, exatamente como o leitor do Excel a devolve, e a limpeza fica em SQL (schema
limpo), onde é versionada e testada.

A planilha é lida com o motor calamine (Rust): medido em 03/10/2026, 13,7 s contra
77,4 s do openpyxl, com texto idêntico nas 8,5 milhões de células das duas abas.
"""

from __future__ import annotations

import io
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

from varejo.baixar_dados import CAMINHO_PLANILHA, planilha_valida, sha256_arquivo
from varejo.banco import Conexao, conectar
from varejo.config import ConfigBanco, ConfigError, carregar_config_banco

# Colunas da planilha → colunas do banco, na ordem do COPY.
COLUNAS = {
    "Invoice": "fatura",
    "StockCode": "codigo_produto",
    "Description": "descricao",
    "Quantity": "quantidade",
    "InvoiceDate": "data_fatura",
    "Price": "preco_unitario",
    "Customer ID": "cliente_id",
    "Country": "pais",
}
ABAS = ("Year 2009-2010", "Year 2010-2011")


class CargaError(RuntimeError):
    """A planilha não tem o formato esperado."""


@dataclass(frozen=True)
class ResultadoCarga:
    linhas_por_aba: dict[str, int]
    segundos_leitura: float
    segundos_copia: float

    @property
    def total(self) -> int:
        return sum(self.linhas_por_aba.values())


def ler_planilha(caminho: Path) -> pd.DataFrame:
    """Lê as duas abas como texto e devolve uma tabela só, com aba e linha de origem.

    Recusa a planilha se faltar uma aba ou uma coluna: carregar metade do dataset sem
    perceber geraria números errados lá na frente.
    """
    abas = pd.read_excel(caminho, sheet_name=None, engine="calamine", dtype=str)
    faltando = [aba for aba in ABAS if aba not in abas]
    if faltando:
        raise CargaError(f"Abas ausentes na planilha: {faltando}")
    partes = []
    for aba in ABAS:
        tabela = abas[aba]
        colunas_faltando = [c for c in COLUNAS if c not in tabela.columns]
        if colunas_faltando:
            raise CargaError(f"Aba {aba!r} sem as colunas {colunas_faltando}")
        tabela = tabela[list(COLUNAS)].rename(columns=COLUNAS)
        # Linha 1 da planilha é o cabeçalho: o índice 0 do DataFrame é a linha 2.
        tabela.insert(0, "linha_origem", tabela.index + 2)
        tabela.insert(0, "aba", aba)
        partes.append(tabela)
    return pd.concat(partes, ignore_index=True)


def copiar(con: Conexao, tabela: pd.DataFrame) -> None:
    """COPY da tabela para bruto.fatura_linha (bem mais rápido que INSERT linha a linha).

    O CSV vai em memória. Célula vazia (NaN) vira NULL pela opção NULL '' do COPY; o
    leitor do Excel não devolve texto vazio (célula vazia já é NaN), então não há
    texto vazio a perder. A ida e volta é conferida célula a célula no teste da carga.
    """
    buffer = io.StringIO()
    tabela.to_csv(buffer, index=False, header=False, na_rep="")
    colunas = sql.SQL(", ").join(
        sql.Identifier(c) for c in ["aba", "linha_origem", *COLUNAS.values()]
    )
    comando = sql.SQL("COPY bruto.fatura_linha ({}) FROM STDIN WITH (FORMAT csv, NULL '')")
    with con.cursor().copy(comando.format(colunas)) as copy:
        copy.write(buffer.getvalue())


def carregar(config: ConfigBanco, caminho: Path = CAMINHO_PLANILHA) -> ResultadoCarga:
    """Substitui o conteúdo do bruto pela planilha, numa transação só.

    TRUNCATE + COPY + registro da carga: ou tudo entra, ou nada muda. Rodar de novo
    não duplica linhas.
    """
    inicio = time.perf_counter()
    tabela = ler_planilha(caminho)
    lida = time.perf_counter()
    sha256 = sha256_arquivo(caminho)
    with conectar(config) as con:
        con.execute("TRUNCATE bruto.fatura_linha")
        copiar(con, tabela)
        con.execute(
            "INSERT INTO bruto.carga (arquivo, sha256, linhas) VALUES (%s, %s, %s)",
            (caminho.name, sha256, len(tabela)),
        )
    return ResultadoCarga(
        linhas_por_aba={aba: int((tabela["aba"] == aba).sum()) for aba in ABAS},
        segundos_leitura=lida - inicio,
        segundos_copia=time.perf_counter() - lida,
    )


def main() -> int:
    if not planilha_valida():
        print(
            f"Planilha ausente ou com hash diferente em {CAMINHO_PLANILHA}. "
            "Rode antes: python -m varejo.baixar_dados",
            file=sys.stderr,
        )
        return 1
    try:
        resultado = carregar(carregar_config_banco())
    except (ConfigError, CargaError, psycopg.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    for aba, linhas in resultado.linhas_por_aba.items():
        print(f"{aba}: {linhas:,} linhas".replace(",", "."))
    print(
        f"Total: {resultado.total:,} linhas em bruto.fatura_linha ".replace(",", ".")
        + f"(leitura {resultado.segundos_leitura:.1f} s, cópia {resultado.segundos_copia:.1f} s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
