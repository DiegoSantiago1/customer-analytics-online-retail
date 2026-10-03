"""Checagens de qualidade (dq.verificar): passam num cenário limpo e pegam cada problema."""

from collections.abc import Sequence

import pytest

from varejo.banco import Conexao

from .apoio import ANTIGA, NOVA, carregar_bruto, compra, linha

pytestmark = pytest.mark.integracao


def rodar(bd: Conexao, linhas: Sequence[tuple[object, ...]]) -> dict[str, bool]:
    """Pipeline inteiro dentro da transação do teste; devolve {checagem: ok}."""
    carregar_bruto(bd, linhas)
    bd.execute(
        "INSERT INTO bruto.carga (arquivo, sha256, linhas) "
        "SELECT 'teste.xlsx', repeat('0', 64), count(*) FROM bruto.fatura_linha"
    )
    for funcao in ("recarregar", "recarregar_churn", "recarregar_coortes", "recarregar_clv"):
        bd.execute(f"SELECT analise.{funcao}()")
    bd.execute("SELECT dq.verificar()")
    return dict(bd.execute("SELECT verificacao, ok FROM dq.resultado").fetchall())


def base() -> list[tuple[object, ...]]:
    """Cenário limpo: duas abas com sobreposição idêntica e 10 clientes."""
    linhas: list[tuple[object, ...]] = [
        linha(ANTIGA, fatura="489434", data="2010-06-01 10:00:00", cliente="12346"),
        linha(ANTIGA, fatura="536365", data="2010-12-01 08:26:00"),
        linha(NOVA, fatura="536365", data="2010-12-01 08:26:00"),
    ]
    for i in range(10):
        linhas += [
            compra(12000 + i, f"55{i:02d}01", f"2011-0{1 + i % 5}-10"),
            compra(12000 + i, f"55{i:02d}02", f"2011-0{6 + i % 4}-12"),
        ]
    return linhas


def falhas(resultado: dict[str, bool]) -> set[str]:
    return {nome for nome, ok in resultado.items() if not ok}


def test_cenario_limpo_passa_em_tudo(bd: Conexao) -> None:
    resultado = rodar(bd, base())
    assert len(resultado) == 16
    # O cenário pequeno não tem 2 cortes de churn válidos nem quintos equilibrados.
    assert falhas(resultado) <= {"analise_churn_validado_nos_dois_cortes", "analise_quintis_r_e_m"}


def test_sobreposicao_diferente_e_pega(bd: Conexao) -> None:
    linhas = [*base(), linha(ANTIGA, fatura="536366", data="2010-12-02 09:00:00")]
    assert "sobreposicao_identica" in falhas(rodar(bd, linhas))


def test_codigo_novo_fora_do_padrao_e_pego(bd: Conexao) -> None:
    linhas = [*base(), compra(12001, "556001", "2011-03-01", codigo="NOVOCODIGO")]
    assert "limpo_codigo_nao_classificado" in falhas(rodar(bd, linhas))


def test_anomalia_nova_e_pega(bd: Conexao) -> None:
    linhas = [*base(), compra(12001, "C556001", "2011-03-01", quantidade=1)]
    assert "limpo_anomalias_novas" in falhas(rodar(bd, linhas))


def test_hora_ambigua_e_pega(bd: Conexao) -> None:
    linhas = [*base(), compra(12001, "556001", "2011-10-30 01:30:00")]
    assert "limpo_hora_ambigua" in falhas(rodar(bd, linhas))


def test_fatura_com_dois_clientes_e_pega(bd: Conexao) -> None:
    linhas = [*base(), compra(12001, "556001", "2011-03-01"), compra(12002, "556001", "2011-03-01")]
    assert "limpo_fatura_um_cliente" in falhas(rodar(bd, linhas))


def test_carga_incompleta_e_pega(bd: Conexao) -> None:
    rodar(bd, base())
    bd.execute(
        "INSERT INTO bruto.carga (arquivo, sha256, linhas) VALUES ('x', repeat('1', 64), 999)"
    )
    bd.execute("SELECT dq.verificar()")
    ok = bd.execute(
        "SELECT ok FROM dq.resultado WHERE verificacao = 'bruto_linhas_da_ultima_carga'"
    ).fetchone()
    assert ok == (False,)


def test_resultado_e_lido_pelo_bi(bd: Conexao, bd_bi: Conexao) -> None:
    # dq.resultado precisa estar visível para o usuário do Power BI.
    bd_bi.execute("SELECT count(*) FROM dq.resultado").fetchone()
