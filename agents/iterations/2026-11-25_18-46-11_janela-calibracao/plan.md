# Janela Calibração do CN3S

Implementação local concluída. Referência de interface no [mockup interativo](mockup.html). Para percorrer os dois caminhos, abra Marabá e alterne as calibrações. Depois selecione Valparaíso e abra **Nova calibração**. No exemplo falta a vazão mensal. Os dados, as datas e os resultados são ilustrativos.

## Sessão Azure

O SHC configura a sessão Flask para uma hora em `web/app.py`. Em `web/login.py`, termina o contexto de `DeviceCodeCredential` logo após a autenticação e conserva no servidor apenas o token de acesso SQL, com expiração no menor prazo entre uma hora e a validade desse token. Mesmo um usuário ativo acaba voltando ao login. Os dez minutos de `LOGIN_TIMEOUT` controlam a espera pelo código de dispositivo.

Proponho experimentar uma sessão de oito horas de inatividade, configurável na implantação. Guardar, por sessão e conta, o estado necessário à renovação silenciosa no servidor. Reaproveitar o token válido e renová-lo antes de acessar SQL quando preciso. Distinguir indisponibilidade temporária de exigência de interação. Respeitar revogação e MFA, limpar a credencial ao sair e recuperar a estação de origem após nova autenticação. Para sobreviver à recriação do contêiner, verificar segredo estável e persistência protegida do cache no ambiente publicado. Validar com duas contas, após o primeiro vencimento, após inatividade e depois de sair. A política efetiva da instituição precisa ser verificada no ambiente. [Aquisição silenciosa de tokens](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens) · [Frequência de entrada no Entra](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-session-lifetime)

## Fluxo da página

1. Restaurar a estação da navegação, conforme o fechamento da janela Estação. Na primeira visita sem código, aguardar a seleção. A entrada do mockup já mostra Marabá para facilitar a revisão.
2. Ler o histórico local de `Monthly/optim` e da pasta legada `optim` via `calibrations()`. Ordenar as calibrações mensais compatíveis por `metadata.saved_at` decrescente. Usar o caminho relativo como identidade e desempate. Selecionar a primeira automaticamente. Mostrar data e hora em Brasília, objetivo e período dos dados. Sem data registrada, ordenar ao fim e indicar o campo ausente. Identificar arquivos incompatíveis ou inválidos separadamente.
3. Ao trocar a calibração, trocar juntos a linha dos oito parâmetros finais de `params` e as duas linhas de desempenho. Ler objetivo e NSE de treino e teste de `metadata.final_metrics`. Se necessário, consultar a linha identificada por `final_step` no histórico antigo. Identificar métricas ausentes como indisponíveis. A função objetivo é uma perda a minimizar. Para PlainNSE, ela vale 1 − NSE. O NSE cresce com a qualidade do ajuste.
4. Manter **Nova calibração** disponível também quando o histórico estiver vazio. O diálogo identifica a estação, mostra o resumo diário de vazão salvo em `overview.json` por fonte e código, data da consulta, período, anos efetivos e falhas. Se faltar o resumo, indicar onde atualizá-lo na janela Estação. As estatísticas diárias orientam a escolha de datas. A cobertura mensal vem dos arquivos efetivamente preparados.
5. Escolher mês inicial e final inclusivos, função objetivo e **Relação Treino/Teste**, expressa por duas porcentagens complementares (padrão 90% / 10%, com opções de 10% / 90% a 95% / 5% em incrementos de cinco pontos percentuais). A primeira se refere ao trecho cronológico inicial e é enviada ao otimizador como train_ratio. Editar aquecimento, semente, critério de parada e os limites de busca no próprio diálogo. Sugerir datas pela cobertura local comum utilizável. Quando faltar uma entrada, usar o resumo de vazão como referência inicial. Conferir lacunas antes de habilitar a execução. O mockup usa períodos fixos para comparação.
6. **Calibrar e salvar** inicia a operação com os dados locais. Gerar um nome único no servidor, exibir andamento real e preservar o formulário em caso de erro. Selecionar a nova calibração após publicação concluída se o usuário continua na mesma estação. Mostrar o motivo de parada do otimizador mesmo quando há um resultado salvo. Fechar ou cancelar o diálogo antes de executar preserva a calibração selecionada.

## Quando buscar os dados

| Ação | Leitura ou operação | O que a pessoa vê |
| --- | --- | --- |
| Selecionar estação ou histórico | Ler metadados e resultados locais | Histórico e resultado, inclusive sem conexão com as fontes de dados |
| Abrir o diálogo ou mudar o período | Ler resumo salvo e conferir chuva e vazão mensais locais | Cobertura por variável e o que falta para o intervalo escolhido |
| Escolher **Preparar dados faltantes** | Buscar somente as variáveis necessárias. Usar o cache MERGE para chuva de bacia e a conexão SQL delegada para vazão | Fontes, intervalos e avanço por variável. Ao concluir, revisar o período e executar |
| Escolher **Calibrar e salvar** | Carregar os Parquets e rodar o otimizador | Andamento e resultado identificado no histórico |

Assim a consulta habitual é imediata e uma busca demorada tem uma causa visível. Abrir o diálogo, editar um mês ou navegar entre estações não dispara SQL nem download de chuva. O preparo é uma ação distinta da calibração e pode deixar dados mensais disponíveis para a próxima visita.

As rotas atuais de preparo substituem um Parquet inteiro por variável. Para ampliar a cobertura, mostrar o intervalo final que será gravado e pedir confirmação quando já houver arquivo compartilhado. Preparar em pasta temporária, conservar a série anterior fora do intervalo solicitado, verificar a junção e publicar o arquivo completo por substituição atômica. Manter a origem da chuva e identificar calibrações cuja proveniência mudou. Se falhar a segunda variável, mostrar qual já foi salva e permitir repetir o preparo da restante. No mockup a preparação é simulada em memória.

## Período científico e implementação

- Usar o fluxo do notebook `nbs/Workflow/02-Optimization.ipynb` para distinguir preparo, leitura dos dados salvos, otimização e gravação. A célula de configuração atual seleciona frequência diária. Para esta janela vale o caminho mensal existente em `web/cn3s.py`, com ACT em meses de calendário. A previsão reutiliza o JSON e o histórico de chuva.
- O mês inicial é o primeiro mês dos dados usados na simulação. Recortar chuva e vazão ao mesmo intervalo inclusivo. Em CN3S.run, os primeiros W meses de chuva fornecem os antecedentes e ficam fora das métricas. Com início em janeiro, W = 3 e ACT = 0, o primeiro resultado é abril. Com ACT = 1 ele recebe a data de maio. Parear somente observações disponíveis até o fim escolhido. O aquecimento não requer buscar dados anteriores ao início.
- Exibir no diálogo o primeiro resultado possível com ACT = 0. Para o corte de treino/teste, usar as datas observadas elegíveis após o aquecimento com ACT = 0 e manter o corte fixo entre candidatos. Conferir quantos pares restaram em cada amostra com o ACT final. Arquivar início dos dados, fim, aquecimento e períodos efetivos. Na previsão, recortar o histórico na mesma origem de chuva arquivada antes de reaplicar r0. Para JSONs antigos sem origem registrada, manter o comportamento histórico e indicar essa limitação.
- Validar chuva contínua em mm/mês e parear as médias mensais de vazão em m³/s pelos meses observados. Manter lacunas de vazão como ausentes. Sinalizar meses parciais e indicar amostras insuficientes ou NSE indefinido. O resumo diário, sozinho, não garante pares mensais válidos.
- O otimizador atual inclui o mês de corte nos dois subconjuntos. Para novas calibrações, propor o corte como primeiro mês de teste, com treino estritamente anterior, e registrar a convenção no JSON. Conferir os dois resultados com um caso manual. Preservar os valores gravados das calibrações antigas e o comportamento de chamadas existentes ao introduzir a nova convenção.
- Concentrar a interface em `web/templates/cn3s_calibrar.html`, `web/static/cn3s.js` e no CSS existente. Reaproveitar o seletor compartilhado, as rotas de operações e a publicação dos artefatos. Adaptar a consulta inicial para que um arquivo de entrada ausente ou a leitura de Parquets grandes não impeça abrir o histórico. Carregar a disponibilidade detalhada ao abrir o diálogo. Descartar respostas de estações anteriores durante troca rápida. Depois de reautenticar, recuperar a operação quando possível, sem reenviar o POST automaticamente.

## Parada do SciPy e limites da busca

- **Execução curta** vem selecionada inicialmente, com até 20 gerações (editável de 1 a 20). Usar tol = 0,0001 e atol = 0. O SciPy pode convergir antes do máximo.
- **Treinar até convergência** libera a execução além das 20 gerações e permite editar tol (relativa) e atol (absoluta), com os mesmos valores iniciais. Cada candidato recebe um valor da função objetivo no treino. Esse valor, também chamado de perda, mede o desajuste que o algoritmo procura reduzir. Para PlainNSE, NSE de 0,80 dá objetivo de 0,20. Para ExtremeFlowBlend, o valor combina os erros relativos quadráticos por faixa de vazão. O SciPy compara esses valores na mesma geração. A margem permitida para seu desvio padrão é atol + tol × |média|. Por exemplo, com média 0,20, tol de 1% e atol de 0,001, a margem é 0,003. Se a média estiver próxima de zero, atol controla a escala absoluta de parada. O SciPy recebe um maxiter inteiro. Propomos 1.000 gerações como teto explícito neste modo, em linha com a chamada do notebook. Mostrar se houve convergência, esgotamento do teto ou interrupção conforme o resultado real do solver. [Documentação do SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html)
- No diálogo em tela larga, manter dados e relação treino/teste à esquerda. À direita, mostrar a tabela com os oito pares mínimo e máximo, seguida do critério de parada. Empilhar as colunas em tela estreita. Apresentar os limites, inicialmente preenchidos com CN3SParams.bounds. Usar unidades de mm para r0, meses inteiros para ACT e valores adimensionais para os demais. Validar entradas finitas, não negativas e mínimo < máximo, no formulário e no servidor. Validar as tolerâncias como finitas e não negativas. Se os novos limites excluírem o chute inicial padrão, iniciar a população com x0=None. Salvar limites, tolerâncias, modo, maxiter efetivo, gerações realizadas e motivo de parada no resultado.
- Adaptar o limite de 20 da rota web conforme o modo e enviar explicitamente as opções ao CN3SOptimizer.optimize. Reusar a atualização por geração para indicar andamento e manter o registro da operação acessível durante execuções longas. Conferir parada por tolerância e por maxiter separadamente, inclusive ao atingir o teto do modo de convergência.

## Verificação prevista para implementação

Conferir restauração da estação, histórico vazio e legado, ordenação por data com fuso, quatro métricas contra o JSON e troca rápida A → B → A. Verificar ausência de tráfego externo durante navegação, reutilização integral dos dados, preparo parcial, falha e retomada, meses invertidos, aquecimento, ACT e conjuntos de treino e teste disjuntos. Conferir continuidade da previsão com a mesma origem de chuva, navegação por teclado e uso em tela estreita.

## Registro da sessão

Revisados o fechamento da iteração Estação, o fluxo dos notebooks e os caminhos atuais de autenticação, preparo e calibração mensal. Criados o plano e o mockup autocontido para discussão. A discussão inicial definiu o fluxo antes da implementação.

No Chromium, em tela de 390 px, verificados a seleção inicial, a alternância dos resultados, o cancelamento por Escape, a estação sem histórico, o bloqueio por meses invertidos ou vazão ausente, o preparo simulado, a seleção do novo resultado e o isolamento entre estações.

Na revisão, o início passou a definir a origem dos dados e o diálogo passou a expor limites e tolerâncias. No Chromium, a 390 e 1280 px, foram verificados o primeiro mês simulado, o bloqueio de período curto, os dois modos de parada, a rejeição de tolerância negativa, de mínimo igual ao máximo e de ACT fracionário, a aplicação de limites ao resultado ilustrativo e a restauração dos padrões ao reabrir.

O mockup passou a apresentar as duas porcentagens da divisão cronológica, os limites em coluna lateral e a explicação de convergência com um exemplo de cada função objetivo.

## Registro da implementação

A janela web consulta o catálogo local na seleção da estação e carrega a disponibilidade mensal ao abrir o diálogo. O formulário usa a relação treino/teste em incrementos de 5 pontos percentuais tanto na interface quanto na validação do servidor. As novas execuções registram origem do histórico, aquecimento, corte de treino/teste, períodos efetivos, quantidade de pares, limites, tolerâncias e motivo de parada. A previsão aplica a mesma origem de chuva. O preparo explícito preserva os meses fora do intervalo atualizado e registra os meses consultados sem vazão como ausentes.

O login usa MSAL com o mesmo cliente público institucionalmente autenticado pelo fluxo de dispositivo. Cada sessão tem seu próprio cache de tokens no servidor. A validade por inatividade é configurada em SHC_SESSION_IDLE_HOURS, com padrão de 8 horas. O Compose mantém o cache em volume nomeado. A política do Entra pode exigir interação durante a renovação. A reentrada restaura a página e a estação. Trabalhos privados pertencem à sessão que os iniciou.

No Chromium foram executadas duas calibrações reais do SciPy em uma cópia temporária de Marabá, de janeiro de 2010 a dezembro de 2012, com divisão 80% / 20%. Foram verificados o corte sem sobreposição, as quatro métricas no JSON, a seleção do resultado e o gráfico. Uma execução atingiu o teto curto de uma geração. A outra, em tela de 390 px, atingiu a tolerância deliberadamente ampla para testar a parada por convergência. Verificada a preservação de meses externos durante uma atualização parcial de vazão, inclusive intervalos sem observações nas extremidades.

Com respostas controladas da Microsoft foram verificados isolamento entre contas, expiração do token, renovação silenciosa, erro transitório, retorno à estação, exigência de nova autenticação e logout. O acesso interativo com conta institucional e a implantação publicada continuam sem verificação nesta sessão. Ruff completo, formatação e mypy estrito passaram nos cinco arquivos Python alterados. A sintaxe dos dois arquivos JavaScript também foi verificada.

## Exemplos propostos de chamadas

Rotas relativas ao prefixo do módulo. Os parâmetros de leitura de histórico e disponibilidade e o recorte inicial dos dados são extensões propostas. Exemplo com chuva local suficiente e vazão ausente desde janeiro de 2010.

```text
GET  stations/13710001?view=calibrations
GET  stations/13710001?view=availability
POST stations/13710001/inputs     {"series":"discharge","start":"2010-01-01","end":"2025-12-01","replace":true}
GET  operations/<id>
POST stations/13710001/calibrate  {"start":"2010-01-01","end":"2025-12-01","objective":"PlainNSE","train_ratio":0.9,"warmup_steps":3,"seed":42,"until_convergence":false,"maxiter":20,"tol":0.0001,"atol":0,"bounds":{"act":[0,3]}}
GET  operations/<id>
GET  stations/13710001?view=calibrations
```

```python
inputs = station.get_optim_data("M")
rain = inputs.loc[start:end, "prec_mm"]
observed = inputs.loc[start:end, "q_m3s"]
model.params.bounds["act"] = (0, 3)
optim = CN3SOptimizer(rain, observed, model, train_ratio=0.9, objective=Objectives.PlainNSE,
                      disjoint_split=True)
maxiter = 1000 if until_convergence else requested_maxiter
optim.optimize(maxiter=maxiter, tol=tol, atol=atol, workers=1, popsize=5, seed=42,
               x0=None, polish=False)
optim.save(destination)
```
