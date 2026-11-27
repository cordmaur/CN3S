# Estações e desempenho do SHC

**Status** — catálogo de estações implementado em `/shc/estacoes` e mockup ajustado nesta pasta. Medições com o banco institucional ficam pendentes.

## Entrega desta sessão

A navegação do SHC oferece **Estações** antes de **Curvas de Permanência**. A ficha da estação selecionada mostra **Série disponível** quando encontra os Parquets de uma revisão completa e **Sem série disponível** antes da primeira carga. O cabeçalho informa a última atualização bem-sucedida em horário de São Paulo e a última observação de qualquer fonte ou variável. O quadro de estatísticas e os gráficos Plotly de cota e vazão preservam os códigos e fontes individuais.

**Atualizar observações** consulta o histórico inteiro da estação, com a credencial do visitante e sem filtro de datas ou reaproveitamento de resultados SQL. As consultas continuam selecionando os códigos da estação e das séries telemétricas. O período escolhido no gráfico altera apenas a visualização. Recarregar o histórico completo permite incorporar revisões de valores antigos. Uma atualização concluída é compartilhada por todos durante o dia civil de São Paulo.

O diretório configurável `SHC_STATIONS_DIR` usa por padrão `/data/CN3S/estacoes`. O Compose fornece o volume persistente `shc-estacoes`. Cada estação mantém `Hydrology/Hidro.parquet`, `Hydrology/Telemetria.parquet`, `Hydrology/stats.parquet` e `Hydrology/metadata.json`. O JSON guarda o nome e a última atualização. A atualização prepara os arquivos em um diretório temporário ao lado de Hydrology e substitui os arquivos sob o bloqueio do catálogo e grava o JSON por último. Solicitações concorrentes compartilham o trabalho no processo único de Gunicorn.

O botão **Cadastrar estação** valida o código ANA no inventário Hidro. A carga das séries é iniciada pelo botão **Atualizar observações**. A lixeira retira a estação do catálogo após confirmação e apaga seus arquivos em Hydrology. Se houver uma atualização em andamento para aquele código, a exclusão pode ser repetida após o término.

O diálogo compartilhado de progresso é usado no cadastro e na atualização. Durante a atualização, as mensagens registram a consulta, a preparação das séries e a gravação. A barra acompanha as etapas concluídas. No cadastro, a barra fica indeterminada enquanto o inventário é consultado.

## Onde o compartilhamento deve acontecer

O cache atual reaproveita resultados de SQL pela credencial, banco, consulta e argumentos. Mesmo para uma única credencial, a consulta completa e a consulta dos últimos três anos usam chaves distintas. Adotar a base ANA pública, conforme informado, como fonte de observações compartilhadas. A revisão persistida da série passa a ser a unidade de reaproveitamento, identificada pelo código ANA, fonte, código de série e variável. A janela pedida serve para selecionar datas do arquivo. O cache de consultas atual continua atendendo o fluxo legado durante a transição. [Conector web](../../../src/utils/user_sql_connector.py#L21)

`Station` pode passar a carregar a ficha e as séries de `hydrology/` por um caminho explícito de leitura local, assim que houver um consumidor real. A primeira tela pode exercitar a leitura de uma série com uma função simples. No passo seguinte, reusar essa leitura em `Station`, preservando os construtores atuais para o código em uso. A instância pode ser reutilizada dentro de uma mesma operação. Entre módulos e requisições, compartilhar a revisão no disco: hoje `load_series()` substitui a janela, `calc_stats()` atualiza as estatísticas, e a estação guarda correções e um conector. Uma instância global faria uma edição e uma previsão disputarem esse estado. Se a leitura local ainda pesar após medição, avaliar um cache em memória dos dados publicados, por revisão. [Station e suas séries](../../../src/hydro/station.py#L415)

## Telemetria diária do Datamart

As séries de cota e vazão passam a usar `datamart.hidroinfoana_cotas_media_diaria` e `datamart.hidroinfoana_vazoes_media_diaria` como fonte de referência. O SQL autenticado confirmou `HORESTACAO`, `DATE`, `AVG_HORNIVELADOTADO` e `AVG_HORVAZAO`. A leitura usa os valores diários fornecidos pelo banco e mantém o código e a origem telemétrica. A atualização da ficha pede todo o histórico. O leitor compartilhado também aceita datas inicial e final para os chamadores que pedem um recorte. [Leitor de Telemetria](../../../src/hydro/telemetria.py#L100)

A atualização registra o inventário, a consulta e o resultado de cada combinação de variável, fonte e código da série. O log mostra horários de São Paulo, quantidade de registros e intervalo das observações, além das etapas de cálculo de estatísticas e gravação. A caixa mostra cerca de seis linhas e permite rolar para revisar o histórico. Ao concluir, o botão **Ver dados** fecha o diálogo e atualiza a ficha. Uma série gravada pelo leitor anterior pode ser atualizada para o Datamart no mesmo dia.

## Migração em passos separados

1. **Curvas de Permanência, abertura do gráfico.** Aproveitar o piloto de cota diária para uma estação. Hoje, abrir o gráfico carrega referências históricas e cotas recentes e gera PNG e Plotly antes da resposta. Medir o ganho da leitura local primeiro. Se a geração pesar, preparar o formato selecionado e gerar o outro sob demanda. [Abertura atual](../../../web/permanencia.py#L417)
2. **Curvas de Permanência, edição.** Abrir a edição com a configuração e as estatísticas salvas. Hoje essa ação consulta o histórico de cota e vazão. Carregar o histórico completo quando for necessário para recalcular e comparar os resultados e a cobertura por fonte antes de trocar a leitura. Preservar as regras de prioridade Hidro/Telemetria e as correções específicas da curva. [Edição atual](../../../web/permanencia.py#L483)
3. **CN3S, previsão.** Depois de publicar vazão diária com cobertura adequada, usar a mesma base por estação para a comparação observada. Preservar o corte na data de referência, as estatísticas, os CSVs e a ancoragem. Medir essa etapa separadamente da chuva MERGE/CDS, da simulação e dos gráficos. Hoje a comparação reabre a geometria e consulta a vazão diária depois da simulação. Manter o fluxo atual para estações e períodos ainda fora da base migrada. [Comparação observada](../../../web/cn3s.py#L412)
4. **Demais produtos.** Expandir o catálogo por código ANA e reunir `exceedance/`, `geo/` e `cn3s/` por estação quando cada consumidor estiver pronto. A curva inteira, a referência sazonal de 365 dias e a observação por data são produtos distintos. Reutilizar curvas calculadas só depois de verificar equivalência de variável, período, fonte, correções e convenção de quantis. Durante a migração, cada produto tem uma fonte de gravação, e cada módulo pode voltar à leitura legada antes da transferência dessa gravação. [Curvas de permanência](../../../src/hydro/exceedance.py#L54) · [Estatísticas do CN3S](../../../src/hydro/inference.py#L190)

A primeira entrega usa apenas `/shc/estacoes`. `/shc/novo` fica como opção se houver necessidade de homologar vários módulos juntos, e `/shc/antigo` só entra em discussão quando houver uma troca das URLs principais.

## Medidas e limites da investigação

A inspeção anterior encontrou Lábrea e Beruri nos dois diretórios de dados, e Marabá no CN3S. O piloto começa com Lábrea e expande para Beruri (`13990000`) e Marabá (`29050000`) quando for necessário testar paridade ou ausência de produto. Foram inspecionados código, caminhos e esquemas de amostras Parquet locais. As tabelas diárias da TI foram identificadas pela captura fornecida. Ainda serão medidos os tempos com SQL e no navegador, com contagem de consultas e separação entre leitura e renderização. Como referência inicial, buscar p95 de até 1 s para abrir a ficha e até 2 s para ver o primeiro gráfico a partir de dados publicados. Ajustar as metas após a medição de base.

## Validação da ficha

O [mockup navegável](estacoes.html) integra esta mesma iteração. A tela reproduz as duas linhas de Lábrea extraídas do arquivo station_stats.parquet disponível em Exceedance. Mostra dois gráficos Plotly, cada um com séries separadas de Hidro e Telemetria/RHN. Os valores diários e a atualização são simulados. A tabela reproduz a revisão persistida e tem período próprio. O HTML usa o Plotly distribuído no repositório.

Verificação no Chromium offline: duas linhas na tabela, duas fontes em cada gráfico, troca de período, recuperação da tela após carga simulada e layout móvel de 390 px.

## Exemplo de uso previsto

A equipe abre `/shc/estacoes`, seleciona Lábrea e alterna entre o histórico inteiro e os últimos três anos. Ao clicar em **Atualizar observações**, acompanha a carga diária. Outro usuário abre a mesma estação e vê a revisão publicada. A atualização usa `POST /shc/estacoes/13870000/atualizar` e o acompanhamento usa `GET /shc/estacoes/13870000/status`.


## Verificação da implementação

O Chromium exercitou a ficha Flask com respostas SQL substituídas, processamento real dos leitores Hidro e Telemetria e gravação real de Parquets em diretório temporário. Foram verificadas a ausência inicial, a primeira carga, duas fontes em cada gráfico, duas linhas de estatísticas e a troca do período. Duas sessões acionaram a mesma carga. Uma nova instância Flask reutilizou os arquivos. Uma falha preservou a revisão anterior e uma carga posterior incorporou a correção de uma observação de 1990. O custo do histórico real e a equivalência das novas tabelas diárias da TI continuam pendentes de verificação com SQL autenticado.

Ruff passou nos dois arquivos Python alterados. O mypy registrou o erro preexistente no retorno de login.require_login() em web/app.py e um aviso de opção incompatível com a versão instalada.


Verificação dos ajustes do catálogo no Chromium com uma cópia da revisão local de Lábrea e respostas SQL simuladas para o cadastro e a carga de Beruri. Foram exercitados a migração dos arquivos, o código inexistente, as etapas do diálogo, o bloqueio de exclusão durante a carga, os dois gráficos, os quatro arquivos de Hydrology, o cancelamento e a confirmação da exclusão.

## Exemplo de uso do diálogo de progresso

Inclua `progress_dialog.html` e carregue `progress_dialog.js` antes do script do módulo. Envie a lista acumulada de mensagens em cada atualização. Omita `progress` quando a duração da tarefa for indeterminada.

```javascript
const dialog = createProgressDialog(document.querySelector('.progress-dialog'));
dialog.open('Atualizar observações');
dialog.update({progress: 25, messages: ['Consultando o histórico no SQL.']});
dialog.update({
  progress: 100,
  messages: ['Consultando o histórico no SQL.', 'Observações salvas.'],
});
dialog.close();
```


## Correção de acesso no volume do Windows

Na montagem do Windows, Hydrology e hydrology identificam a mesma pasta. A tentativa anterior de renomear essa pasta para criar um backup falhava com erro de permissão. A instalação agora mantém a pasta e substitui seus arquivos individualmente, com restauração dos arquivos anteriores em caso de erro de escrita. Se a migração falhar, Estações abre a última revisão de Lábrea em modo de consulta e mostra o motivo. O cartão da página inicial usa uma régua linimétrica como ícone.

Uma cópia da revisão real de Lábrea foi migrada no mesmo volume Windows. No Chromium foi possível abrir a ficha, cadastrar outra estação com SQL simulado, carregar os arquivos planos e excluir a estação de teste. Um teste Flask injetou erro de permissão durante a substituição de stats.parquet e confirmou que a ficha abriu com os dados antigos e que a tentativa seguinte migrou os arquivos. O ícone foi conferido no HTML da página inicial. O Ruff passou para o arquivo Python alterado.


## Recriação do cadastro de Lábrea

Removido o fluxo de migração e a leitura de revisões datadas. O diretório de Lábrea foi apagado do volume do catálogo. A exclusão do último Parquet da subpasta datada funcionou após nova tentativa. O catálogo considera apenas o JSON e os Parquets diretamente em Hydrology. O cadastro começa com o JSON e a primeira atualização constrói as séries. O carregamento de Plotly e do diálogo de progresso é independente dos controles de cadastro.

Verificado no Chromium no mesmo volume, com catálogo temporário vazio e uma cópia das séries reais de Lábrea com mais de 61 mil registros em substituição ao SQL. O cadastro, a primeira gravação e os dois gráficos funcionaram. Ao bloquear as bibliotecas de gráfico e de progresso, o formulário de cadastro continuou abrindo e a ficha mostrou o erro dos gráficos. O Ruff passou no arquivo Python alterado.

## Abertura dos gráficos de Lábrea

A ficha de Lábrea continha aproximadamente 1,57 MB de HTML com todo o histórico em JSON. A ficha agora entrega a tabela e os metadados. Os gráficos buscam apenas o período selecionado em `GET /shc/estacoes/13870000/series?years=3`. Os links de cota e vazão em PNG ficam disponíveis durante o carregamento e em caso de erro do Plotly, dos dados ou do JavaScript. A atualização das observações continua consultando o histórico integral.

A verificação local no Chromium usou os Parquets atuais de Lábrea e autenticação substituída. A ficha enviou 6.374 bytes, e o recorte padrão trouxe 4.105 pontos em 96.141 bytes de JSON. Foram conferidos os dois gráficos, a troca para o histórico completo, a mensagem ao bloquear Plotly ou interromper a resposta de dados e os dois PNGs. Os recursos JavaScript servidos pelo IIS foram comparados com as cópias locais. O erro no navegador do usuário não foi reproduzido no Chromium local. Ruff passou no Python alterado e o mypy informou que a opção strict_equality_for_none da configuração não é reconhecida pela versão instalada, sem erros no módulo.

## Plotly com o histórico completo

O aviso anterior era genérico e podia indicar uma falha no carregamento da biblioteca, na requisição dos dados ou no desenho do gráfico. A ficha agora inclui a série completa diretamente e abre os dois gráficos Plotly nesse período. Os outros recortes alteram apenas o eixo no navegador. A resposta de Lábrea usa cerca de 341 KB com gzip. A ficha indica falhas de download e inicialização da biblioteca e sinaliza falhas de renderização no gráfico correspondente.

O Chromium renderizou 61.617 posições, incluindo marcadores de lacunas, com os Parquets atuais de Lábrea. Foram conferidos o recorte, o retorno ao histórico completo e o aviso específico ao bloquear o Plotly. A verificação foi feita no Flask local e usando os recursos estáticos servidos pelo IIS com o documento autenticado substituído no teste. A causa específica do aviso no navegador do usuário permanece desconhecida. Ruff passou no módulo alterado.

### Verificação do Datamart e do diálogo

O Chromium acompanhou uma atualização completa de Lábrea com SQL autenticado e gravação em catálogo temporário. O Datamart retornou 3.241 cotas diárias e 3.175 vazões diárias, com datas entre 24/08/2005 e 26/11/2026 e sem chave diária duplicada no Parquet. O log registrou separadamente início e fim das quatro leituras, atingiu 100% e teve rolagem vertical. O botão **Ver dados** abriu a ficha atualizada e os gráficos. Uma consulta com recorte explícito de 01/11/2026 a 23/11/2026 confirmou os dois limites nas novas tabelas.

Ruff passou nos três arquivos Python alterados. A execução explícita do mypy apresentou o aviso da versão instalada sobre strict_equality_for_none e os mesmos oito apontamentos preexistentes nos leitores e na classe Station.
