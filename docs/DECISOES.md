# Decisões do projeto

Cada decisão traz o que foi decidido, por quê, e o número medido que a sustenta. Os números vêm do banco (`retail`), depois de `python -m varejo.carga` e `python -m varejo.processar`, e são conferidos pelos testes ou pelo schema `dq`.

## Ambiente

### D1. Leitura da planilha com o motor calamine
O pandas lê xlsx com o `openpyxl` (padrão) ou com o `calamine` (Rust). Medido em 03/10/2026, na planilha do projeto: **13,7 s contra 77,4 s**. Antes de trocar, comparei as duas leituras célula a célula: **as 8,5 milhões de células saíram idênticas**. Custo: uma dependência (`python-calamine`) no lugar de outra.

### D2. Bruto como texto e ida e volta conferida
O schema `bruto` guarda as 8 colunas como texto, sem restrições, com a aba e a linha da planilha como chave. Assim, qualquer número da análise pode ser rastreado até a célula original. A carga foi conferida comparando planilha e banco: **1.067.371 linhas, nenhuma célula diferente**, incluindo os espaços no começo de algumas descrições.

### D3. Download com SHA-256
A planilha (45 MB) não vai para o git. `python -m varejo.baixar_dados` baixa o zip da UCI, extrai só o arquivo esperado (o que protege de *zip slip* e de *zip bomb*) e só põe o arquivo no lugar se o SHA-256 bater. Se a UCI publicar outra versão, o script recusa, porque os números do projeto valem para esta versão.

## Limpeza (schema `limpo`)

### D4. Sobreposição das abas: só a aba nova vale
A aba "Year 2009-2010" vai até 09/12/2010 e a "Year 2010-2011" começa em 01/12/2010. Medido: **as 22.523 linhas desse período são idênticas nas duas abas**, inclusive na contagem de repetições (`EXCEPT ALL` vazio nos dois sentidos). A regra é ficar só com a aba nova: a antiga sai inteira a partir do primeiro dia da nova. O `dq` confere essa igualdade a cada carga. Sem isso, dezembro de 2010 contaria em dobro.

### D5. Repetições dentro de uma aba são mantidas (não são duplicatas)
A planilha tem **34.335 linhas idênticas a outra linha**. A reação comum seria um `drop_duplicates()`. **Medido antes de decidir:**
- **22.523** são a sobreposição das abas (D4), que é artefato da exportação e foi removida;
- as **11.812** restantes são repetições dentro da mesma aba, e **85,7%** delas (10.127) estão em linhas **não vizinhas** da mesma fatura;
- no `limpo`, 21.234 pares fatura+produto aparecem mais de uma vez, e **10.967 deles com quantidades diferentes**. Na fatura 536412, por exemplo, o produto 21448 aparece com quantidade 1 duas vezes e com quantidade 2 três vezes.

Esse é o jeito do sistema de registrar o mesmo item adicionado mais de uma vez no pedido, e não erro de exportação. As 11.812 linhas mantidas valem £57.481 (0,3% da venda): apagá-las removeria vendas reais. O único artefato comprovado é a sobreposição das abas.

### D6. Tipo de cada linha
Toda linha recebe um tipo, e os `CHECK`s da tabela garantem que o tipo nunca contradiz os sinais:

| Tipo | Regra | Linhas | Valor (£) |
|---|---|---:|---:|
| venda | fatura numérica, quantidade > 0, preço > 0 | 1.019.653 | 20.522.680 |
| cancelamento | fatura `C…`, quantidade < 0, preço > 0 | 19.164 | −1.465.677 |
| sem_valor | fatura numérica, preço 0 ("damages", "lost", brindes) | 6.024 | 0 |
| ajuste_divida | fatura `A…` ("Adjust bad debt") | 6 | −147.614 |
| anomalia | o resto | 1 | 373,57 |

A única anomalia é a C496350: um lançamento "Manual" numa fatura de cancelamento com quantidade positiva. Ela fica fora das análises, e o `dq` avisa se aparecer outra.

### D7. Códigos que não são produto
Há 26 StockCodes que não são mercadoria (tabela `limpo.codigo_nao_produto`): frete (POST, DOT, C2, C3), taxas (BANK CHARGES, AMAZONFEE, CRUK), desconto (D), lançamento manual (M, m), ajustes (ADJUST, ADJUST2, B), amostras (S), vales-presente (GIFT, gift_0001_*) e produtos de teste (TEST001, TEST002). Eles saem da **receita de produto** e são reportados à parte. Nas vendas com cliente, isso representa £306.610 (frete e afins).

Ficam como produto, mesmo fora do padrão de 5 dígitos: os DCGS* (produtos da loja do site), PADS (almofadas vendidas a £0,001), SP1002 e "47503J " (com espaço no fim, removido na limpeza).

### D8. Fuso horário
O horário da planilha é local do Reino Unido, sem fuso. Ele é convertido com `AT TIME ZONE 'Europe/London'` para `timestamptz`, e o banco usa `Europe/London` como fuso das sessões. As vendas vão de 06:10 a 21:52, então nenhuma cai na hora ambígua da troca de horário de verão (01:00 a 02:00).

### D9. Linhas sem cliente
243.007 linhas não têm `Customer ID` e ficam no `limpo`, porque o total precisa bater com a fonte. Fora as da sobreposição, são 228.608 linhas de venda (226.882 delas de produto), com £2.576.013 de **receita de produto não atribuível**. Elas não entram em RFM, churn, coortes nem CLV, mas aparecem na visão geral.

### D10. Clientes em mais de um país
13 clientes aparecem com mais de um país. `limpo.cliente.pais` é o país mais frequente nas linhas de cada um, e `n_paises` registra quantos países apareceram.

## Clientes e RFM (schema `analise`)

### D11. Tudo numa data de referência
`analise.metricas_cliente(data_ref)` e `analise.rfm(data_ref)` só enxergam pedidos anteriores à data de referência. A mesma função responde "como estava a base em 10/06/2011?" (validação do churn e do CLV) e "como está no fim?" (10/12/2011, o dia seguinte à última fatura). Assim, a validação usa exatamente o mesmo código da análise final e não tem como olhar o futuro (há teste para isso).

### D12. O que é compra e o que é receita
- **Compra** = fatura de venda com receita de produto > 0. Uma fatura só de frete não conta. F conta **faturas**, não ocasiões: 3.716 intervalos entre compras são de 0 dias (duas faturas no mesmo dia), o que infla um pouco F e a taxa de compras. É uma escolha consciente: a fatura é a unidade que o negócio registra.
- **Receita líquida** = vendas de produto − cancelamentos de produto do cliente. Créditos que não são produto dentro de faturas de cancelamento (sobretudo o código "M", lançamento manual: −£337.492 em clientes identificados) **não** são abatidos, porque não dá para saber a que venda se referem. Por isso o README diz "vendas de produto − cancelamentos de produto".
- No fim da base são **5.852 clientes** com ao menos uma compra, **£16.413.301** de receita líquida **atribuível** (clientes identificados), **72,4%** com 2 compras ou mais, e os **10% maiores fazem 63,2%** dessa receita. 87 clientes só aparecem em cancelamentos e ficam fora do RFM.
- 20 clientes têm receita líquida ≤ 0, quase todos por terem cancelado a única compra inteira. Ficam com nota M = 1 e o flag `liquido_nao_positivo`.

### D13. Notas por `percent_rank`, não por `NTILE(5)` (desvio do plano)
O plano previa `NTILE(5)`. Medido: **1.618 clientes têm exatamente 1 compra**. O `NTILE` divide em 5 grupos de mesmo tamanho e, para isso, espalharia esses clientes empatados entre as notas 1 e 2 em ordem arbitrária: dois clientes iguais com notas diferentes. A nota é `1 + floor(5 × percent_rank)`, em que empates recebem sempre a mesma nota. R e M (quase sem empates) ficam em quintos de ~1.170 clientes. F reflete os empates:

| F | Compras | Clientes |
|---|---|---:|
| 1 | 1 | 1.618 |
| 2 | 2 | 945 |
| 3 | 3 a 4 | 1.148 |
| 4 | 5 a 8 | 1.025 |
| 5 | 9 ou mais | 1.116 |

### D14. Segmentos
O segmento vem do mapa R × F (`analise.segmento_rfm`, 25 combinações), no padrão de mercado. M fica fora do mapa para que ele continue legível, mas é mostrado ao lado. O mapa é **monotônico**: comprar mais recentemente ou mais vezes nunca rebaixa o cliente (testado célula a célula; ver D27). Resultado no fim da base:

| Segmento | Clientes | % clientes | % receita | Recência média (dias) |
|---|---:|---:|---:|---:|
| Campeões | 1.380 | 23,6 | 69,3 | 20 |
| Leais | 1.196 | 20,4 | 15,2 | 76 |
| Potenciais leais | 271 | 4,6 | 1,2 | 25 |
| Novos | 72 | 1,2 | 0,1 | 11 |
| Promissores | 163 | 2,8 | 0,3 | 38 |
| Precisam de atenção | 425 | 7,3 | 1,4 | 107 |
| Não pode perder | 66 | 1,1 | 2,8 | 330 |
| Em risco | 647 | 11,1 | 5,6 | 362 |
| Hibernando | 673 | 11,5 | 1,8 | 314 |
| Perdidos | 959 | 16,4 | 2,4 | 552 |

Os percentuais de receita são da receita líquida **atribuível** (clientes identificados).

### D15. Flag de atacado (aproximação)
O dataset não diz quem é atacadista. A mediana já é de 156 unidades por compra, e o p90 dos clientes é ~408. O flag `eh_atacado` marca quem compra **em média 400 unidades ou mais por pedido** (parâmetro `atacado_unidades_por_pedido`): são **607 clientes (10,4%)**. Ele é um filtro no BI, e o RFM continua único para todos.

## Churn

### D16. Intervalo entre compras
Entre compras consecutivas do mesmo cliente (dias de Londres, `analise.vw_intervalo_compra`): p50 = 25 dias, p75 = 62, p80 = 78, p90 = 136, p95 = 207. Em 3.716 dos 30.742 intervalos, a compra seguinte foi no mesmo dia.

### D17. Escolha do X: 90 dias (o F1 é praticamente plano)
Regra: o cliente está em churn se passou **mais de X dias** sem comprar. Validação em 10/06/2011, só com o passado: 4.944 clientes, dos quais 2.372 (48%) não compraram nos 6 meses seguintes.

| X | Marcados | Precisão | Recall | F1 | Acurácia |
|---:|---:|---:|---:|---:|---:|
| 30 | 3.907 | 0,564 | 0,928 | 0,701 | 0,621 |
| 60 | 3.375 | 0,609 | 0,866 | **0,715** | 0,669 |
| **90** | 2.971 | 0,641 | 0,803 | 0,713 | 0,690 |
| 120 | 2.666 | 0,667 | 0,749 | 0,705 | 0,700 |
| 180 | 2.306 | 0,693 | 0,673 | 0,683 | 0,700 |

**Leitura honesta (revisão de dados):** o F1 é praticamente o mesmo entre 30 e 120 dias (0,70 a 0,715); o melhor absoluto é 60. Entre os candidatos do plano (90, 120 e 180), 90 tem o melhor F1 e o maior recall, e "um trimestre sem comprar" é uma regra fácil de explicar ao CRM; por isso 90. Como X é escolhido e avaliado no mesmo corte, a diferença de 0,002 entre 60 e 90 não significa nada.

**Onde está o sinal.** A taxa de "não voltou" por faixa de recência (`analise.churn_faixa`) mostra que a precisão vem sobretudo de quem já sumiu há muito tempo:

| Faixa (corte de 10/06/2011) | Clientes | Não voltaram |
|---|---:|---:|
| até 90 dias | 1.973 | 23,7% |
| 91 a 180 dias | 665 | **46,2%** |
| 181 a 365 dias | 1.685 | 63,3% |
| mais de 365 dias | 621 | 85,3% |

Quem acabou de passar dos 90 dias (91 a 180) não volta em 46% dos casos, praticamente a taxa base (48%): nessa faixa a regra **não** informa mais que o acaso. Ela separa bem os ativos (até 90 dias, 24%) dos que já foram embora. Por isso o fim da base separa **em risco** (91 a 365 dias) de **inativo** (mais de 365), em vez de um único "churn".

### D18. A regra depende da época do ano (limitação medida)
Repeti a validação num segundo corte, 10/12/2010, logo depois do pico de vendas (set a nov):

| X | Precisão | Recall | F1 |
|---:|---:|---:|---:|
| 30 | 0,642 | 0,760 | 0,696 |
| 90 | 0,734 | 0,453 | 0,560 |
| 180 | 0,781 | 0,276 | 0,407 |

Logo depois do pico, quase todo mundo comprou há pouco tempo, então a regra marca poucos. Muitos clientes só voltam no pico seguinte: das primeiras voltas depois de 10/12/2010, as mensais caem até agosto (69 clientes) e sobem de novo em setembro, outubro e novembro (121, 148 e 157). Mesmo com uma janela de 12 meses, o F1 com X = 90 nesse corte fica em 0,565.

**Consequência para o fim da base (10/12/2011, também logo depois do pico):** a marcação de churn ali é conservadora. Pelo análogo de dez/2010, cerca de 73% dos marcados de fato não voltam em 6 meses, mas a regra deixa passar metade de quem some. Isso fica registrado no README e na página de Churn do BI. O próximo passo natural seria um limite por cliente (baseado no intervalo típico de cada um) ou um modelo que considere a sazonalidade.

### D19. Em risco, inativos e receita em risco
`analise.cliente.status_churn` separa o que a regra única misturava. No fim da base (10/12/2011):

| Status | Regra | Clientes | Receita líquida dos últimos 12 meses |
|---|---|---:|---:|
| ativo | até 90 dias sem comprar | 2.885 | £7.148.662 |
| **em risco** | 91 a 365 dias | **1.376** | **£837.690** |
| inativo | mais de 365 dias | 1.591 | −£2.569 |

Os 2.967 com mais de 90 dias sem comprar (50,7%) são a soma de em risco e inativos, mas **mais da metade deles (1.591) já não compra há mais de um ano**: não estão "indo embora", já foram. A receita em risco está praticamente toda nos 1.376 em risco.

## Coortes

### D20. Coorte = mês da primeira compra, com grade completa
`analise.coorte_retencao` tem uma linha por coorte × mês desde a primeira compra, até o último mês da base. Os meses sem compra aparecem com 0 ativos, para o heatmap não ter buracos. A coorte vem de `min(mes) OVER (PARTITION BY cliente_id)`. A receita do mês é líquida (compras − cancelamentos daquele mês). A soma dos tamanhos das coortes é igual ao número de clientes (5.852).

### D21. Dez/2009 = pré-existentes; coortes do começo da base contaminadas
- Dez/2009 é o primeiro mês da base: os 951 clientes dessa coorte não são necessariamente novos, são só o primeiro registro. A coorte é marcada como `pre_existente` e fica fora das médias.
- O mesmo efeito (censura à esquerda) contamina **muito** as coortes seguintes, e não pouco como a primeira versão deste documento dizia. Medido com o análogo de 2011 (contando como "novo" só quem não comprou nos meses anteriores dentro da mesma janela de histórico): cerca de **70%** dos "novos" de jan a mar e **39%** dos "novos" de set a nov já eram clientes antes. Um cliente de 2010 que comprou pela primeira vez "na base" pode ser só um cliente antigo que não comprou em dez/2009.
- Dez/2011 vai só até o dia 9 e é marcado como `mes_parcial`.
- Cancelamento anterior à primeira compra (de uma venda de antes da base) entra no mês 0 da coorte; sem isso, as coortes somavam £3.325 a mais que os clientes (achado do QA; o dq agora confere).

### D22. A retenção melhora ou piora? Inconclusivo, e por quê
Retenção média ponderada (sem pré-existentes e sem o mês parcial): **21,0% no mês 1, 21,1% no mês 3, 18,4% no mês 6 e 18,4% no mês 12**.

**A comparação entre anos não é de igual para igual** (revisão de dados):
- no mês 1: 19,9% nas coortes de 2010 contra 23,6% nas de 2011. Mas as coortes de 2010 estão misturadas com clientes antigos que voltaram (D21), e o mês 1 das coortes de 2011 sobe de 16,7% (jan) para 31,7% (out) só pela sazonalidade;
- no mês 6: 18,3% contra 19,6%, e o mês 6 de 2011 só tem 5 coortes (jan a mai), cujo mês 6 cai perto do pico.

Conclusão: com dois anos de dados e a censura à esquerda, **não dá para afirmar** que a retenção melhorou ou piorou. O que dá para afirmar é a forma da curva: cerca de 1 em cada 5 clientes volta no mês seguinte, e as coortes voltam a subir em set a nov do ano seguinte (a sazonalidade da D18).

**Correção de uma afirmação anterior:** a primeira versão deste documento dizia que a aquisição de clientes novos caiu 36% (940 em set a nov de 2010 contra 600 em 2011). Era artefato da censura: com a mesma janela de histórico para trás nos dois anos, set a nov de 2011 tem **979** "novos", contra 940 em 2010. A afirmação foi retirada.

## CLV

### D23. Fórmula
- **CLV histórico** = receita líquida acumulada (`analise.cliente.receita_liquida`).
- **CLV previsto** para os próximos H meses, numa data T:
  `p_ativo(segmento) × ticket médio líquido × compras por mês × H`
  - **p_ativo**: fração dos clientes do mesmo segmento RFM que compraram de novo numa janela de H meses na **mesma época do ano anterior** (de T − 12 meses a T − 12 meses + H). A sazonalidade é forte (D18), e calibrar numa janela de outra época distorceria a previsão.
  - **compras por mês** = `(compras + b × taxa da base) / (meses de vida + b)`, com b = 3 meses: a média de uma Gamma-Poisson. Sem essa suavização, um cliente com uma compra há 10 dias teria "1 compra por mês", e na primeira validação o CLV dos Novos saiu 2,8 vezes o real.

Sem biblioteca nova, e cada termo pode ser explicado. **Limitação conhecida (revisão de dados):** p_ativo é a probabilidade de ao menos uma compra na janela, e "compras por mês × H" já é uma esperança que inclui os meses parados; o produto conta a inatividade duas vezes, e o b acaba compensando isso em parte. Além disso, a calibração usa segmentos de 10/06/2010, quando a base tinha só 6 meses: um "Perdido" daquela época tinha no máximo 6 meses sem comprar. BG/NBD e Gamma-Gamma (que modelam isso direito) ficam como próximos passos.

### D24. Validação no corte (previsão de 6 meses feita em 10/06/2011)
A comparação é contra a receita líquida real de 10/06 a 10/12/2011 (£4,24 mi, 4.944 clientes), e contra dois modelos ingênuos: "os próximos 6 meses repetem os 6 anteriores" e o **ingênuo sazonal**, "repetem a mesma janela de um ano antes" (o adversário justo, porque também enxerga a sazonalidade; incluído depois da revisão de dados).

| Modelo | Total previsto | Erro no total | Erro médio por cliente | Captura do top 20% |
|---|---:|---:|---:|---:|
| **Previsto** | £4,25 mi | **+0,2%** | £603 | **0,882** |
| Ingênuo sazonal | £4,74 mi | +11,8% | £650 | 0,845 |
| Ingênuo (6 meses anteriores) | £3,01 mi | −29,2% | **£547** | 0,869 |

*Captura do top 20%* = quanto da receita real está nos 20% de clientes com maior previsão, dividido pelo que um top 20% perfeito capturaria.

Leitura honesta:
- O modelo **ganha do ingênuo sazonal nas três métricas**.
- O **erro de +0,2% no total é em boa parte compensação de erros**. Por segmento, o viés vai de **−17% (Campeões, subestimados)** a **+199% (Não pode perder)**: Leais +31%, Em risco +55%, Perdidos +90%, Promissores +100%, Precisam de atenção +107%. O total fecha porque os Campeões, que são a maior parte da receita, são subestimados e os outros superestimados.
- O b foi escolhido nesse mesmo corte (não há um segundo corte possível com dois anos de dados). A sensibilidade mostra quanto o total depende dele:

| b (meses) | Erro no total | Erro médio | Captura do top 20% |
|---:|---:|---:|---:|
| 0 (sem suavização) | +7,6% | £603 | 0,877 |
| 1 | +3,8% | £594 | 0,883 |
| **3** | **+0,2%** | £603 | 0,882 |
| 6 | −2,8% | £626 | 0,883 |
| 12 | −6,5% | £668 | 0,876 |

A **ordenação** (captura do top 20%) praticamente não depende do b, e é ela que importa para priorizar campanha. O erro no total depende, e por isso o +0,2% não deve ser lido como precisão do modelo.

### D25. Horizonte final de 6 meses, não 12 (desvio do plano)
O plano previa um CLV de 12 meses. Com o mesmo método, o CLV de 12 meses no fim daria cerca de £9,35 mi, contra £7,98 mi de receita real nos 12 meses anteriores. **Esse horizonte não tem como ser validado com 2 anos de dados**: seriam necessários 12 meses depois de um corte, mais um ano antes dele para calibrar. Por isso o CLV publicado é o de **6 meses**, o mesmo horizonte validado: **£3,82 mi** para os 6 meses seguintes ao fim da base. Na mesma época do ano anterior, a receita real foi £3,01 mi, com uma base de clientes 37% menor. Os 20% de clientes com maior CLV concentram 74% do valor previsto. Os vieses por segmento da D24 valem aqui também.

Bug achado pelos testes: se ninguém comprar na janela, o total real é zero e o erro percentual não existe. A coluna era `NOT NULL`, o que derrubava a recarga inteira. Agora o valor fica NULL.

## Qualidade de dados (schema `dq`)

### D26. O que o dq checa e por quê
As restrições do banco (`CHECK`, `FOREIGN KEY`, `NOT NULL`) impedem linhas impossíveis. O `dq.verificar()` cobre o que uma restrição de linha não enxerga. São **18 checagens**:
- **Totais que precisam bater entre camadas:** linhas do bruto = última carga; limpo = bruto − sobreposição; soma de quantidade × preço conservada; pedidos = linhas de venda e cancelamento; receita líquida dos clientes = compras − cancelamentos deles; soma das coortes = clientes; **receita somada nas coortes = receita dos clientes**.
- **Premissas medidas que podem deixar de valer numa carga nova:** sobreposição das abas idêntica (`EXCEPT ALL` nos dois sentidos); nenhum código novo fora do padrão de produto sem classificação; nenhuma anomalia além da C496350; nenhuma linha na hora ambígua do horário de verão; cada fatura com um cliente só; **nenhuma fatura misturando linhas com e sem cliente**.
- **Forma das distribuições:** os quintos de R e M com tamanhos parecidos (maior/menor ≤ 1,10; medido 1,03); CLV e churn preenchidos para todos; validação do churn nos dois cortes.

**Se alguma checagem falhar, o `python -m varejo.processar` desfaz a transação inteira** (o banco continua com o último resultado bom) e o `python -m varejo.exportar_site` se recusa a exportar: um número reprovado não chega ao Power BI nem ao site. Cada checagem tem um teste que corrompe o dado e confirma que ela falha.

O teste `test_pipeline_completo_reproduz_os_numeros_documentados` roda o pipeline inteiro sobre a planilha real e confere os principais números deste documento. Uma mudança que altere um número publicado quebra esse teste.

## Revisão independente (T12)

### D27. O que as três revisões acharam e o que mudou
Antes de publicar, três revisões independentes (engenharia, QA e dados), feitas por agentes separados que só podiam ler o projeto. Todos os números do README foram re-consultados no banco pela revisão de dados: **nenhum divergia**. Os problemas eram de método, de redação e de robustez:

| Achado | Revisão | O que mudou |
|---|---|---|
| `timestamptz + interval '6 months'` dependia do fuso da **sessão**: o mesmo cenário dava resultados diferentes em Londres e em UTC | QA | Toda função do pipeline roda com `SET timezone = 'Europe/London'` (migration 0010); testes em 4 fusos |
| A "queda de 36% na aquisição" era artefato da censura à esquerda | Dados | Afirmação retirada; D21 e D22 reescritas |
| "Retenção estável nos dois anos" era uma comparação confundida | Dados | D22: inconclusivo, com os motivos |
| A precisão do churn vinha de quem já tinha sumido; "2.967 indo embora" misturava em risco com inativos | Dados | `status_churn` (ativo, em risco, inativo) e `churn_faixa`; D17 e D19 |
| O +0,5% do CLV era compensação de erros, com b escolhido no próprio teste; o ingênuo era fraco | Dados | Ingênuo sazonal incluído; vieses por segmento e sensibilidade publicados (D24) |
| Mapa R × F não monotônico em (R5, F3) | Dados | Vira "Leais"; teste do mapa inteiro e da monotonicidade |
| Coortes somavam £3.325 a mais que os clientes | QA | Cancelamento anterior à primeira compra entra no mês 0; checagem nova no dq |
| dq dava falso alarme sem a aba nova; fatura mista passava sem aviso | QA | `coalesce(..., 'infinity')` no dq; checagem nova |
| 10 checagens do dq sem teste negativo | QA | Um teste de corrupção por checagem |
| Dados reprovados no dq eram gravados e podiam ser exportados | Engenharia | Rollback no `processar`; o exportador recusa |
| O "Como rodar" do README não funcionava para quem clona | Engenharia | Ativação da venv por shell, `docker-compose.yml`, `.env.example` genérico |
| O bootstrap podia alterar um usuário de outro projeto no container compartilhado | Engenharia | Recusa usuário igual ao superusuário e role que já seja superusuário ou dona de outros bancos |
| Download sem timeout; site quebrava com valor nulo | Engenharia/QA | Timeout e limpeza do arquivo parcial; site robusto a nulos e a cortes vindos do JSON |
