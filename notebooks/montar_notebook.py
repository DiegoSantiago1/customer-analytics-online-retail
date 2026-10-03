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

Antes de qualquer número, as 16 checagens do schema `dq`. Todas precisam estar ok.""",
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
        """**Leitura:** os Campeões são 24% dos clientes e fazem 69% da receita líquida.
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
        """**Leitura:** no corte de junho, X = 90 tem o melhor F1 entre 90, 120 e 180 (0,71):
dos marcados, 64% de fato não voltaram, e a regra pegou 80% dos que não voltaram. Em
dezembro, logo depois do pico, a mesma regra perde recall (45%): muitos clientes só
voltam no pico seguinte. A marcação do fim da base (também em dezembro) é, portanto,
conservadora.""",
    ),
    (
        "code",
        """ler(\"\"\"SELECT segmento, count(*) FILTER (WHERE em_churn) AS em_churn,
           round(sum(receita_12m) FILTER (WHERE em_churn)) AS receita_12m_em_risco
    FROM analise.vw_cliente GROUP BY segmento, segmento_ordem ORDER BY segmento_ordem\"\"\")""",
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
        """**Leitura:** a retenção é estável, em torno de 21% no mês 1 e 18% no mês 6, sem
piora entre 2010 e 2011. O que caiu foi a entrada de clientes novos (set-nov: 940 em
2010, 600 em 2011). A diagonal mais escura nas coortes de 2010 é o pico de set-nov do
ano seguinte.""",
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
validacao_clv.groupby("segmento")[["previsto", "ingenuo", "real"]].sum().reindex(ordem)""",
    ),
    (
        "md",
        """**Leitura:** o modelo erra o total em +0,5%, e o ingênuo ("repete os 6 meses
anteriores") erra em -29%, porque não enxerga o pico de fim de ano. Na ordenação os
dois empatam (os 20% maiores previstos capturam 88% do que um top 20% perfeito
capturaria). O ingênuo ganha no erro médio por cliente. Detalhes em DECISOES D24.""",
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
