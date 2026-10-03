"""O resultado não pode depender do fuso da sessão de quem roda o pipeline.

`timestamptz + interval '6 months'` é calculado no fuso da sessão. As funções rodam
com `SET timezone = 'Europe/London'` (migration 0010). Aqui o fuso da sessão é trocado
ANTES da recarga, e os números precisam ser os mesmos de Londres.
"""

import pytest

from varejo.banco import Conexao

from .apoio import cenario, compra

pytestmark = pytest.mark.integracao

FUSOS = ["Europe/London", "UTC", "America/Sao_Paulo", "Asia/Tokyo"]


@pytest.mark.parametrize("fuso", FUSOS)
def test_janela_do_churn_nao_depende_do_fuso(bd: Conexao, fuso: str) -> None:
    bd.execute("SELECT set_config('timezone', %s, true)", (fuso,))
    cenario(
        bd,
        [
            compra(10001, "536001", "2011-01-10"),
            compra(10001, "536002", "2011-12-10 00:00:00"),  # 1º instante depois da janela
            compra(10002, "536003", "2011-01-10"),
            compra(10002, "536004", "2011-12-09 23:59:00"),  # último minuto da janela
        ],
    )
    linha = bd.execute(
        "SELECT clientes, nao_voltaram FROM analise.validar_churn("
        "analise.data_param('data_corte'), 6, ARRAY[90])"
    ).fetchone()
    assert linha == (2, 1)


@pytest.mark.parametrize("fuso", FUSOS)
def test_mes_da_coorte_nao_depende_do_fuso(bd: Conexao, fuso: str) -> None:
    bd.execute("SELECT set_config('timezone', %s, true)", (fuso,))
    # 01/08/2011 00:30 em Londres (BST) = 31/07 23:30 UTC: é agosto em Londres.
    cenario(bd, [compra(10001, "536001", "2011-08-01 00:30:00")])
    bd.execute("SELECT analise.recarregar_coortes()")
    coorte = bd.execute("SELECT coorte::text FROM analise.coorte_retencao").fetchone()
    assert coorte == ("2011-08-01",)


@pytest.mark.parametrize("fuso", FUSOS)
def test_recencia_e_clv_nao_dependem_do_fuso(bd: Conexao, fuso: str) -> None:
    bd.execute("SELECT set_config('timezone', %s, true)", (fuso,))
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-06-10 00:30:00"),  # borda da janela de calibração
            compra(10001, "536002", "2010-12-09 23:30:00"),
            compra(10001, "536003", "2011-06-09 23:30:00"),
        ],
    )
    bd.execute("SELECT analise.recarregar_churn(); SELECT analise.recarregar_clv()")
    linha = bd.execute(
        "SELECT recencia_dias, status_churn, clv_previsto_6m FROM analise.cliente"
    ).fetchone()
    # Mesmo resultado calculado em Londres (o teste roda os 4 fusos e compara com ele).
    bd.execute("SET LOCAL timezone = 'Europe/London'")
    bd.execute("SELECT analise.recarregar(); SELECT analise.recarregar_churn()")
    bd.execute("SELECT analise.recarregar_clv()")
    referencia = bd.execute(
        "SELECT recencia_dias, status_churn, clv_previsto_6m FROM analise.cliente"
    ).fetchone()
    assert linha == referencia
    assert linha is not None and linha[0] == 184  # 09/06/2011 -> 10/12/2011


def test_funcoes_do_pipeline_tem_fuso_fixo(bd: Conexao) -> None:
    sem_fuso = bd.execute(
        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname IN ('limpo', 'analise', 'dq') "
        "AND NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) AS c(valor) "
        "WHERE lower(c.valor) = 'timezone=europe/london') "
        "ORDER BY 1"
    ).fetchall()
    assert sem_fuso == []
