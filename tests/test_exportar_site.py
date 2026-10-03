"""Exportação dos agregados do site: estrutura, números e nenhum dado individual."""

import json
from pathlib import Path

import pytest

from varejo.banco import Conexao
from varejo.config import RAIZ_PROJETO
from varejo.exportar_site import ExportarError, _limpar, montar

from .apoio import cenario, compra

pytestmark = pytest.mark.integracao


def processar_tudo(bd: Conexao, aprovar_dq: bool = True) -> None:
    for funcao in ("recarregar_churn", "recarregar_coortes", "recarregar_clv"):
        bd.execute(f"SELECT analise.{funcao}()")
    bd.execute("SELECT dq.verificar()")
    if aprovar_dq:
        # O cenário pequeno não tem quintos equilibrados nem os dois cortes de churn:
        # aqui o teste é da exportação, então o dq é dado como aprovado.
        bd.execute("UPDATE dq.resultado SET ok = true")


def test_recusa_exportar_com_dq_reprovado(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10")])
    processar_tudo(bd, aprovar_dq=False)
    bd.execute("UPDATE dq.resultado SET ok = false WHERE verificacao = 'limpo_linhas'")
    with pytest.raises(ExportarError, match="falha"):
        montar(bd)


def test_recusa_exportar_sem_dq_rodado(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2011-01-10")])
    bd.execute("TRUNCATE dq.resultado")
    with pytest.raises(ExportarError):
        montar(bd)


def test_montar_tem_as_secoes_e_os_numeros_do_banco(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-10", quantidade=10),
            compra(10001, "536002", "2011-03-10", quantidade=5),
            compra(10002, "536003", "2011-02-10", quantidade=1),
            compra(None, "536004", "2011-02-11", quantidade=3),
        ],
    )
    processar_tudo(bd)
    dados = montar(bd)
    assert set(dados) == {
        "resumo",
        "limpeza",
        "receita_mes",
        "segmentos",
        "churn",
        "churn_faixa",
        "coortes",
        "clv_validacao",
        "clv_segmento",
    }
    resumo = dados["resumo"]
    assert resumo["clientes"] == 2
    assert resumo["receita_liquida"] == 160.0
    assert resumo["pct_recompra"] == 0.5
    assert resumo["receita_produto"] == 190.0  # inclui a venda sem cliente
    assert len(dados["segmentos"]) == 10
    json.dumps(dados)  # tudo serializável (Decimal e datas convertidos)


def test_nenhum_dado_individual_de_cliente(bd: Conexao) -> None:
    cenario(bd, [compra(12345, "536001", "2011-01-10")])
    processar_tudo(bd)
    texto = json.dumps(montar(bd))
    assert "cliente_id" not in texto
    assert "12345" not in texto


def test_limpar_converte_tipos() -> None:
    from datetime import date
    from decimal import Decimal

    assert _limpar({"a": [Decimal("0.123456"), date(2011, 6, 10)]}) == {"a": [0.1235, "2011-06-10"]}


def test_json_versionado_bate_com_o_documentado() -> None:
    # site/dados.json é o que o GitHub Pages mostra: precisa trazer os números do DECISOES.
    dados = json.loads(Path(RAIZ_PROJETO / "site" / "dados.json").read_text(encoding="utf-8"))
    resumo = dados["resumo"]
    assert resumo["clientes"] == 5852
    assert round(resumo["receita_liquida"]) == 16_413_301
    assert resumo["em_churn"] == 2967
    assert round(resumo["clv_6m"]) == 3_822_972
    assert (resumo["em_risco"], resumo["inativos"]) == (1376, 1591)
    assert dados["limpeza"]["sobreposicao"] == 22_523
    assert dados["limpeza"]["repeticoes_mantidas"] == 11_812
    assert sum(s["em_risco"] for s in dados["segmentos"]) == 1376
    assert resumo["dq_ok"] == resumo["dq_total"] == 18
