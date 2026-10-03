"""Gráficos estáticos (matplotlib) do notebook e do README.

Cada função recebe um DataFrame lido das views do schema analise e devolve uma
Figure. Nenhuma conta nova acontece aqui: o gráfico mostra o que o SQL calculou.

Paleta: a paleta categórica de referência, em ordem fixa (validada para daltonismo
nos pares vizinhos), e o azul sequencial para o heatmap. Texto sempre em tons de
cinza; a cor fica só nas marcas.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, PercentFormatter

# Categórica (ordem fixa: azul, laranja, verde-água).
SERIE = ["#2a78d6", "#eb6834", "#1baf7a"]
TEXTO = "#0b0b0b"
TEXTO_2 = "#52514e"
GRADE = "#e4e3df"
FUNDO = "#fcfcfb"
# Azul sequencial, do quase-zero ao máximo.
SEQUENCIAL = LinearSegmentedColormap.from_list(
    "azul", ["#f3f7fd", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]
)

plt.rcParams.update(
    {
        "figure.facecolor": FUNDO,
        "axes.facecolor": FUNDO,
        "axes.edgecolor": GRADE,
        "axes.labelcolor": TEXTO_2,
        "axes.titlecolor": TEXTO,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRADE,
        "grid.linewidth": 0.8,
        "xtick.color": TEXTO_2,
        "ytick.color": TEXTO_2,
        "font.size": 10,
        "legend.frameon": False,
        "legend.labelcolor": TEXTO_2,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    }
)


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _mes(data: object) -> str:
    """Mês abreviado em português ("nov/10"), sem depender do locale do sistema."""
    ts = pd.Timestamp(data)  # type: ignore[arg-type]
    return f"{MESES[ts.month - 1]}/{ts:%y}"


def _libras(valor: float, _pos: object = None) -> str:
    if abs(valor) >= 1_000_000:
        return f"£{valor / 1_000_000:.1f} mi".replace(".", ",")
    if abs(valor) >= 1_000:
        return f"£{valor / 1_000:.0f} mil"
    return f"£{valor:.0f}"


def _subtitulo(ax: Axes, texto: str) -> None:
    ax.text(0, 1.02, texto, transform=ax.transAxes, color=TEXTO_2, fontsize=9.5, va="bottom")


def receita_mensal(receita_mes: pd.DataFrame) -> Figure:
    """Barras empilhadas: receita de produto com e sem cliente identificado, por mês."""
    dados = receita_mes.sort_values("mes")
    rotulos = [_mes(m) for m in dados["mes"]]
    x = np.arange(len(dados))
    com = dados["venda_produto_com_cliente"].astype(float).to_numpy()
    sem = dados["venda_produto_sem_cliente"].astype(float).to_numpy()

    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.bar(x, com, color=SERIE[0], width=0.72, label="Com cliente identificado")
    # edgecolor do fundo = o espaço de 2px entre os segmentos empilhados
    ax.bar(
        x,
        sem,
        bottom=com,
        color=SERIE[1],
        width=0.72,
        label="Sem cliente (não atribuível)",
        edgecolor=FUNDO,
        linewidth=1.5,
    )
    parcial = dados["mes_parcial"].to_numpy()
    for i in np.flatnonzero(parcial):
        ax.annotate(
            "até dia 9",
            (x[i], com[i] + sem[i]),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            color=TEXTO_2,
            fontsize=8.5,
        )
    ax.set_xticks(x[::2], rotulos[::2])
    ax.yaxis.set_major_formatter(FuncFormatter(_libras))
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, float((com + sem).max()) * 1.18)  # espaço para a legenda
    ax.set_title("Receita de produto por mês", pad=22)
    _subtitulo(ax, "Vendas antes dos cancelamentos. O pico de set a nov se repete nos dois anos.")
    ax.legend(loc="upper left", ncols=2)
    return fig


def segmentos(resumo: pd.DataFrame) -> Figure:
    """Barras horizontais pareadas: % dos clientes e % da receita líquida por segmento."""
    dados = resumo.sort_values("ordem", ascending=False)
    y = np.arange(len(dados))
    altura = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.barh(
        y + altura / 2,
        dados["pct_clientes"].astype(float),
        height=altura,
        color=SERIE[0],
        label="% dos clientes",
    )
    ax.barh(
        y - altura / 2,
        dados["pct_receita"].astype(float),
        height=altura,
        color=SERIE[1],
        label="% da receita líquida",
    )
    for yi, (pc, pr) in zip(
        y, dados[["pct_clientes", "pct_receita"]].astype(float).to_numpy(), strict=True
    ):
        ax.text(pc + 0.005, yi + altura / 2, f"{pc:.0%}", va="center", color=TEXTO_2, fontsize=8.5)
        ax.text(pr + 0.005, yi - altura / 2, f"{pr:.0%}", va="center", color=TEXTO_2, fontsize=8.5)
    ax.set_yticks(y, dados["segmento"])
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", visible=False)
    ax.set_title("Segmentos RFM: quem traz a receita", pad=22)
    _subtitulo(ax, "Fim da base (10/12/2011), 5.852 clientes.")
    ax.legend(loc="lower right")
    return fig


def validacao_churn(validacao: pd.DataFrame, dias_escolhido: int) -> Figure:
    """Precisão e recall da regra de churn por X, um painel por data de corte."""
    cortes = sorted(validacao["corte"].unique(), reverse=True)
    fig, eixos = plt.subplots(1, len(cortes), figsize=(11, 4.2), sharey=True)
    eixos = np.atleast_1d(eixos)
    for ax, corte in zip(eixos, cortes, strict=True):
        dados = validacao[validacao["corte"] == corte].sort_values("dias")
        for coluna, cor, nome in (
            ("precisao", SERIE[0], "Precisão"),
            ("recall", SERIE[1], "Recall"),
        ):
            ax.plot(
                dados["dias"],
                dados[coluna].astype(float),
                color=cor,
                linewidth=2,
                marker="o",
                markersize=5,
                label=nome,
            )
        ax.axvline(dias_escolhido, color=TEXTO_2, linewidth=1, linestyle=(0, (3, 3)))
        ax.text(dias_escolhido + 6, 0.95, f"X = {dias_escolhido}", color=TEXTO_2, fontsize=9)
        ax.set_title(f"Corte em {pd.Timestamp(corte):%d/%m/%Y}", fontsize=11)
        ax.set_xlabel("X (dias sem comprar)")
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    eixos[0].legend(loc="lower left")
    fig.suptitle(
        "Regra de churn validada no tempo",
        x=0.01,
        y=1.0,
        ha="left",
        fontweight="bold",
        color=TEXTO,
        fontsize=13,
    )
    fig.text(
        0.01,
        0.905,
        "Logo depois do pico (dez/2010), a mesma regra perde recall: muitos "
        "clientes só voltam no pico seguinte.",
        color=TEXTO_2,
        fontsize=9.5,
    )
    fig.subplots_adjust(top=0.78)
    return fig


def heatmap_coortes(coortes: pd.DataFrame, meses: int = 12) -> Figure:
    """Retenção por coorte (linhas) e meses desde a primeira compra (colunas)."""
    dados = coortes[
        (~coortes["pre_existente"])
        & (coortes["meses_desde"].between(1, meses))
        & (~coortes["mes_parcial"])
    ]
    tabela = dados.pivot(index="coorte", columns="meses_desde", values="retencao").astype(float)
    tamanhos = coortes[coortes["meses_desde"] == 0].set_index("coorte")["tamanho"]
    tabela = tabela.sort_index()

    fig, ax = plt.subplots(figsize=(11, 7))
    imagem = ax.imshow(tabela.to_numpy(), cmap=SEQUENCIAL, vmin=0, vmax=0.4, aspect="auto")
    ax.grid(False)
    for (i, j), v in np.ndenumerate(tabela.to_numpy()):
        if not np.isnan(v):
            ax.text(
                j,
                i,
                f"{v:.0%}",
                ha="center",
                va="center",
                fontsize=7.5,
                color="#ffffff" if v >= 0.25 else TEXTO,
            )
    ax.set_xticks(range(len(tabela.columns)), [str(c) for c in tabela.columns])
    ax.set_yticks(range(len(tabela.index)), [f"{_mes(c)} ({tamanhos[c]})" for c in tabela.index])
    ax.set_xlabel("Meses desde a primeira compra")
    for lado in ("left", "bottom"):
        ax.spines[lado].set_visible(False)
    barra = fig.colorbar(
        imagem, ax=ax, fraction=0.03, pad=0.02, format=PercentFormatter(1.0, decimals=0)
    )
    barra.outline.set_visible(False)
    ax.set_title("Retenção mensal por coorte", pad=22)
    _subtitulo(
        ax,
        "Coorte = mês da primeira compra (tamanho entre parênteses). Sem a coorte "
        "pré-existente de dez/2009 e sem o mês parcial.",
    )
    return fig


def clv_previsto_vs_real(validacao_cliente: pd.DataFrame, ordem: list[str]) -> Figure:
    """Barras agrupadas por segmento: previsto, ingênuo e real (6 meses após o corte)."""
    soma = validacao_cliente.groupby("segmento")[["previsto", "ingenuo", "real"]].sum()
    soma = soma.reindex([s for s in ordem if s in soma.index])
    x = np.arange(len(soma))
    largura = 0.27
    fig, ax = plt.subplots(figsize=(11, 4.6))
    series = (
        ("previsto", "Previsto (modelo)"),
        ("ingenuo", "Ingênuo (repete 6 meses)"),
        ("real", "Real"),
    )
    for k, (coluna, nome) in enumerate(series):
        ax.bar(
            x + (k - 1) * largura,
            soma[coluna].astype(float),
            width=largura - 0.02,
            color=SERIE[k],
            label=nome,
        )
    ax.set_xticks(x, soma.index, rotation=20, ha="right")
    ax.yaxis.set_major_formatter(FuncFormatter(_libras))
    ax.axhline(0, color=TEXTO_2, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.set_title("CLV de 6 meses: previsto x real, por segmento", pad=22)
    _subtitulo(ax, "Previsão feita em 10/06/2011; real = receita líquida até 10/12/2011.")
    ax.legend(loc="upper right")
    return fig
