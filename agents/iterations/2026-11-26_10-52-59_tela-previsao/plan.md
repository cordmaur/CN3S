# Tela de Previsão CN3S

## Fluxo proposto

1. **Estação e calibração.** Manter o seletor compartilhado e recuperar a estação selecionada ao navegar entre as etapas. À direita da estação, listar as calibrações mensais compatíveis, identificadas por nome, data e função objetivo. Mostrar uma orientação para **Calibrar Estação** quando não houver opção compatível.
2. **Revisar os parâmetros.** Ao selecionar uma calibração, mostrar seu gráfico de chuva e vazão, com a marca de início do teste quando disponível. Exibir os oito parâmetros da calibração em uma linha somente leitura, com as unidades de `r0` e `act`. A escolha da calibração define o conjunto. Ajustes continuam na etapa **Calibrar Estação** e podem ser selecionados aqui depois de salvos. Exibir a área calibrada e o aquecimento junto à tabela, pois ambos entram no cálculo.
3. **Configurar a previsão.** Apresentar dois campos: **Mês de inicialização CDS** (mês e ano) e **Número de meses de previsão**. Selecionar inicialmente o ciclo completo mais recente. Oferecer de 1 até o total de meses consecutivos disponíveis no ciclo, começando no primeiro mês listado no calendário dos arquivos. Mostrar o intervalo de chuva resultante abaixo dos campos e manter o horizonte ao trocar de ciclo quando ele ainda for válido. Se exceder o limite, ajustar para o máximo do novo ciclo.
4. **Executar e apresentar a vazão.** Liberar **Executar previsão mensal** após validar a estação, a calibração, o ciclo e a cobertura de chuva mensal. Após a execução, apresentar **Vazão média mensal observada e prevista** como o primeiro e principal resultado, conforme o notebook `nbs/Workflow/05-Inference_Organized.ipynb`, com altura suficiente para ler as curvas. Mostrar a faixa histórica P10–P90, a mediana mensal, o ponto observado do mês de referência com sua data de corte e os cenários de vazão com chuva média e chuva prevista. A faixa representa a variabilidade histórica. A série observada do ano de referência fica sempre visível, e três caixas permitem selecionar individualmente os três anos anteriores. Os gráficos auxiliares, downloads e a procedência vêm depois do gráfico principal.
5. **Alternar a ancoragem.** Colocar a caixa **Ancorar ao observado** junto ao gráfico mensal. A seleção inicial proposta para novas execuções é desmarcada, como no padrão da API. Ao marcar, aplicar a cada cenário de vazão um deslocamento constante, em m³/s, igual ao observado no mês de referência menos a previsão do mesmo mês. Identificar as duas curvas ancoradas na legenda. Preservar as séries numéricas, os CSVs e as demais visualizações. Se faltar a observação ou algum cenário no mês de referência, por exemplo devido ao ACT, manter a figura original e explicar junto à caixa por que a ancoragem está indisponível.
6. **Exibir todo o horizonte de vazão.** A caixa **Centralizar no mês de referência** seleciona entre a janela centrada e a janela que começa em janeiro. A primeira parte de seis meses de cada lado e se amplia simetricamente quando necessário. A segunda vai até dezembro ou até o último mês previsto de vazão, se posterior. **A virada do ano nunca corta a previsão.** Calcular o fim do eixo pela última data dos cenários de vazão, que já incorporam o ACT, e identificar o novo ano no eixo. Por exemplo, seis meses a partir de outubro, com ACT zero, seguem de outubro a março nas duas janelas. O seletor de anos anteriores afeta apenas as séries históricas exibidas.

## Integração proposta

- Concentrar as mudanças em `web/templates/cn3s_previsao.html`, `web/static/cn3s.js` e no CSS compartilhado, com ajuste no template comum se necessário para alinhar os seletores.
- Reusar o catálogo da estação, a formatação do nome da calibração e o endpoint do gráfico salvo. Ao trocar de estação ou calibração, limpar o gráfico e a tabela anteriores e ignorar respostas de seleções antigas. Informar falhas de carregamento no próprio gráfico. Para calibração legada sem figura arquivada, identificar a reconstrução com arquivos mensais atuais oferecida pelo endpoint.
- Reusar `GET /cycles` para obter o calendário comum aos modelos. Desabilitar ciclos incompletos e informar quando nenhum está disponível. Definir o mês de `as_of` pelo primeiro mês do calendário selecionado. Para que a ancoragem possa usar os dias observados nesse mês, propõe-se usar o dia da execução em America/Sao_Paulo quando o mês estiver em curso, o último dia em meses encerrados e o primeiro dia para um mês futuro. Exibir e registrar o corte efetivo. Para um ciclo histórico, o resultado pode incorporar observações coletadas após a inicialização do CDS e deve indicar a data usada.
- Reusar `Inference.plot_monthly_discharge(months_each_side=6, anchor_to_observed=...)` em `web/cn3s.py`. Gerar a figura padrão e, quando houver dados para ancorar, a segunda figura na mesma execução, para alternar a visualização sem repetir a simulação nem a consulta de vazão. Uma falha específica da ancoragem deve preservar a figura padrão. Quando a comparação observada inteira estiver indisponível, manter os demais resultados e destacar o motivo. Substituir a nota fixa da tela sobre o ajuste por uma indicação ligada à figura em exibição.
- Na implementação, adaptar o intervalo mensal da figura para incluir todas as datas previstas nas duas janelas. Usar datas com mês e ano para posicionar as previsões e preservar a sequência dezembro, janeiro, fevereiro e assim por diante. Aplicar os controles de exibição aos resultados já calculados.
- Verificar troca de estação e de calibração, gráfico indisponível, ciclo incompleto, redução do horizonte, virada de ano, chuva insuficiente e recuperação de uma operação concluída. Comparar as duas figuras com o notebook, confirmar o deslocamento constante, testar ausência de observação parcial ou de previsão no mês de referência e verificar a figura e a tabela em telas estreitas.

## Registro da sessão

Revisados o fluxo atual e as duas figuras mensais registradas no notebook. O mockup abre com o exemplo de Marabá, de outubro de 2026, com a ancoragem marcada para reproduzir a figura enviada. O gráfico usa os valores arquivados, arredondados ao m³/s, nessa configuração. As demais configurações usam séries demonstrativas. A execução no mockup é simulada.

No Chromium, foram verificados o deslocamento constante das duas curvas, sua coincidência com o observado em outubro, a preservação da mediana histórica ao alternar a caixa, o aviso quando o ACT impede a ancoragem, a atualização do resultado após trocar o horizonte e o layout em 320, 736 e 1.024 pixels.

Na revisão do mockup, o gráfico de calibração passou a exibir todo o período ilustrativo. Foram acrescentadas as seleções independentes de 2025, 2024 e 2023 e a alternância entre a janela centrada e a janela iniciada em janeiro. O Chromium confirmou que 2026 permanece visível, a troca de janela reposiciona o mês de referência e a ancoragem funciona nas duas janelas. A série de 2023 foi identificada como ilustrativa.

O gráfico de previsão passou de 310 para 480 pixels de altura no desktop e 400 pixels em telas estreitas. No Chromium, foram verificados horizontes que terminam em dezembro, janeiro, fevereiro e março, além de um caso em que o ACT estende a série de vazão até abril. Ambas as janelas mantiveram todos os meses previstos.

## Exemplos de chamadas

Rotas relativas ao módulo CN3S. O exemplo usa a data de referência fixada no notebook.

```text
GET  /stations/29050000
GET  /stations/29050000/calibrations/chart?calibration=Monthly%2Foptim%2Fmensal_exemplo.json
GET  /cycles
POST /stations/29050000/forecast
     {"calibration":"Monthly/optim/mensal_exemplo.json","cycle":"202610","as_of":"2026-10-13","months":6}
GET  /operations/<id>
```

```python
inference.plot_monthly_discharge(months_each_side=6, anchor_to_observed=False)
inference.plot_monthly_discharge(months_each_side=6, anchor_to_observed=True)
```
