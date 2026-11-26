# Progresso e revisão da calibração CN3S

O [mockup](mockup.html) apresenta a calibração como seção da página principal. Os dados, a evolução do otimizador e o histórico são simulados. As duas figuras usam o Plotly distribuído no repositório. Beruri começa sem as duas séries mensais para demonstrar o preparo. Marabá abre com séries prontas para demonstrar a execução direta.

## Fluxo proposto

- Abrir no histórico. Selecionar automaticamente a calibração mais recente disponível e exibir sua revisão com métricas, parâmetros e gráfico. Oferecer **Apagar calibração** com confirmação. Na aplicação, remover somente o artefato selecionado e autorizado. No protótipo, editar o histórico em memória.
- Em **Nova calibração**, ocultar o histórico e mostrar o formulário. Ao salvar, voltar ao histórico com o novo resultado selecionado. Ao descartar ou cancelar, voltar ao histórico da estação. Se ele estiver vazio, ocultar a revisão.
- **Atualizar dados** recria o gráfico com os Parquets atuais, os parâmetros salvos e o intervalo registrado. A ação é de leitura e mantém as métricas originais identificadas na revisão. Calibrações antigas sem gráfico são apresentadas por simulação a partir das séries mensais disponíveis.

1. Organizar período, função objetivo e cobertura à esquerda. À direita, mostrar os limites dos parâmetros com divisor vertical. Em tela estreita, empilhar os grupos. Recolher estatísticas diárias e opções do otimizador para reduzir a altura inicial. Sugerir o mês anterior ao atual como fim, com edição livre.
2. Em **Preparar dados faltantes**, mostrar a chuva MERGE ou a vazão SQL em processamento e manter a barra visível na própria seção. Usar etapas concluídas por fonte. Quando o backend não informar unidades concluídas dentro de uma fonte, indicar atividade indeterminada nessa etapa.
3. Em **Calibrar**, mostrar a fase de inicialização e publicar, por geração, o melhor valor do objetivo de treino e o vetor correspondente. Exibir a curva acumulada e distinguir o limite de gerações da parada por tolerância. A execução com convergência usa um indicador de atividade enquanto durar. A página acompanha o trabalho na seção, que tem espaço para o gráfico e a linha dos oito parâmetros.
4. Ao terminar, apresentar métricas de treino e teste e a figura interativa em Plotly. Dedicar cerca de 60% da área útil à vazão (observada e simulada, em m³/s) e 40% à chuva (mm/mês), com um pequeno espaço entre os painéis, e usar eixo de datas compartilhado. Mostrar a divisão treino/teste. A figura proposta mede 740 px no total.
5. **Salvar calibração** publica o resultado da execução que o usuário está revisando e seleciona o novo arquivo no histórico. **Descartar resultado** retorna à preparação. Na aplicação, a execução concluída deve manter suas métricas, parâmetros, proveniência e gráfico em um artefato temporário da sessão até essa decisão. Reaproveitar o acompanhamento e a autorização das operações existentes. Tornar a publicação resistente a clique repetido e indicar eventual expiração do artefato.

## Registro da sessão

Em Chromium, a 1468 e 390 px, foram verificados o mês final, o divisor em desktop e o empilhamento em tela estreita, as duas etapas de preparo, a evolução por geração, a figura de 740 px e a inclusão no histórico após salvar. O resultado também pode ser descartado.

Na revisão seguinte, o Chromium confirmou a abertura no histórico, a revisão sem ação de salvar para resultados já persistidos, a volta ao histórico após descartar ou salvar e a confirmação de exclusão, inclusive ao apagar a última calibração.

## Registro da implementação

A seção de calibração agora separa preparo dos dados, acompanhamento do treino e revisão. O progresso do preparo identifica a fonte e conta as etapas concluídas. O callback do SciPy fornece ao navegador a curva do melhor objetivo de treino e os últimos parâmetros. O resultado final usa painéis Plotly com eixo de datas compartilhado. A precipitação é exibida na data original e a vazão segue as datas deslocadas pelo ACT.

Salvar publica o JSON com o gráfico correspondente. Descartar elimina o resultado privado pendente. A revisão de uma calibração salva permite recuperar o gráfico com dados mensais locais atualizados e apagar a calibração do disco após confirmação. O gráfico recalculado usa o mesmo período e os mesmos parâmetros, e as métricas exibidas continuam sendo as registradas no arquivo.

A verificação em Chromium usou cópias temporárias de Marabá e executou o SciPy. Foram exercitados o preparo por fonte com respostas controladas, progresso por geração, revisão de arquivos anteriores, atualização do gráfico, recarga da página antes de salvar, publicação, descarte e exclusão. O ambiente publicado e o acesso às fontes externas não foram exercitados. Ruff completo, formatação, mypy estrito e sintaxe do JavaScript passaram.

## Exemplos propostos de chamadas

```text
POST stations/13990000/inputs      {"series":"rain","start":"2014-01-01","end":"2026-10-01","replace":true}
GET  operations/<preparo>         → etapa de chuva MERGE
POST stations/13990000/inputs      {"series":"discharge","start":"2014-01-01","end":"2026-10-01","replace":true}
GET  operations/<preparo>         → etapa de vazão SQL
POST stations/13990000/calibrate  {"start":"2014-01-01","end":"2026-10-01","train_ratio":0.9,"maxiter":20}
GET  operations/<treino>          → gerações ou resumo e gráfico para revisão
POST operations/<treino>/save     → publicar calibração revisada
POST operations/<treino>/discard → descartar o resultado privado
GET  stations/13990000/calibrations/chart?calibration=<id>&refresh=1 → refazer o gráfico
POST stations/13990000/calibrations/delete {"calibration":"<id>"} → excluir após confirmação
```
