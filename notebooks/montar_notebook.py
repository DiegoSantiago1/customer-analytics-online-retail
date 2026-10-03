"""Gera notebooks/customer_analytics.ipynb a partir das células abaixo.

O notebook é gerado por código (e não editado à mão) para o diff no git ser legível
e as células ficarem revisáveis como qualquer outro arquivo. Para gerar e executar:
    python notebooks/montar_notebook.py
    jupyter nbconvert --to notebook --execute --inplace notebooks/customer_analytics.ipynb
"""

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

CELULAS: list[tuple[str, str]] = [
    (
        "md",
        """# Customer Analytics: Online Retail II

Este notebook só **lê e mostra** o que o banco calculou (views do schema `analise`).
Nenhuma regra é recalculada aqui: limpeza, RFM, churn, coortes e CLV estão em SQL
versionado (`db/migracoes`) e testados (`tests/`). As decisões e os números estão em
[`docs/DECISOES.md`](../docs/DECISOES.md).

Pré-requisitos: `python -m varejo.carga` e `python -m varejo.processar`.""",
    ),
    (
        "code",
        """import pandas as pd
from IPython.display import display

from varejo import graficos
from varejo.banco import engine
from varejo.config import RAIZ_PROJETO, carregar_config_banco

motor = engine(carregar_config_banco())
IMG = RAIZ_PROJETO / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)


def ler(consulta: str) -> pd.DataFrame:
    return pd.read_sql(consulta, motor)


def salvar(fig, nome: str) -> None:
    fig.savefig(IMG / f"{nome}.png")


pd.set_option("display.float_format", lambda v: f"{v:,.2f}")""",
    ),
    (
        "md",
        """## 0. Qualidade dos dados

Antes de qualquer número, as 18 checagens do schema `dq`. Todas precisam estar ok.""",
    ),
    (
        "code",
        """dq = ler("SELECT camada, verificacao, esperado, obtido, ok FROM dq.resultado ORDER BY camada, verificacao")
assert dq["ok"].all(), "há checagem de qualidade falhando"
dq""",
    ),
    (
        "md",
        """## 1. Visão geral

Receita de produto por mês, separando o que tem cliente identificado do que não tem
(essa parte não entra nas análises de cliente, mas é receita real).""",
    ),
    (
        "code",
        """receita = ler("SELECT * FROM analise.vw_receita_mes ORDER BY mes")
fig = graficos.receita_mensal(receita)
salvar(fig, "receita_mensal")
totais = receita[["venda_produto_com_cliente", "venda_produto_sem_cliente",
                  "cancelamento_produto", "receita_produto_liquida", "frete_taxas_e_ajustes"]].sum()
totais.to_frame("£")""",
    ),
    (
        "md",
        """**Leitura:** a sazonalidade é forte e se repete: setembro a novembro concentram o
ano (nov/2010 e nov/2011 passam de £1,4 mi, contra £0,5 a £0,7 mi nos meses comuns).
Dez/2011 vai só até o dia 9. Cerca de 13% da receita de produto vem de vendas sem
cliente identificado.""",
    ),
    (
        "md",
        """## 2. Quem são os melhores clientes? (RFM)

Notas de 1 a 5 por `percent_rank` (empates com a mesma nota) e segmento pelo mapa R x F.""",
    ),
    (
        "code",
        """resumo = ler("SELECT * FROM analise.vw_segmento_resumo ORDER BY ordem")
fig = graficos.segmentos(resumo)
salvar(fig, "segmentos")
resumo[["segmento", "clientes", "pct_clientes", "pct_receita", "recencia_media",
        "frequencia_media", "ticket_medio", "atacado"]]""",
    ),
    (
        "md",
        """**Leitura:** os Campeões são 24% dos clientes e fazem 69% da receita líquida
atribuível (clientes identificados).
"Não pode perder" é pequeno (66 clientes), mas tem frequência média de 17 compras: é
a lista de contato pessoal do CRM.""",
    ),
    (
        "code",
        """clientes = ler("SELECT perfil, count(*) AS clientes, sum(receita_liquida) AS receita FROM analise.vw_cliente GROUP BY perfil")
clientes["pct_receita"] = clientes["receita"] / clientes["receita"].sum()
clientes""",
    ),
    (
        "md",
        """## 3. Quem está indo embora? (churn)

Regra: mais de X dias sem comprar. Validada em dois cortes, só com o passado: o "real"
é não ter comprado nos 6 meses seguintes.""",
    ),
    (
        "code",
        """validacao = ler("SELECT * FROM analise.churn_validacao ORDER BY corte DESC, dias")
x = int(ler("SELECT valor FROM analise.parametro WHERE nome = 'churn_dias'").iloc[0, 0])
fig = graficos.validacao_churn(validacao, x)
salvar(fig, "validacao_churn")
validacao[["corte", "dias", "marcados", "precisao", "recall", "f1", "acuracia", "escolhido"]]""",
    ),
    (
        "md",
        """**Leitura:** no corte de junho o F1 é quase plano entre 30 e 120 dias (0,70 a
0,715); ficou X = 90 por ser fácil de agir. Dos marcados, 64% de fato não voltaram, e a
regra pegou 80% dos que não voltaram. Em dezembro, logo depois do pico, a mesma regra
perde recall (45%): muitos clientes só voltam no pico seguinte.

Onde está o sinal: a taxa de "não voltou" por faixa de recência (tabela abaixo) mostra
que quem está de 91 a 180 dias sem comprar não volta em 46% dos casos, praticamente a
taxa base (48%). A regra separa os ativos de quem já foi embora; por isso o fim da base
separa **em risco** (91 a 365 dias) de **inativo** (mais de um ano).""",
    ),
    (
        "code",
        """display(ler("SELECT corte, faixa, clientes, nao_voltaram, taxa_nao_voltou FROM analise.churn_faixa ORDER BY corte DESC, ordem"))
ler(\"\"\"SELECT status_churn, count(*) AS clientes, round(sum(receita_12m)) AS receita_12m
    FROM analise.cliente GROUP BY status_churn ORDER BY status_churn\"\"\")""",
    ),
    ("md", """## 4. A retenção melhora ou piora? (coortes)"""),
    (
        "code",
        """coortes = ler("SELECT * FROM analise.coorte_retencao")
fig = graficos.heatmap_coortes(coortes)
salvar(fig, "coortes")
sem_pre = coortes[~coortes["pre_existente"] & ~coortes["mes_parcial"]]
media = (sem_pre[sem_pre["meses_desde"].isin([1, 3, 6, 12])]
         .groupby("meses_desde")[["ativos", "tamanho"]].sum())
media["retencao"] = media["ativos"] / media["tamanho"]
media""",
    ),
    (
        "md",
        """**Leitura:** cerca de 1 em cada 5 clientes volta a comprar no mês seguinte (21%
no mês 1, 18% no mês 6). Comparar 2010 com 2011 é **inconclusivo**: as coortes do
começo de 2010 misturam clientes antigos que voltaram (censura à esquerda: ~70% dos
"novos" de jan a mar, medido com o análogo de 2011) e a sazonalidade mexe no mês 1. A
diagonal mais escura nas coortes de 2010 é o pico de set a nov do ano seguinte.""",
    ),
    (
        "md",
        """## 5. Quanto vale cada cliente? (CLV)

CLV previsto = p_ativo(segmento) x ticket médio x compras por mês x meses. Validado
com a previsão feita em 10/06/2011 contra a receita real até 10/12/2011.""",
    ),
    (
        "code",
        """resumo_clv = ler("SELECT * FROM analise.clv_validacao")
display(resumo_clv)
validacao_clv = ler("SELECT * FROM analise.clv_validacao_cliente")
ordem = resumo.sort_values("ordem")["segmento"].tolist()
fig = graficos.clv_previsto_vs_real(validacao_clv, ordem)
salvar(fig, "clv_validacao")
validacao_clv.groupby("segmento")[["previsto", "ingenuo_sazonal", "ingenuo", "real"]].sum().reindex(ordem)""",
    ),
    (
        "md",
        """**Leitura:** o modelo ganha do ingênuo sazonal ("repete a mesma janela de um ano
antes") nas três medidas: erro no total +0,2% contra +11,8%, erro médio £603 contra
£650, captura do top 20% 0,882 contra 0,845. Mas o total fecha em parte porque os erros
se compensam: por segmento, o viés vai de -17% (Campeões, subestimados) a +199% (Não
pode perder). O b da suavização foi escolhido nesse mesmo corte. Detalhes em DECISOES
D23 e D24.""",
    ),
    (
        "code",
        """ler(\"\"\"SELECT round(sum(clv_previsto_6m)) AS clv_6m_total,
           round(avg(clv_previsto_6m)) AS media,
           round(percentile_cont(0.5) WITHIN GROUP (ORDER BY clv_previsto_6m)) AS mediana
    FROM analise.cliente\"\"\")""",
    ),
]


def montar() -> nbformat.NotebookNode:
    notebook = new_notebook()
    notebook.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook.cells = [
        new_markdown_cell(texto) if tipo == "md" else new_code_cell(texto)
        for tipo, texto in CELULAS
    ]
    return notebook


if __name__ == "__main__":
    destino = Path(__file__).with_name("customer_analytics.ipynb")
    nbformat.write(montar(), destino)
    print(f"Gerado: {destino}")
