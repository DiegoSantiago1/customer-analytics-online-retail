"""Testes de fumaça dos gráficos: montam sem erro com dados pequenos (sem banco)."""

import matplotlib

matplotlib.use("Agg")  # sem janela nos testes

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from matplotlib.figure import Figure

from varejo import graficos


@pytest.fixture(autouse=True)
def fechar_figuras() -> None:
    plt.close("all")


def test_mes_em_portugues_sem_depender_do_locale() -> None:
    assert graficos._mes("2010-12-01") == "dez/10"
    assert graficos._mes(pd.Timestamp("2011-02-01")) == "fev/11"


@pytest.mark.parametrize(
    ("valor", "texto"),
    [(1_400_000, "£1,4 mi"), (650_000, "£650 mil"), (12, "£12"), (-20_000, "£-20 mil")],
)
def test_libras(valor: float, texto: str) -> None:
    assert graficos._libras(valor) == texto


def test_receita_mensal() -> None:
    dados = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2011-10-01", "2011-11-01", "2011-12-01"]),
            "venda_produto_com_cliente": [100.0, 200.0, 50.0],
            "venda_produto_sem_cliente": [10.0, 20.0, 5.0],
            "mes_parcial": [False, False, True],
        }
    )
    assert isinstance(graficos.receita_mensal(dados), Figure)


def test_segmentos() -> None:
    dados = pd.DataFrame(
        {
            "ordem": [1, 2],
            "segmento": ["Campeões", "Perdidos"],
            "pct_clientes": [0.3, 0.7],
            "pct_receita": [0.9, 0.1],
        }
    )
    assert isinstance(graficos.segmentos(dados), Figure)


def test_validacao_churn() -> None:
    dados = pd.DataFrame(
        {
            "corte": ["2011-06-10"] * 2 + ["2010-12-10"] * 2,
            "dias": [90, 180] * 2,
            "precisao": [0.6, 0.7, 0.7, 0.8],
            "recall": [0.8, 0.6, 0.4, 0.3],
        }
    )
    fig = graficos.validacao_churn(dados, 90)
    assert len(fig.axes) == 2  # um painel por corte


def test_heatmap_coortes() -> None:
    linhas = []
    for coorte in ("2010-01-01", "2010-02-01"):
        for m in range(3):
            linhas.append(
                {
                    "coorte": pd.Timestamp(coorte),
                    "meses_desde": m,
                    "tamanho": 10,
                    "ativos": 10 if m == 0 else 3,
                    "retencao": 1.0 if m == 0 else 0.3,
                    "pre_existente": False,
                    "mes_parcial": False,
                }
            )
    assert isinstance(graficos.heatmap_coortes(pd.DataFrame(linhas)), Figure)


def test_clv_previsto_vs_real_respeita_a_ordem() -> None:
    dados = pd.DataFrame(
        {
            "segmento": ["Perdidos", "Campeões"],
            "previsto": [1.0, 9.0],
            "ingenuo_sazonal": [0.0, 8.0],
            "real": [2.0, 10.0],
        }
    )
    fig = graficos.clv_previsto_vs_real(dados, ["Campeões", "Leais", "Perdidos"])
    rotulos = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    assert rotulos == ["Campeões", "Perdidos"]
