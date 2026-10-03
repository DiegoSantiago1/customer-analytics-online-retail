# Customer Analytics: Online Retail II

**Quem são os melhores clientes, quem está indo embora e quanto eles valem?** Segmentação RFM, churn validado no tempo, coortes de retenção e valor do cliente (CLV) para uma varejista online real de Londres, com PostgreSQL, SQL, Python e Power BI.

[English](README.md) · **[Página interativa](https://diegosantiago1.github.io/customer-analytics-online-retail/)** · [Decisões e medições](docs/DECISOES.md) · [Relatório Power BI](docs/POWERBI.md) · [Notebook](notebooks/customer_analytics.ipynb)

![Power BI: segmentos RFM](docs/img/powerbi_segmentos.png)

## As respostas

| Pergunta | Resposta | Como foi conferido |
|---|---|---|
| **Quem são os melhores clientes?** | **Os Campeões são 24% dos 5.852 clientes e trazem 69% da receita líquida atribuível.** Os 10% maiores trazem 63%. 72% compraram ao menos duas vezes. | Notas RFM calculadas em SQL; empates sempre com a mesma nota |
| **Quem está indo embora?** | **1.376 clientes em risco** (91 a 365 dias sem comprar). A receita deles nos últimos 12 meses foi de **£838 mil**. Outros 1.591 não compram há mais de um ano: já foram embora. | A regra foi aplicada numa data de corte passada, só com o que se sabia naquele dia, e comparada com quem de fato voltou |
| **A retenção melhora ou piora?** | **Cerca de 1 em cada 5 clientes volta a comprar no mês seguinte** (21% no mês 1, 18% no mês 6). Se está melhorando **não dá para afirmar** com dois anos de dados: as primeiras coortes misturam clientes antigos que voltaram, e a sazonalidade mexe no mês 1. | Coortes mensais com window functions, conferidas quanto à censura à esquerda |
| **Quanto vale cada cliente?** | **£3,82 mi esperados nos próximos 6 meses.** Os 20% de clientes com maior valor previsto concentram 74% disso. | Uma previsão feita em junho de 2011 ganhou de um modelo ingênuo sazonal no erro do total, no erro por cliente e na ordenação |

## O que faz disto mais que um tutorial

**1. Medir antes de limpar.** O dataset tem 34.335 linhas idênticas a outra. O gesto comum seria um `drop_duplicates()`. Medir antes mostrou que são duas coisas diferentes:
- **22.523 são artefato da exportação.** As duas abas do Excel se sobrepõem de 1 a 9 de dezembro de 2010, e esse período é idêntico nas duas, até nas linhas repetidas. A sobreposição é removida.
- **As outras 11.812 parecem compras reais e foram mantidas.** 86% delas estão em linhas não vizinhas da mesma fatura. Em 10.967 pares fatura+produto, o mesmo produto aparece de novo com outra quantidade. Isso é consistente com o caixa registrando o item adicionado duas vezes no pedido. Elas valem £57 mil (0,3% da venda). ([D4, D5](docs/DECISOES.md))

**2. Churn validado no tempo, inclusive onde não tem sinal.** "Mais de 90 dias sem comprar" foi testado numa data de corte passada (junho de 2011): 64% dos marcados de fato não voltaram, e a regra pegou 80% de quem foi embora. O F1 é quase o mesmo entre 30 e 120 dias, então ficou 90, por ser fácil de agir. Olhando por faixa de recência dá para ver onde está o sinal:
- quem estava de 91 a 180 dias sem comprar não voltou em 46% dos casos, quase o mesmo que o cliente médio (48%);
- a regra separa sobretudo os ativos (24% não voltaram) de quem já foi embora (85% com mais de um ano).

Por isso o relatório separa **em risco** de **inativo**. Logo depois do pico de set a nov, a regra também pega só 45% de quem some, porque muitos clientes só voltam no pico seguinte. ([D17 a D19](docs/DECISOES.md))

![Validação do churn em dois cortes](docs/img/validacao_churn.png)

**3. CLV conferido contra o que de fato aconteceu, contra um adversário justo.** A previsão cabe numa linha:

> probabilidade de seguir ativo por segmento × ticket médio × compras por mês × meses

Duas escolhas fazem ela funcionar:
- A probabilidade é medida **na mesma época do ano anterior**, porque a sazonalidade é forte.
- A taxa de compra de clientes novos é suavizada em direção à média (Gamma-Poisson). Sem isso, a previsão dos "Novos" saía 2,8 vezes o real.

| Modelo (previsão feita em 10/06/2011, 6 meses) | Erro no total | Erro médio por cliente | Captura do top 20% |
|---|---:|---:|---:|
| **Este modelo** | **+0,2%** | £603 | **0,882** |
| Ingênuo sazonal (mesma janela um ano antes) | +11,8% | £650 | 0,845 |
| Ingênuo (repete os 6 meses anteriores) | −29,2% | **£547** | 0,869 |

O modelo ganha do ingênuo sazonal nas três medidas. O +0,2% no total não deve ser lido como precisão:
- os erros se compensam em parte: por segmento, o viés vai de −17% (Campeões) a +199% ("Não pode perder");
- o parâmetro de suavização foi escolhido nesse mesmo corte, e a sensibilidade dele está publicada.

([D23 a D25](docs/DECISOES.md))

**4. Revisado antes de publicar.** Três revisões independentes (engenharia, QA e metodologia de dados) re-consultaram cada número de destaque. Nenhum estava errado, mas as revisões acharam problemas reais, todos corrigidos e listados na [D27](docs/DECISOES.md):
- um bug de fuso: o resultado dependia do fuso da sessão;
- uma afirmação enganosa de que a aquisição caiu 36%, que na verdade era censura à esquerda;
- um título de churn enganoso;
- um adversário fraco para o CLV;
- lacunas nos testes.

**5. Todo número é reproduzível e testado.**
- A planilha é baixada e conferida por SHA-256.
- Cada regra é uma migration SQL versionada.
- **280 testes automatizados** cobrem as regras, entre eles casos hostis e 4 fusos de sessão. Um teste ponta a ponta roda o pipeline inteiro sobre a planilha real e confere os números publicados.
- Um schema de qualidade de dados roda **18 checagens**. Se alguma falhar, o pipeline inteiro é desfeito e a exportação do site se recusa a rodar.
- Cada número do Power BI foi conferido contra o SQL ([tabela](docs/POWERBI.md#conferência-contra-o-sql)).

## Arquitetura

```mermaid
flowchart LR
    UCI[zip da UCI] -->|download + SHA-256| XLSX[xlsx 45 MB]
    XLSX -->|Python: lê + COPY| BRUTO[(bruto<br/>texto como veio)]
    BRUTO -->|migrations SQL| LIMPO[(limpo<br/>tipado, CHECKs)]
    LIMPO --> ANALISE[(analise<br/>RFM, churn,<br/>coortes, CLV)]
    BRUTO & LIMPO & ANALISE --> DQ[(dq<br/>18 checagens)]
    ANALISE -->|usuário só leitura| PBI[Power BI]
    ANALISE --> NB[Notebook]
    ANALISE -->|só agregados| SITE[GitHub Pages]
```

- **O SQL faz as contas, o Python orquestra.** Cada etapa reconstrói o próprio schema a partir do anterior, numa transação só (`python -m varejo.processar`).
- **Funções numa data de referência.** `analise.metricas_cliente(data)` e `analise.rfm(data)` só enxergam pedidos anteriores à data. A validação usa exatamente o mesmo código da análise final e não tem como olhar o futuro (testado).
- **Fuso fixo na origem e nas funções.** O horário das faturas é local do Reino Unido, gravado como `timestamptz`. Toda função do pipeline roda com `SET timezone = 'Europe/London'`, então o resultado não depende de quem roda.
- **Menor privilégio.** O Power BI conecta com um usuário que só lê os schemas `analise` e `dq` (testado).

| Visão geral | Churn | Coortes e CLV |
|---|---|---|
| ![](docs/img/powerbi_visao_geral.png) | ![](docs/img/powerbi_churn.png) | ![](docs/img/powerbi_coortes_clv.png) |

## Dados

[Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), UCI Machine Learning Repository (Chen, 2012), licença CC BY 4.0. É uma varejista online do Reino Unido de presentes e utilidades, com muitos clientes atacadistas, de 01/12/2009 a 09/12/2011: 1.067.371 linhas de fatura em duas abas.

Código, tabelas e colunas estão em português. O dicionário dos nomes originais está no [README em inglês](README.md#data).

## Como rodar

Requisitos: Python 3.14, Docker e, para o relatório, Power BI Desktop. Clone **fora** de pasta sincronizada como o OneDrive (ele trava arquivos da `.venv` e de `data/`).

```bash
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt     # rode na pasta do projeto (instala o pacote com -e .)
cp .env.example .env                    # PowerShell: Copy-Item .env.example .env  -> depois defina as senhas
docker compose up -d                    # PostgreSQL 16 em 127.0.0.1:5432 (docker-compose.yml)
python -m varejo.bootstrap              # usuário + bancos, via docker exec (sem guardar senha de superusuário)
alembic upgrade head                    # schemas, regras e funções (10 migrations)
python -m varejo.baixar_dados           # baixa o xlsx e confere o SHA-256
python -m varejo.carga                  # 1.067.371 linhas no bruto (~30 s)
python -m varejo.processar              # limpo -> analise -> dq (~30 s); desfaz tudo se uma checagem falhar
python -m varejo.exportar_site          # site/dados.json (recusa se o dq falhou)
python -m http.server 8000 -d site      # a página interativa em http://127.0.0.1:8000 (as setas passam de capítulo)
pytest                                  # 280 testes (-m "not lento" pula os 2 com a planilha real)
```

Depois, abra `powerbi/customer_analytics.pbip` ([passo a passo da conexão](docs/POWERBI.md)) ou rode o notebook. O relatório lê o banco `retail` em `127.0.0.1`. Se você mudar o `VAREJO_DB_NAME`, regere o relatório com `python powerbi/gerar_pbip.py`. A página em `site/` é publicada no GitHub Pages pelo `.github/workflows/pages.yml` (Settings → Pages → Source: GitHub Actions).

## Limitações e próximos passos

- **Churn.** A regra com X fixo diz pouco logo depois do limite e perde recall logo depois do pico. O próximo passo é um limite por cliente, baseado no intervalo de compra de cada um, ou um modelo que enxergue a época do ano.
- **CLV.** A fórmula conta a inatividade duas vezes (probabilidade de seguir ativo × uma taxa média que já inclui os meses parados), e a suavização compensa isso em parte. O viés por segmento é grande. BG/NBD + Gamma-Gamma modelariam isso direito. O horizonte é de 6 meses, porque 12 não teriam como ser validados com dois anos de dados.
- **Tendência da retenção.** Não dá para avaliá-la com dois anos de dados e as primeiras coortes com censura à esquerda.
- **Definições.**
  - A frequência conta faturas, então faturas do mesmo dia contam duas vezes.
  - Os créditos manuais ("M") dentro de faturas de cancelamento não são abatidos.
  - O flag de atacado (≥ 400 unidades por pedido em média, cerca dos 10% maiores) é uma aproximação.
  - 13% da venda de produto não tem cliente identificado.

---

Diego Freitas Santiago · analista de dados · [GitHub](https://github.com/DiegoSantiago1)
