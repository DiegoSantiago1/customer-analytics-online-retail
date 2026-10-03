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
