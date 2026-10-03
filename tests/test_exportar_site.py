"""Exportação dos agregados do site: estrutura, números e nenhum dado individual."""

import json
from pathlib import Path

import pytest

from varejo.banco import Conexao
from varejo.config import RAIZ_PROJETO
from varejo.exportar_site import _limpar, montar

from .apoio import cenario, compra

pytestmark = pytest.mark.integracao


def processar_tudo(bd: Conexao) -> None:
    for funcao in ("recarregar_churn", "recarregar_coortes", "recarregar_clv"):
        bd.execute(f"SELECT analise.{funcao}()")
    bd.execute("SELECT dq.verificar()")


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
        "receita_mes",
        "segmentos",
        "churn",
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
    assert round(resumo["clv_6m"]) == 3_809_240
    assert resumo["dq_ok"] == resumo["dq_total"] == 16
