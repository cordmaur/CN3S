# SHC — Sistema Hidrológico da COVEC

## Objetivo e decisões confirmadas

Planejar a primeira versão da SHC, com entrada em `/shc`, autenticação Microsoft
por código de dispositivo e o módulo **Curvas de Permanência**. **Chuvas** e
**CN3S** aparecem no menu e na página inicial como “Em breve”, sem funcionalidades
nesta entrega. O idioma da interface é português brasileiro.

O usuário confirmou:

- As estações e os limites são compartilhados entre todos os usuários autenticados.
  Nesta versão, todos eles podem inserir estações e editar limites.
- Selecionar uma estação consulta a telemetria recente usando as permissões de
  quem está conectado. A curva histórica salva permanece inalterada.
- O editor permite alterar nomes/valores, adicionar e remover limites.
- A lista deve comportar mais de mil estações, com uma linha compacta por item:
  código / nome, sem quebra de linha.
- Antes de calcular uma nova estação, consultar o histórico e mostrar station.stats;
  o usuário escolhe o método (from_discharge por padrão, ou direct) e informa
  correções pontuais opcionais.
- A aplicação existente continua funcionando enquanto o plano e o visual são revistos.

Os mockups estão em `mockup.html` e `mockup-assets/`. São uma proposta para revisão,
com navegação simulada, nove estações reais e cópias dos gráficos já salvos. Não
fazem autenticação, consultas nem gravações nos dados científicos.

## Telas e navegação

1. **Entrada:** `/shc` e `/shc/` encaminham quem não está autenticado para
   `/shc/login`; quem já está autenticado vai para `/shc/home`. O título é
   “SHC — Sistema Hidrológico da COVEC”. Login separado em `login.py` e
   `login.html`, reaproveitando o fluxo de dispositivo já validado. A confirmação
   automática leva à página inicial, não ao antigo formulário de teste.
2. **Início:** `shc_home.html` tem cabeçalho compartilhado com nome do sistema,
   identificação do usuário, botão Sair e menu Início / Curvas de Permanência /
   Chuvas / CN3S. Os cartões e itens dos dois módulos futuros ficam desabilitados,
   identificados como “Em breve”.
3. **Curvas de Permanência:** lista pesquisável à esquerda com uma linha de
   aproximadamente 33 px por estação: `14558000 / Fazenda Paraíso`. Manter código
   visível, nome com reticências quando necessário e texto completo no tooltip.
   A lista tem rolagem própria e busca por nome/código. Renderizar os primeiros
   50 resultados filtrados e oferecer “Carregar mais 50”, evitando mil elementos
   de uma vez. O painel principal mostra origem/método/período, gráfico anual e
   editor de limites. Abrir o módulo inicialmente pede seleção; não consultar
   todas as estações no banco.
4. **Inserção em duas etapas:**
   - **Consultar estação:** informar código e clicar em “Consultar estatísticas”.
     O servidor carrega o histórico completo e devolve as estatísticas, sem salvar
     curva ou cadastro. Mostrar progresso real da consulta.
   - **Revisar e calcular:** mostrar tabela de `station.stats`, agrupada em Cota e
     Vazão, com código/fonte por linha (Hidro e estações telemétricas) e Início,
     Fim, Anos, Falhas (%), Consist. (%) e Anos efetivos por variável. Escolher
     “A partir da vazão” (`from_discharge`, padrão) ou “Diretamente das cotas”
     (`direct`), adicionar correções pontuais e limites iniciais opcionais, e só
     então acionar “Calcular e inserir”. Permitir voltar e alterar o código,
     invalidando a análise e os ajustes vinculados ao código anterior.
   - Uma estação já cadastrada pode ter suas estatísticas consultadas, mas a ação
     final é “Abrir estação existente”; não recalcular ou sobrescrever o cadastro.
     As configurações de inserção ficam desabilitadas nesse caso.
   - No mockup, a tabela usa valores ilustrativos baseados na imagem do usuário,
     claramente identificados; não há consulta real. Para experimentar a etapa
     de cálculo, informar um código ainda ausente da lista, por exemplo 14558001.
5. **Limites:** linhas com nome, cota em cm e Remover; botão Adicionar limite e
   “Salvar limites”. Alterações não salvas são indicadas. Ao mudar de estação
   com alterações, pedir confirmação para descartá-las.
6. Botão “Atualizar observações” consulta novamente as séries recentes sem
   recalcular o histórico; “Baixar PNG” entrega exatamente o gráfico exibido.
   O gráfico desta versão é uma imagem Matplotlib, sem zoom/hover interativo.

O gráfico principal é `plot_annual_stage_chart`, correspondente à imagem enviada:
faixa histórica, média, mínimos/máximos, três anos de telemetria e limites. Não é
uma curva de vazão versus probabilidade de excedência. O ano de referência é o
ano atual em America/Sao_Paulo; os meses da apresentação ficam em português.

## Organização mínima

```text
web/
  app.py                   # configuração, sessões, registro dos módulos, entrada/início
  login.py                 # Blueprint de login/logout, progresso e helpers de autenticação
  permanencia.py           # Blueprint, catálogo, operações e fluxo explícito das curvas
  templates/
    base.html              # cabeçalho e menu compartilhados
    login.html
    shc_home.html
    permanencia.html
  static/
    shc.css
    shc.js
```

Usar Blueprints apenas para separar as rotas e compartilhar uma única aplicação
Flask, configuração e sessão. Helpers usam `current_app`, evitando importar o
objeto app entre módulos. Não criar classes de serviço, frameworks de tarefas,
banco adicional nem arquivos de implementação para os módulos futuros.

`src/hydro` continua responsável pelas equações, séries e gráficos;
`src/utils/user_sql_connector.py` mantém a conexão por usuário. O `SqlConnector`
dos notebooks permanece sem alterações. CSS e JavaScript saem do HTML inline.
Configurar os arquivos estáticos em `/shc/static`, dentro do prefixo do IIS.

Referência: [Flask Blueprints](https://flask.palletsprojects.com/en/stable/blueprints/).

## Arquivos e processamento científico

**Formato real encontrado:** nove diretórios de estação em
`/data/CN3S/duration_curves`, cada um com `curve.parquet`, `stats.parquet` e
**`meta.json`**, não `metadata.json`. Os limites ficam em `thresholds`, um mapa
ordenado de nome para cota em centímetros. Há estações com um limite e outras
com três. Manter esse formato e a compatibilidade com os notebooks.

- Catálogo: ler os diretórios numéricos e seus metadados, ordenar por nome e
  código. Usar metadados locais para montar a lista; não consultar todas as
  estações no banco. Diretórios incompletos ou inconsistentes aparecem como
  indisponíveis com mensagem, sem recalculá-los silenciosamente. Não apresentar
  diretórios temporários como estações.
- Estação existente: criar `UserSqlConnector` com o token do usuário, construir
  `Station`, carregar `DurationCurveReporter.from_saved`, e buscar séries somente
  de 1º de janeiro de dois anos antes até a data atual. Esse recorte serve para
  as observações desenhadas; nunca substitui a climatologia salva. Renderizar o
  gráfico anual, informar última observação disponível e fechar o conector.
- Nova estação: a consulta inicial usa `station.load_series()` e apresenta
  `station.stats`. Essa tabela descreve observações por fonte, antes da combinação
  ou sanitização; não apresentá-la como estatística dos dados corrigidos.
- Guardar temporariamente, por sessão/análise, as séries diárias originais,
  informações telemétricas, estatísticas e código analisado; não guardar um
  conector/engine SQL no cache. Reutilizar esses dados no cálculo para evitar uma
  segunda carga completa das séries. Uma análise expirada exige nova consulta.
  Ao reconstruir Station para calcular, usar um conector novo do usuário e
  restaurar explicitamente as séries e estatísticas analisadas.
- Calcular com `series_type="cota"`, `source=None`, `method=selected_method` e
  `period=slice(None, None)`, após associar a sanitização escolhida à Station.
  O usuário escolhe o método a partir dos dados analisados; a fonte continua
  usando a seleção existente. O usuário confirmou que a troca automática atual
  para cotas diretas deve ser preservada quando a série de vazão ou a curva-chave
  impedirem o método solicitado. Exibir o método solicitado e o efetivamente
  utilizado; não apresentar um fallback como se a conversão por vazão tivesse
  sido aplicada.
- Salvar curva, estatísticas e metadados no formato compatível. Publicar o novo
  diretório somente depois de os arquivos obrigatórios estarem completos;
  falhas não deixam uma estação válida na lista.
- Corrigir pontualmente os caminhos de `create_duration_curve` que ainda
  desempacotam `Station.get_series()` como tupla, embora ele retorne DataFrame;
  calcular as estatísticas explicitamente. Tratar ausência de séries e divisão
  por zero quando só há vazão. Manter heurísticas e conversão da curva-chave;
  informar o método efetivamente utilizado. Não refatorar métodos não utilizados.
- Sem telemetria recente: apresentar apenas a referência histórica e os limites,
  com aviso explícito, sem inventar observações. Adicionar ao método de gráfico
  anual a opção `allow_missing_telemetry=False`; a SHC passa True e os notebooks
  conservam o comportamento atual por padrão. Se faltar telemetria, desenhar a
  referência normalmente e identificar essa ausência no gráfico.
- Sanitização: formato atual `dict[SeriesType, dict[str, float]]`, por exemplo
  `{"cota": {"2025-06-15": 439.0}, "vazao": {"2025-06-16": 1250.0}}`.
  A interface mostra linhas Variável / Data / Valor substituto / Remover, com
  Cota em cm e Vazão em m³/s. Os valores substituem observações existentes na
  série final após a combinação das fontes, sem alterar SQL ou dados brutos.
  Não adicionar exclusão de dias, preenchimento de lacunas ou filtros genéricos.
  Exigir valores finitos, datas ISO e unicidade por variável/data. Na análise
  real, avisar se uma correção não corresponde a uma data existente na série
  usada, em vez de deixá-la ser ignorada sem indicação. Mudança de variável
  atualiza a unidade exibida.
- Persistir `sanitization` e `requested_method` como campos opcionais nos resultados
  e em `meta.json`, com valores padrão para carregar os arquivos existentes.
  Estender apenas DurationCurveResult/save/load para esses campos. Preservar
  `method` como método efetivamente utilizado. A SHC reaplica a sanitização salva
  ao construir a Station para reabrir/atualizar a telemetria. Salvar limites não
  apaga essas configurações. Este plano não adiciona edição de sanitização ou
  recálculo de estações já cadastradas.
- Limites: não derivar automaticamente um nível do nome “Permanência 95%”. Os
  valores são referências informadas pelo usuário, como no notebook. Aceitar
  cotas finitas, inclusive negativas; nomes devem ser não vazios e distintos.
  A lista pode ficar vazia. Validar antes de converter as linhas em dicionário.
- Salvar limites altera somente `thresholds` em `meta.json`, preservando os demais
  campos, `curve.parquet` e `stats.parquet`. Escrever em arquivo temporário e
  substituir atomicamente. Comparar a revisão do metadado carregado antes de
  gravar; se outra pessoa já salvou, pedir recarga em vez de sobrescrever.
- Após salvar, renderizar o gráfico com os novos limites. Se a consulta/renderização
  falhar depois da gravação, informar separadamente que os limites foram salvos e
  o gráfico não foi atualizado; não mostrar silenciosamente uma imagem antiga
  como se contivesse os novos limites.

## Rotas, operações e implantação

| Método e rota | Responsabilidade |
|---|---|
| GET `/shc`, `/shc/` | Encaminhar para entrada ou início |
| GET `/shc/login` | Página de autenticação |
| POST `/shc/login` | Iniciar código de dispositivo |
| GET `/shc/login/status` | Progresso público da própria autenticação |
| POST `/shc/logout` | Encerrar a própria sessão |
| GET `/shc/home` | Início autenticado |
| GET `/shc/permanencia` | Página e catálogo das estações |
| POST `/shc/permanencia/estacoes/analisar` | Consultar histórico e estatísticas, sem salvar |
| POST `/shc/permanencia/estacoes` | Calcular com análise/método/correções, ou abrir existente |
| POST `/shc/permanencia/estacoes/<codigo>/atualizar` | Selecionar/recarregar e gerar gráfico |
| POST `/shc/permanencia/estacoes/<codigo>/limites` | Atualizar limites compartilhados |
| GET `/shc/permanencia/operacoes/<id>` | Estado/resultado da própria operação |
| GET `/shc/permanencia/graficos/<id>.png` | Exibir/baixar a própria imagem |

As leituras demoradas e cálculos rodam em threads de fundo, com estado simples
no cache do servidor, seguindo o mecanismo já utilizado no login. O navegador
consulta o progresso sem manter uma requisição HTTP aberta por vários minutos.
Sem Celery, Redis ou serviço separado. Permitir uma operação ativa por sessão;
retornar fases reais (consultando séries, preparando estatísticas, calculando,
salvando, renderizando), sem
percentuais fictícios. Resultados temporários expiram após 30 minutos e não são
armazenados dentro da pasta científica. Uma falha permite tentar novamente.

Nesta implantação haverá um único container e um worker Gunicorn explícito.
Usar locks por estação para publicar resultados/gravar metadados, e um lock
curto ao renderizar Matplotlib; não serializar consultas SQL de estações distintas.
Cada trabalho recebe o token e identificador da sessão no início e cria/fecha
seu próprio conector. Não passar `session` ou contexto de requisição à thread.
Gráficos e operações são acessíveis apenas à sessão que os gerou; arquivos
científicos compartilhados não ficam expostos como diretório estático público.
POSTs validam o token anti-CSRF. Falta/expiração de login pede nova entrada, sem
expor tokens ou retornar páginas de login como imagens.

- Migrar cookie e suas rotas para `/shc`. A interface inteira exige autenticação,
  salvo entrada/progresso da própria entrada e recursos visuais. Preservar a
  ausência de cache HTTP para conteúdo por usuário.
- IIS: regra `^shc(?:/.*)?$` e destino `http://127.0.0.1:8000/{R:0}` em
  desenvolvimento; usar 18000 no destino da versão implantada. A página raiz
  do IIS permanece disponível para um futuro índice de aplicações.
- Montar a pasta real de curvas do host em `/data/CN3S/duration_curves` com
  leitura/escrita e existência obrigatória. Não criar um diretório vazio no host
  por erro de caminho. Configuração `SHC_DURATION_CURVES_DIR` tem esse caminho
  interno como padrão; Compose exige o caminho externo em `SHC_DURATION_CURVES_HOST_DIR`.
- Incluir pyarrow nas dependências web e copiar templates/static/módulos novos
  na imagem. Não embutir dados ou credenciais durante o build.
- Desenvolvimento continua com Gunicorn --reload e VS Code port forwarding.
  Reconstruir a imagem apenas para publicar mudanças/dependências. O runtime
  Docker Desktop e suas limitações de boot/logoff já documentadas permanecem
  fora desta entrega funcional; não afirmar inicialização autônoma após reboot.

## Validação e critérios de aceite

Usar verificações temporárias representativas, sem criar uma suíte formal.

- `/shc` leva a login ou home conforme o estado; os três módulos aparecem, mas
  somente Curvas de Permanência está ativo. Conteúdo, estados e erros em pt-BR.
- Comparar os nove arquivos reais: catálogo, nomes, códigos e limites corretos;
  selecionar Fazenda Paraíso e Boa Vista exercita um e três limites.
- Verificar com duas sessões Microsoft distintas: consultas usam o token correto,
  operações/imagens não se cruzam, e as edições compartilhadas aparecem ao recarregar.
- Ao abrir/atualizar uma estação existente, os hashes de curva e estatísticas
  permanecem idênticos; telemetria recente é consultada novamente.
- Salvar limites preserva os outros campos do JSON e os Parquets. Exercitar
  valor decimal, remoção, lista vazia, nome duplicado e conflito entre duas edições.
- Catálogo com mais de mil metadados: itens em uma linha, rolagem contida,
  pesquisa por código/nome e lotes de 50 sem milhares de nós DOM simultâneos.
- A consulta de estatísticas não cria diretório de estação. A tabela mantém
  separadas as fontes Hidro/Telemetria e as métricas de cota/vazão.
- Método padrão from_discharge e escolha de direct enviados corretamente ao
  cálculo. Código alterado invalida a análise anterior. Análise reaproveitada
  não desencadeia outra carga completa das séries.
- Correções com cota e vazão, decimal e data existente alteram somente o valor
  correspondente após combinação; dados originais e station.stats permanecem
  originais. Exercitar duplicidade por variável/data e data não encontrada.
- Sanitização e método solicitado são reabertos dos metadados; arquivos antigos
  sem esses campos continuam funcionando. Edição de limites preserva ambos.
- Inserção válida produz os três arquivos obrigatórios e inclui a estação na
  lista. Código repetido apenas abre a existente; código inválido/inexistente,
  acesso negado e falha de cálculo exibem mensagem sem diretório parcial.
- Comparar PNG e valores históricos com o notebook para a mesma entrada,
  referência anual e observações. Verificar ano bissexto, ausência de telemetria,
  ausência de cota, fallback para cota direta e ausência de dados utilizáveis.
- Confirmar leitura/escrita no bind mount, persistência após recriar o container,
  e acesso pelo Mac via IIS. Conferir a versão de desenvolvimento com reload.

Plano e mockup aprovados pelo usuário; implementação da primeira versão concluída no checkout. A validação ao vivo no IIS/SQL do servidor permanece necessária.

## Implementação e verificações

- Aplicação migrada para `/shc`, com `app.py`, `login.py` e `permanencia.py`,
  templates separados e CSS/JavaScript externos. Rotas e template antigos do
  teste cn3s-test removidos; a documentação indica a nova regra do IIS.
- Implementados catálogo compacto, consulta de estatísticas, revisão de método,
  correções e limites, cálculo em segundo plano, PNG privado, atualização de
  telemetria e salvamento atômico dos limites compartilhados.
- Metadados antigos continuam carregando. Os novos persistem sanitization e
  requested_method. Corrigidos somente os caminhos necessários do cálculo e
  adicionada a opção explícita de gráfico sem telemetria, preservando o padrão
  dos notebooks. O SqlConnector original não foi alterado.
- Cache de análises guarda os dados diários, nunca o engine SQL. Imagens e
  operações pertencem à sessão. Recarregar o worker interrompe a tarefa e uma
  identificação do processo permite apresentar erro e liberar nova tentativa.
- Compose exige o caminho da pasta científica no host e usa bind mount sem
  criação automática da origem; Dockerfile inclui os módulos novos, recursos
  estáticos, pyarrow e um único worker.
- Verificações temporárias com leitor SQL e credenciais simulados passaram:
  login/logout, cookie /shc, duas identidades, isolamento de operações e imagens,
  CSRF e expiração; consulta de estatísticas antes de salvar; criação pelos dois
  métodos; reaproveitamento do histórico analisado; correção persistida e rejeição
  de data ausente; salvamento de limites sem mudar hashes dos Parquets; conflito
  entre edições; leitura dos nove resultados antigos; catálogo com 1.005 estações
  e entrada incompleta; falta de telemetria; ano bissexto; vazão sem cotas; fallback
  por falha de curva-chave respeitando o período; operação interrompida por reload.
- Python compilou, JavaScript passou no Node --check e verificações Ruff F/E9/D213
  dos módulos web passaram. HTML renderizado tem IDs únicos. Um Gunicorn local
  respondeu à entrada, login e CSS/JS; cn3s-test respondeu 404.
- Não foi criada suíte formal de testes. Nenhuma estação científica real foi
  modificada durante as verificações: gravações ocorreram em diretórios temporários.
- Não há Docker CLI nem navegador automatizado neste devcontainer: build da imagem,
  revisão visual e integração Microsoft/SQL pelo IIS precisam da execução no host.

## Registro da sessão

- Renomeados 31 diretórios anteriores para o padrão data primeiro; AGENTS.md
  atualizado. Esta iteração foi criada em 03/11/2026, 15:24:42, America/Sao_Paulo.
- Usuário definiu SHC como sistema principal e CN3S como um dos submódulos.
- Confirmadas as três decisões: dados/limites compartilhados, telemetria ao abrir
  estação e edição completa de limites nomeados.
- Inspecionados os nove diretórios reais, `meta.json`, Parquets, notebook e métodos
  de carregamento/plotagem. Identificada a incompatibilidade de retorno de
  get_series em caminhos da geração de curva.
- Usuário aprovou o visual geral e pediu lista compacta para mais de mil estações,
  consulta de estatísticas antes da inserção, escolha de método e sanitização.
- Inspecionado o formato DataSanitization e confirmado que station.stats descreve
  fontes originais antes da aplicação das correções em get_series.
- Mockup atualizado no mesmo arquivo, com lista código/nome em uma linha,
  tabela de estatísticas ilustrativas, seleção de método e editor de correções.
- Usuário confirmou preservar o fallback automático para cotas diretas, com
  indicação do método realmente aplicado. O texto do seletor informa essa regra.
- Conferidos IDs únicos, duas etapas do diálogo, tabela agrupada, método padrão,
  editor de correções e paginação de 50 itens. JavaScript passou na verificação
  sintática do Node disponível no VS Code; revisão visual permanece com o usuário.
- Criado protótipo HTML local com entrada, início, módulo de curvas e inserção,
  usando cópias das imagens existentes. Nenhum arquivo científico nem a aplicação
  em funcionamento foi alterado neste planejamento.
- Conferidos estrutura HTML, IDs únicos e metadados das nove estações; as cópias
  dos nove gráficos são idênticas aos originais. HTML e imagem responderam HTTP
  200 em uma verificação temporária. Não havia navegador automatizado disponível
  neste ambiente; a revisão visual/interativa será feita pelo usuário.

Para abrir a prévia sem alterar a aplicação, executar no devcontainer:

```bash
python -m http.server 8001 --directory agents/iterations/2026-11-03_15-24-42_iis-flask-version-1
```

Encaminhar a porta 8001 no VS Code e abrir `http://localhost:8001/mockup.html`
no navegador do Windows. A barra da prévia alterna Entrada, Início e Curvas.

## Exemplos propostos de chamadas

```python
# Estação existente: manter a climatologia e recarregar apenas os anos exibidos.
conn = UserSqlConnector(access_token)
try:
    station = Station(14558000, connector=conn)
    reporter = DurationCurveReporter.from_saved(results_dir / str(station.code), station)
    station.load_series(start=f"{reference_year - 2}-01-01", end=today.isoformat())
    fig = Figure(figsize=(14, 7))
    ax = fig.subplots()
    reporter.plot_annual_stage_chart(
        ax, ref_year=reference_year, allow_missing_telemetry=True,
    )
finally:
    conn.close()
```

```python
# Nova estação: processar o histórico completo e salvar no formato existente.
conn = UserSqlConnector(access_token)
try:
    sanitization = {"cota": {"2025-06-15": 439.0}}
    station = Station(station_code, sanitization=sanitization, connector=conn)
    station.load_series()
    # Mostrar station.stats; depois da decisão do usuário, reutilizar estas séries.
    reporter = DurationCurveReporter(station, thresholds=initial_thresholds)
    reporter.create_duration_curve(
        series_type="cota", source=None, method=selected_method, period=slice(None, None),
    )
    # staging_root pertence ao mesmo filesystem da pasta definitiva.
    reporter.save_results(staging_root)
    # A implementação publica staging_root/<codigo> somente após sucesso.
finally:
    conn.close()
```
