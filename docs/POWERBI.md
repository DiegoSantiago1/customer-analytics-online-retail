# Relatório Power BI

O relatório está em [`powerbi/customer_analytics.pbip`](../powerbi/), no formato de projeto do Power BI (PBIP): o modelo fica em texto (TMDL, uma tabela por arquivo, com medidas e descrições) e as páginas em JSON (PBIR, um arquivo por visual). Os arquivos **são gerados** por [`powerbi/gerar_pbip.py`](../powerbi/gerar_pbip.py): tabelas, relacionamentos, medidas DAX, páginas e visuais estão descritos nesse script, revisável no git como o resto do projeto.

```
python powerbi/gerar_pbip.py
```

O arquivo não guarda dados nem senha: os dados vêm do banco a cada atualização (o cache local `.pbi/` é ignorado pelo git).

Público: gerente de marketing/CRM. Quatro páginas, uma por pergunta.

| Visão geral | Segmentos RFM |
|---|---|
| ![Visão geral](img/powerbi_visao_geral.png) | ![Segmentos RFM](img/powerbi_segmentos.png) |
| **Churn** | **Coortes e CLV** |
| ![Churn](img/powerbi_churn.png) | ![Coortes e CLV](img/powerbi_coortes_clv.png) |

## Abrir e atualizar

1. Docker Desktop aberto, banco carregado (`python -m varejo.carga` e `python -m varejo.processar`).
2. Duplo clique em `powerbi/customer_analytics.pbip` e **Atualizar agora**.
3. Só na primeira vez, o Power BI pede a credencial de `127.0.0.1;retail`:

| Campo | Valor |
|---|---|
| Tipo | Banco de Dados |
| Nome do usuário | `varejo_bi` (variável `VAREJO_BI_USER` do `.env`) |
| Senha | `VAREJO_BI_PASSWORD` do `.env` |
| Nível | `127.0.0.1` |

4. Se aparecer "Suporte a Criptografia", clique em **OK**: a conexão é local (a porta do container só é publicada em `127.0.0.1`).

**Por que o servidor é `127.0.0.1` e não `127.0.0.1:5432`:** o Power BI guarda a credencial por endereço, e `127.0.0.1:5432` já tem a do usuário do BI do Projeto 2, que não enxerga este banco (testado: "permission denied for database retail"). Sem a porta, o endereço é outro e a porta padrão é a mesma.

O usuário `varejo_bi` **só lê** os schemas `analise` e `dq`: não vê `bruto` nem `limpo` e não consegue rodar recargas nem alterar nada (testado em `tests/test_views.py`).

## Modelo

| Tabela | Origem | O que tem |
|---|---|---|
| `receita_mes` | `analise.vw_receita_mes` | receita por mês e origem (com/sem cliente, cancelamentos, frete), pedidos, clientes ativos e novos |
| `segmento` | `analise.segmento` | os 10 segmentos, ordem de exibição e ação sugerida (dimensão) |
| `cliente` | `analise.vw_cliente` | um cliente por linha: RFM, segmento, perfil, churn, receita em risco, CLV |
| `churn_validacao` | `analise.churn_validacao` | precisão, recall, F1 e acurácia da regra para 8 valores de X em 2 cortes |
| `coorte` | `analise.coorte_retencao` | retenção por coorte e mês desde a primeira compra |
| `clv_validacao`, `clv_validacao_cliente` | `analise.clv_validacao*` | validação do CLV: modelo, ingênuo e real |
| `qualidade` | `dq.resultado` | as 16 checagens de qualidade |

Relacionamentos: `segmento[segmento]` → `cliente[segmento]` e `clv_validacao_cliente[segmento]` (um para muitos). O segmento e a faixa de recência são ordenados pelas colunas de ordem (não alfabeticamente).

As medidas DAX só somam, contam e dividem o que o SQL já calculou; nenhuma regra de negócio vive no DAX. A descrição de cada medida está no TMDL (`tables/Medidas.tmdl`) e aparece como dica no Power BI.

## Conferência contra o SQL

Cada número do relatório foi conferido contra o banco, com o relatório aberto no Power BI Desktop (03/10/2026):

| Página | Visual | Power BI | SQL |
|---|---|---|---|
| Visão geral | Receita de produto | £18.981.262 | `sum(receita_produto_liquida)` de `vw_receita_mes` = 18.981.262 |
| Visão geral | Clientes | 5.852 | `count(*)` de `analise.cliente` = 5.852 |
| Visão geral | Venda sem cliente | 13,1% | 2.576.013 / (17.124.941 + 2.576.013) = 13,08% |
| Visão geral | Checagens | 16 de 16 | `dq.resultado`: 16 ok |
| Segmentos | Receita líquida / ticket médio | £16.413.301 / £448,52 | 16.413.301 / 36.594 compras = 448,52 |
| Segmentos | Tabela (Campeões) | 1.380 · £11.372.064 · CLV £2.611.038 | `vw_segmento_resumo`: idem |
| Segmentos | Filtro Atacado | 607 · £6.241.911 · £1.255,16 · 263 em churn | `WHERE eh_atacado`: idem |
| Churn | Em churn / % / receita em risco | 2.967 · 50,7% · £835.121 | idem (DECISOES D19) |
| Churn | Precisão da regra (jun/2011) | 64,1% | `churn_validacao`: 0,6409 |
| Coortes e CLV | Retenção total, meses 1/3/6/12 | 21,0% · 21,1% · 18,4% · 18,4% | DECISOES D22: idem |
| Coortes e CLV | CLV previsto, 6 meses | £3.809.240 | `sum(clv_previsto_6m)` = 3.809.240 |
| Coortes e CLV | Modelo x ingênuo | +0,5 / −29,2; 0,883 / 0,869 | `clv_validacao`: idem |

## O que o gerador garante (testes)

`tests/test_powerbi.py`: gerar duas vezes dá o mesmo resultado (identificadores determinísticos); todo JSON é válido; todo campo usado em visual, toda coluna citada no DAX, todo relacionamento e toda ordenação existem no modelo; cada coluna do modelo existe na view do banco (consultado como o usuário do BI); o modelo não contém senha.

Problemas achados ao abrir no Desktop e corrigidos no gerador: coluna no eixo Y sem agregação deixava o gráfico vazio (trocado por medidas); cartões abreviavam demais ("£4 Mi"); o tema personalizado deixava títulos em cinza-claro (resolvido com `visualStyles` no tema).
