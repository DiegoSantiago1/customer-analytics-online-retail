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
A planilha tem 12.133 linhas idênticas a outra linha da mesma aba. A reação comum é um `drop_duplicates()`. **Medido antes de decidir:**
- 86% dessas repetições (10.430 de 12.133) estão em linhas **não vizinhas** da mesma fatura;
- na aba 2010-2011, o mesmo produto aparece mais de uma vez na mesma fatura em 9.694 pares fatura+produto, e em 5.084 deles **com quantidades diferentes**. Na fatura 536412, por exemplo, o produto 21448 aparece com quantidade 1 duas vezes e com quantidade 2 três vezes.

Esse é o jeito do sistema de registrar o mesmo item adicionado mais de uma vez no pedido, e não erro de exportação. Apagar as repetições removeria vendas reais. O único artefato comprovado é a sobreposição das abas (D4).

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
- **Compra** = fatura de venda com receita de produto > 0. Uma fatura só de frete não conta.
- **Receita líquida** = receita de produto das compras − valor dos cancelamentos do cliente.
- No fim da base são **5.852 clientes** com ao menos uma compra, **£16.413.301** de receita líquida, **72,4%** com 2 compras ou mais, e os **10% maiores fazem 63,2%** da receita líquida. 87 clientes só aparecem em cancelamentos e ficam fora do RFM.
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
O segmento vem do mapa R × F (`analise.segmento_rfm`, 25 combinações), no padrão de mercado. M fica fora do mapa para que ele continue legível, mas é mostrado ao lado. Resultado no fim da base:

| Segmento | Clientes | % clientes | % receita | Recência média (dias) |
|---|---:|---:|---:|---:|
| Campeões | 1.380 | 23,6 | 69,3 | 20 |
| Leais | 1.025 | 17,5 | 13,9 | 87 |
| Potenciais leais | 442 | 7,6 | 2,4 | 19 |
| Novos | 72 | 1,2 | 0,1 | 11 |
| Promissores | 163 | 2,8 | 0,3 | 38 |
| Precisam de atenção | 425 | 7,3 | 1,4 | 107 |
| Não pode perder | 66 | 1,1 | 2,8 | 330 |
| Em risco | 647 | 11,1 | 5,6 | 362 |
| Hibernando | 673 | 11,5 | 1,8 | 314 |
| Perdidos | 959 | 16,4 | 2,4 | 552 |

### D15. Flag de atacado (aproximação)
O dataset não diz quem é atacadista. A mediana já é de 156 unidades por compra, e o p90 dos clientes é ~408. O flag `eh_atacado` marca quem compra **em média 400 unidades ou mais por pedido** (parâmetro `atacado_unidades_por_pedido`): são **607 clientes (10,4%)**. Ele é um filtro no BI, e o RFM continua único para todos.

## Churn

### D16. Intervalo entre compras
Entre compras consecutivas do mesmo cliente (dias de Londres, `analise.vw_intervalo_compra`): p50 = 25 dias, p75 = 62, p80 = 78, p90 = 136, p95 = 207. Em 3.716 dos 30.742 intervalos, a compra seguinte foi no mesmo dia.

### D17. Escolha do X: 90 dias, pelo F1 na data de corte
Regra: o cliente está em churn se passou **mais de X dias** sem comprar. Validação em 10/06/2011, só com o passado: 4.944 clientes, dos quais 2.372 (48%) não compraram nos 6 meses seguintes.

| X | Marcados | Precisão | Recall | F1 | Acurácia |
|---:|---:|---:|---:|---:|---:|
| 60 | 3.375 | 0,609 | 0,866 | 0,715 | 0,669 |
| **90** | 2.971 | **0,641** | **0,803** | **0,713** | 0,690 |
| 120 | 2.666 | 0,667 | 0,749 | 0,705 | 0,700 |
| 180 | 2.306 | 0,693 | 0,673 | 0,683 | 0,700 |

Entre os candidatos do plano (90, 120 e 180), **90 tem o melhor F1 e o maior recall**. Para o CRM, perceber cedo quem está saindo vale mais do que um alarme falso, porque o custo de uma campanha de reativação é baixo. Leitura: dos marcados, 64% de fato não voltaram; dos que não voltaram, a regra pegou 80%. Como referência, marcar todo mundo daria precisão de 48% (a taxa base).

### D18. A regra depende da época do ano (limitação medida)
Repeti a validação num segundo corte, 10/12/2010, logo depois do pico de vendas (set a nov):

| X | Precisão | Recall | F1 |
|---:|---:|---:|---:|
| 30 | 0,642 | 0,760 | 0,696 |
| 90 | 0,734 | 0,453 | 0,560 |
| 180 | 0,781 | 0,276 | 0,407 |

Logo depois do pico, quase todo mundo comprou há pouco tempo, então a regra marca poucos. Muitos clientes só voltam no pico seguinte: das primeiras voltas depois de 10/12/2010, as mensais caem até agosto (69 clientes) e sobem de novo em setembro, outubro e novembro (121, 148 e 157). Mesmo com uma janela de 12 meses, o F1 com X = 90 nesse corte fica em 0,565.

**Consequência para o fim da base (10/12/2011, também logo depois do pico):** a marcação de churn ali é conservadora. Pelo análogo de dez/2010, cerca de 73% dos marcados de fato não voltam em 6 meses, mas a regra deixa passar metade de quem some. Isso fica registrado no README e na página de Churn do BI. O próximo passo natural seria um limite por cliente (baseado no intervalo típico de cada um) ou um modelo que considere a sazonalidade.

### D19. Receita em risco
`analise.cliente.receita_12m` é a receita líquida de cada cliente nos 12 meses antes do fim da base. Dos £7,98 mi de receita líquida nos últimos 12 meses, **£835 mil** vêm dos 2.967 clientes hoje marcados como churn (50,7% dos clientes).
