# Customer Analytics: Online Retail II

**Who are the best customers, who is leaving, and what are they worth?** RFM segmentation, churn validated back in time, retention cohorts and customer lifetime value for a real London online retailer, built with PostgreSQL, SQL, Python and Power BI.

[Português](README.pt-BR.md) · **[Interactive page](https://diegosantiago1.github.io/customer-analytics-online-retail/)** · [Decisions and measurements](docs/DECISOES.md) · [Power BI report](docs/POWERBI.md) · [Notebook](notebooks/customer_analytics.ipynb)

![Power BI: RFM segments](docs/img/powerbi_segmentos.png)

## The answers

| Question | Answer | How it was checked |
|---|---|---|
| **Who are the best customers?** | **Champions are 24% of the 5,852 customers and bring 69% of net revenue.** The top 10% of customers bring 63%. 72% bought at least twice. | RFM scores computed in SQL; ties always get the same score |
| **Who is leaving?** | **2,967 customers (51%)** have gone more than 90 days without buying. They spent **£835k** in the last 12 months. | The rule was applied at a past cut-off using only data available then, and compared with who actually came back |
| **Is retention getting better or worse?** | **Stable**: about 21% of each cohort buys again in month 1 and 18% in month 6, in both years. What fell was **new-customer acquisition** (Sep–Nov: 940 in 2010, 600 in 2011, −36%). | Monthly cohorts with window functions |
| **What is each customer worth?** | **£3.81m expected in the next 6 months.** The top 20% of customers by predicted value hold 74% of it. | The same forecast made in June 2011 missed the real total by **+0.5%**. A naive "repeat the last 6 months" forecast missed it by −29% |

## What makes it more than a tutorial

**1. Measured before cleaning.** The dataset has 34,335 exactly duplicated lines. The usual move is `drop_duplicates()`. Measuring first showed two different things:
- **22,523 lines are an export artefact.** The two sheets of the Excel file overlap from 1 to 9 Dec 2010, and that period is identical in both, down to the repeated lines. The overlap is removed.
- **The other 11,812 are real purchases.** 86% of them are on non-adjacent lines of the same invoice. In 10,967 invoice/product pairs, the same product appears again with a different quantity. This is how the till records an item added twice to the same order. Deleting those lines would have removed £57k of real sales. ([D4, D5](docs/DECISOES.md))

**2. Churn validated over time, including where it fails.** At the June 2011 cut-off, "more than 90 days without buying" had the best F1 (0.71) among 90, 120 and 180 days: 64% of the flagged customers really did not come back, and the rule caught 80% of those who left. Repeating the test right after the Sep–Nov peak (Dec 2010), the same rule catches only 45%, because many customers only return at the next peak. That limitation is measured and shown in the report, not hidden. ([D17, D18](docs/DECISOES.md))

![Churn validation at two cut-offs](docs/img/validacao_churn.png)

**3. CLV checked against what actually happened.** The forecast is simple enough to explain in one line:

> active probability by segment × average order value × purchases per month × months

The parts that make it work:
- The active probability is measured in **the same season one year earlier**, because seasonality is strong.
- New customers' purchase rate is smoothed toward the average (Gamma-Poisson). Without this, the forecast for "New" customers came out at 2.8× reality.

| Model (forecast made on 10 Jun 2011, 6 months) | Error on total | Mean abs. error per customer | Top-20% capture |
|---|---:|---:|---:|
| **This model** | **+0.5%** | £604 | **0.883** |
| Naive (repeat the previous 6 months) | −29.2% | **£547** | 0.869 |

The naive model wins on per-customer error, and that is reported too. ([D23–D25](docs/DECISOES.md))

**4. Every number is reproducible and tested.**
- The raw file is downloaded and verified by SHA-256.
- Every rule is a versioned SQL migration.
- **227 automated tests** cover the rules, with hostile inputs among them. One end-to-end test reruns the whole pipeline on the real file and checks the numbers published in [DECISOES.md](docs/DECISOES.md).
- A data-quality schema runs **16 checks** (totals reconcile across layers; measured assumptions still hold) and the pipeline fails if any of them breaks.
- Every number in the Power BI report was checked against SQL ([table](docs/POWERBI.md#conferência-contra-o-sql)).

## Architecture

```mermaid
flowchart LR
    UCI[UCI zip] -->|download + SHA-256| XLSX[xlsx 45 MB]
    XLSX -->|Python: read + COPY| BRUTO[(bruto<br/>raw text)]
    BRUTO -->|SQL migrations| LIMPO[(limpo<br/>typed, CHECKs)]
    LIMPO --> ANALISE[(analise<br/>RFM, churn,<br/>cohorts, CLV)]
    BRUTO & LIMPO & ANALISE --> DQ[(dq<br/>16 checks)]
    ANALISE -->|read-only user| PBI[Power BI]
    ANALISE --> NB[Notebook]
    ANALISE -->|aggregates only| SITE[GitHub Pages]
```

- **The SQL does the maths, Python orchestrates.** Python only downloads, loads and calls the SQL functions. Each step rebuilds its own schema from the previous one (`python -m varejo.processar`), in one transaction.
- **Point-in-time functions.** `analise.metricas_cliente(date)` and `analise.rfm(date)` only see orders before the date. Validation therefore uses exactly the same code as the final analysis and cannot look into the future, and a test enforces that.
- **Least privilege.** Power BI connects with a user that only reads the `analise` and `dq` schemas and cannot run any reload (tested).
- **Time zone at the source.** Invoice times are UK local time, converted with `AT TIME ZONE 'Europe/London'` into `timestamptz`. A test covers the BST/GMT boundary.

| Overview | Churn | Cohorts and CLV |
|---|---|---|
| ![](docs/img/powerbi_visao_geral.png) | ![](docs/img/powerbi_churn.png) | ![](docs/img/powerbi_coortes_clv.png) |

## Data

[Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), UCI Machine Learning Repository (Chen, 2012), licence CC BY 4.0. It covers a UK-based online retailer of gifts and homewares, many of its customers wholesalers, from 1 Dec 2009 to 9 Dec 2011: 1,067,371 invoice lines in two sheets.

The code, tables and columns are in **Portuguese** (the author's language). The data dictionary:

| Original | In this project | | Schema / object | Meaning |
|---|---|---|---|---|
| Invoice | `fatura` | | `bruto` | raw sheet as text |
| StockCode | `codigo_produto` | | `limpo` | cleaned and typed lines |
| Description | `descricao` | | `analise` | analysis (orders, customers, RFM, churn, cohorts, CLV) |
| Quantity | `quantidade` | | `dq` | data-quality checks |
| InvoiceDate | `data_fatura` | | `pedido` / `cliente` | order / customer |
| Price | `preco_unitario` | | `receita_liquida` | net revenue (sales − cancellations) |
| Customer ID | `cliente_id` | | `segmento` / `em_churn` | RFM segment / churned |
| Country | `pais` | | `coorte_retencao` | retention cohort |

## Run it

Requirements: Python 3.14, Docker (PostgreSQL 16 container) and, for the report, Power BI Desktop.

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env                 # set the passwords
python -m varejo.bootstrap           # user + databases (via docker exec, no superuser password stored)
alembic upgrade head                 # schemas, rules and functions (9 migrations)
python -m varejo.baixar_dados        # downloads the xlsx and checks SHA-256
python -m varejo.carga               # 1,067,371 lines into bruto (~30 s)
python -m varejo.processar           # limpo -> analise -> dq (~30 s); fails if a check fails
python -m varejo.exportar_site       # site/dados.json
pytest                               # 227 tests (use -m "not lento" to skip the 2 on the real file)
```

Then open `powerbi/customer_analytics.pbip` ([connection steps](docs/POWERBI.md)) or run the notebook.

```
src/varejo/        download, load, pipeline runner, charts, site export
db/migracoes/      9 Alembic migrations (hand-written SQL)
tests/             227 pytest tests (cleaning, RFM, churn, cohorts, CLV, dq, views, BI)
notebooks/         analysis notebook (reads views only) and its generator
powerbi/           PBIP report (TMDL + PBIR), generated by gerar_pbip.py
site/              static page for GitHub Pages
docs/              PLAN, DECISOES (every decision with its measurement), POWERBI
```

## Limitations and next steps

- **Seasonality.** A fixed-X churn rule loses recall right after the peak. Next step: a per-customer threshold based on each customer's own purchase interval, or a model that sees the season.
- **CLV horizon.** It is 6 months, because 12 months cannot be validated with two years of data.
- **The wholesale flag is a proxy.** It means ≥ 400 units per order on average (about the top 10%), because the data does not say who is a wholesaler.
- **Not attributable.** 13% of product sales have no customer ID and stay out of the customer analyses.
- **Possible extensions.** BG/NBD + Gamma-Gamma for CLV, a churn classifier compared against the rule, market-basket analysis.

---

Diego Freitas Santiago · data analyst · [GitHub](https://github.com/DiegoSantiago1)
