"""Testes da carga do bruto: formato da planilha, COPY com valores hostis e carga real."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from varejo.baixar_dados import CAMINHO_PLANILHA, SHA256_PLANILHA, planilha_valida
from varejo.banco import Conexao, conectar
from varejo.carga import COLUNAS, CargaError, carregar, copiar, ler_planilha
from varejo.config import ConfigBanco
from varejo.processar import falhas_dq, processar

from .apoio import valor


def aba_falsa(linhas: int = 2) -> pd.DataFrame:
    return pd.DataFrame({c: [f"{c}{i}" for i in range(linhas)] for c in COLUNAS}, dtype=str)


def test_le_as_duas_abas_com_linha_de_origem(monkeypatch: pytest.MonkeyPatch) -> None:
    abas = {"Year 2009-2010": aba_falsa(2), "Year 2010-2011": aba_falsa(3)}
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: abas)
    tabela = ler_planilha(Path("x.xlsx"))
    assert list(tabela.columns) == ["aba", "linha_origem", *COLUNAS.values()]
    assert tabela["aba"].value_counts().to_dict() == {"Year 2010-2011": 3, "Year 2009-2010": 2}
    # A linha 1 da planilha é o cabeçalho: os dados começam na linha 2.
    assert tabela["linha_origem"].tolist() == [2, 3, 2, 3, 4]


def test_aba_ausente_e_recusada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: {"Year 2009-2010": aba_falsa()})
    with pytest.raises(CargaError, match="Abas ausentes"):
        ler_planilha(Path("x.xlsx"))


def test_coluna_ausente_e_recusada(monkeypatch: pytest.MonkeyPatch) -> None:
    sem_cliente = aba_falsa().drop(columns=["Customer ID"])
    abas = {"Year 2009-2010": aba_falsa(), "Year 2010-2011": sem_cliente}
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: abas)
    with pytest.raises(CargaError, match="Customer ID"):
        ler_planilha(Path("x.xlsx"))


HOSTIS = [
    " espaço no começo",
    "vírgula, no meio",
    'aspas "duplas"',
    "quebra\nde linha",
    "barra \\ invertida",
    "acentuação ç ã £",
    "NULL",
    "\\N",
    "'; DROP TABLE bruto.fatura_linha; --",
]


@pytest.mark.integracao
def test_copy_preserva_valores_hostis_e_nulos(bd: Conexao) -> None:
    tabela = pd.DataFrame(
        {
            "aba": "teste",
            "linha_origem": range(2, 2 + len(HOSTIS) + 1),
            **{coluna: [*HOSTIS, None] for coluna in COLUNAS.values()},
        }
    )
    copiar(bd, tabela)
    linhas = bd.execute(
        "SELECT descricao, cliente_id FROM bruto.fatura_linha WHERE aba = 'teste' "
        "ORDER BY linha_origem"
    ).fetchall()
    assert [d for d, _ in linhas] == [*HOSTIS, None]
    assert linhas[-1] == (None, None)  # célula vazia vira NULL, não o texto ''


@pytest.mark.integracao
@pytest.mark.lento
def test_carga_real_bate_com_a_planilha(banco_teste: ConfigBanco) -> None:
    if not planilha_valida():
        pytest.fail(
            f"Planilha ausente em {CAMINHO_PLANILHA}: rode python -m varejo.baixar_dados",
            pytrace=False,
        )
    resultado = carregar(banco_teste)
    assert resultado.linhas_por_aba == {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}
    carregar(banco_teste)  # rodar de novo substitui, não duplica
    with conectar(banco_teste) as con:
        assert valor(con, "SELECT count(*) FROM bruto.fatura_linha") == 1_067_371
        ultima = con.execute(
            "SELECT arquivo, sha256, linhas FROM bruto.carga ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert ultima == ("online_retail_II.xlsx", SHA256_PLANILHA, 1_067_371)
        # Medições exploratórias de 03/10/2026 (seção 2 do PLAN), agora conferidas.
        assert valor(con, "SELECT count(*) FROM bruto.fatura_linha WHERE cliente_id IS NULL") == (
            243_007
        )
        primeira = con.execute(
            "SELECT fatura, codigo_produto, quantidade, data_fatura, preco_unitario, cliente_id "
            "FROM bruto.fatura_linha WHERE aba = 'Year 2009-2010' AND linha_origem = 2"
        ).fetchone()
        assert primeira == ("489434", "85048", "12", "2009-12-01 07:45:00", "6.95", "13085")


@pytest.mark.integracao
@pytest.mark.lento
def test_pipeline_completo_reproduz_os_numeros_documentados(banco_teste: ConfigBanco) -> None:
    """Planilha real -> bruto -> limpo -> analise -> dq, com os números de docs/DECISOES.md.

    Se uma mudança alterar qualquer número publicado, este teste quebra e obriga a
    atualizar o DECISOES e o README junto.
    """
    if not planilha_valida():
        pytest.fail("Planilha ausente: rode python -m varejo.baixar_dados", pytrace=False)
    carregar(banco_teste)
    processar(banco_teste, saida=False)
    with conectar(banco_teste) as con:
        assert falhas_dq(con) == []
        tipos: dict[str, int] = dict(
            con.execute("SELECT tipo, count(*) FROM limpo.fatura_linha GROUP BY tipo").fetchall()
        )
        assert tipos == {
            "venda": 1_019_653,
            "cancelamento": 19_164,
            "sem_valor": 6_024,
            "ajuste_divida": 6,
            "anomalia": 1,
        }
        # D5: repetições dentro da aba mantidas no limpo (a sobreposição saiu).
        repeticoes = valor(
            con,
            "SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT b.fatura, "
            "b.codigo_produto, b.descricao, b.quantidade, b.data_fatura, b.preco_unitario, "
            "b.cliente_id, b.pais FROM bruto.fatura_linha b JOIN limpo.fatura_linha l "
            "USING (aba, linha_origem)) d) FROM limpo.fatura_linha",
        )
        assert repeticoes == 11_812
        clientes, liquida, atacado, churn = con.execute(
            "SELECT count(*), sum(receita_liquida), count(*) FILTER (WHERE eh_atacado), "
            "count(*) FILTER (WHERE em_churn) FROM analise.cliente"
        ).fetchone()  # type: ignore[misc]
        assert (clientes, liquida, atacado, churn) == (5_852, Decimal("16413300.877"), 607, 2_967)
        assert (
            valor(con, "SELECT count(*) FROM analise.cliente WHERE segmento = 'Campeões'") == 1_380
        )
        escolhido = con.execute(
            "SELECT dias, precisao, recall, f1 FROM analise.churn_validacao "
            "WHERE corte = '2011-06-10' AND escolhido"
        ).fetchone()
        assert escolhido == (90, Decimal("0.6409"), Decimal("0.8027"), Decimal("0.7127"))
        clv = con.execute(
            "SELECT erro_total_pct, captura_top20 FROM analise.clv_validacao "
            "WHERE modelo = 'previsto'"
        ).fetchone()
        assert clv == (Decimal("0.48"), Decimal("0.8830"))
        assert round(valor(con, "SELECT sum(clv_previsto_6m) FROM analise.cliente")) == (  # type: ignore[call-overload]
            3_809_240
        )
