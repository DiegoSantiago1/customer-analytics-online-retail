"""CLV previsto e a validação dele, com cenários montados à mão.

Corte = 10/06/2011; a calibração da retenção usa a mesma época do ano anterior
(10/06/2010 a 10/12/2010).
"""

from decimal import Decimal

import pytest

from varejo.banco import Conexao

from .apoio import cenario, compra, espera_erro, valor

pytestmark = pytest.mark.integracao

CLV_NO_CORTE = (
    "SELECT cliente_id, segmento, p_ativo, ticket_medio, compras_por_mes, clv_previsto "
    "FROM analise.clv_previsto(analise.data_param('data_corte'), 6) ORDER BY cliente_id"
)


def test_retencao_do_segmento_na_janela(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-03-01"),
            compra(10001, "536002", "2010-09-01"),  # voltou na janela
            compra(10002, "536003", "2010-03-01"),  # não voltou
            compra(10002, "536004", "2010-12-20"),  # voltou, mas depois da janela
            compra(10003, "536005", "2010-07-01"),  # não existia no início da janela
        ],
    )
    linhas = bd.execute(
        "SELECT sum(clientes), sum(voltaram) FROM analise.retencao_segmento("
        "'2010-06-10 00:00 Europe/London', 6)"
    ).fetchone()
    assert linhas == (2, 1)


def test_cliente_unico_fica_com_a_propria_taxa(bd: Conexao) -> None:
    # Com um cliente só, a taxa da base é a dele: a suavização não muda nada.
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-03-01", quantidade=10),
            compra(10001, "536002", "2010-09-01", quantidade=10),
            compra(10001, "536003", "2011-03-01", quantidade=10),
        ],
    )
    _, _, p_ativo, ticket, compras_mes, clv = bd.execute(CLV_NO_CORTE).fetchone()  # type: ignore[misc]
    m = bd.execute(
        "SELECT frequencia, meses_de_vida FROM "
        "analise.metricas_cliente(analise.data_param('data_corte'))"
    ).fetchone()
    assert m is not None
    assert compras_mes == round(Decimal(m[0]) / m[1], 4)
    assert p_ativo == Decimal("1.0000")  # voltou na janela de calibração
    assert ticket == Decimal("100.00")
    # compras_mes sai arredondado em 4 casas (erro até 0,00005 x 100 x 6 = 0,03);
    # o CLV usa o valor cheio.
    assert abs(clv - p_ativo * ticket * compras_mes * 6) <= Decimal("0.03")


def test_pouca_historia_puxa_para_a_media(bd: Conexao) -> None:
    # 10002 comprou uma vez há poucos dias: sem suavização teria "1 compra por mês".
    linhas = [compra(10001, f"5360{k:02d}", f"2010-{k + 1:02d}-15") for k in range(12)]
    linhas.append(compra(10002, "536100", "2011-06-01"))
    cenario(bd, linhas)
    taxas = {c: t for c, _, _, _, t, _ in bd.execute(CLV_NO_CORTE)}
    assert taxas[10002] < Decimal("1")
    assert taxas[10002] > taxas[10001] * Decimal("0.5")


def test_clv_nunca_e_negativo(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-03-01", quantidade=1),
            compra(10001, "C536002", "2010-03-02", quantidade=-5),
            compra(10002, "536003", "2010-03-01"),
        ],
    )
    clvs = {c: v for c, _, _, _, _, v in bd.execute(CLV_NO_CORTE)}
    assert clvs[10001] == 0


def test_segmento_sem_calibracao_usa_a_retencao_geral(bd: Conexao) -> None:
    # Nenhum cliente existia em 10/06/2010: a calibração fica vazia e p_ativo = 0.
    cenario(bd, [compra(10001, "536001", "2011-01-10")])
    p_ativo = valor(
        bd, "SELECT p_ativo FROM analise.clv_previsto(analise.data_param('data_corte'), 6)"
    )
    assert p_ativo == 0


def test_validacao_compara_previsto_ingenuo_e_real(bd: Conexao) -> None:
    cenario(
        bd,
        [
            compra(10001, "536001", "2010-03-01", quantidade=10),
            compra(10001, "536002", "2010-09-01", quantidade=10),
            compra(10001, "536003", "2011-03-01", quantidade=4),  # nos 6 meses antes do corte
            compra(10001, "536004", "2011-08-01", quantidade=7),  # nos 6 meses depois
            compra(10002, "536005", "2010-04-01", quantidade=2),
        ],
    )
    bd.execute("SELECT analise.recarregar_clv()")
    linhas = dict(
        (c, (i, r))
        for c, i, r in bd.execute(
            "SELECT cliente_id, ingenuo, real FROM analise.clv_validacao_cliente"
        )
    )
    assert linhas == {
        10001: (Decimal("40.00"), Decimal("70.00")),
        10002: (Decimal("0.00"), Decimal("0.00")),
    }
    resumo = dict(
        (m, (t, e))
        for m, t, e in bd.execute(
            "SELECT modelo, total_real, erro_total_pct FROM analise.clv_validacao"
        )
    )
    assert resumo["ingenuo"] == (Decimal("70.00"), Decimal("-42.86"))
    assert set(resumo) == {"previsto", "ingenuo"}


def test_clv_no_fim_e_preenchido_para_todos(bd: Conexao) -> None:
    cenario(bd, [compra(10001 + i, f"5360{i:02d}", f"2011-0{1 + i}-10") for i in range(5)])
    bd.execute("SELECT analise.recarregar_clv()")
    assert valor(bd, "SELECT count(*) FROM analise.cliente WHERE clv_previsto_6m IS NULL") == 0


def test_check_previsto_nao_negativo(bd: Conexao) -> None:
    cenario(bd, [compra(10001, "536001", "2010-03-01"), compra(10001, "536002", "2011-03-01")])
    bd.execute("SELECT analise.recarregar_clv()")
    with espera_erro(bd, "23514"):
        bd.execute("UPDATE analise.clv_validacao_cliente SET previsto = -1")


def test_sem_receita_real_o_erro_percentual_fica_nulo(bd: Conexao) -> None:
    # Hostil: ninguém comprou depois do corte. A recarga não pode quebrar.
    cenario(bd, [compra(10001, "536001", "2010-03-01"), compra(10001, "536002", "2011-03-01")])
    bd.execute("SELECT analise.recarregar_clv()")
    linha = bd.execute(
        "SELECT total_real, erro_total_pct, captura_top20 FROM analise.clv_validacao "
        "WHERE modelo = 'previsto'"
    ).fetchone()
    assert linha == (Decimal("0.00"), None, None)
