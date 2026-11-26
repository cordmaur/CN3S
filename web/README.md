# SHC — Sistema Hidrológico da COVEC

## Como uma requisição chega à aplicação

No desenvolvimento mostrado na configuração do IIS, o navegador acessa
`http://172.20.28.3/shc/permanencia` (HTTP, porta 80):

```text
Navegador → IIS no Windows :80 /shc/permanencia
          → URL Rewrite + ARR → 127.0.0.1:8000/shc/permanencia no Windows
          → porta do devcontainer encaminhada ao Windows pelo VS Code
          → Gunicorn :8000 no devcontainer → Flask
```

No terminal do devcontainer, na raiz do projeto, o comando usado é:

```bash
python -m gunicorn --bind 0.0.0.0:8000 web.app:app --reload
```

A porta 8000 do devcontainer precisa estar encaminhada e acessível como
`127.0.0.1:8000` no Windows. `0.0.0.0:8000` faz o Gunicorn escutar nas
interfaces do ambiente em que ele executa; isso não configura o IIS, o
encaminhamento da porta, o firewall do Windows nem o acesso pela rede. `--reload`
é destinado ao desenvolvimento e interrompe operações em andamento ao reiniciar.

No container independente descrito abaixo, o Docker publica `127.0.0.1:8000`
do host para a porta 8000 do container. **A regra do IIS não muda**
(`http://127.0.0.1:8000/{R:0}`): desenvolvimento e container usam a mesma porta
e, por isso, **não podem rodar ao mesmo tempo**. Os colegas acessam a porta 80
do IIS; não é necessário expor a porta 8000 a eles.

## Alternar entre desenvolvimento e container (Makefile)

| Comando | Onde executar | O que faz |
|---|---|---|
| `make deploy-dev` | terminal do devcontainer, raiz do projeto | Gunicorn com `--reload` em `0.0.0.0:8000` (primeiro plano) |
| `make deploy-test-build` | WSL/host com Docker, raiz do projeto | constrói a imagem local do container |
| `make deploy-test` | WSL/host com Docker, raiz do projeto | inicia a imagem local em `127.0.0.1:8000` sem reconstruir ou baixar e verifica HTTP |
| `make deploy-test-stop` | WSL/host | para o container e libera a porta 8000 |

O servidor de desenvolvimento verifica a porta no próprio devcontainer; o Docker
verifica a publicação da porta no host e informa conflitos. O encaminhamento do
VS Code e a disponibilidade da porta no Windows devem ser verificados à parte.
Para alternar com segurança: pare o atual (Ctrl+C no `deploy-dev`, ou
`make deploy-test-stop`), confirme que a porta está livre e inicie o outro. Se a
porta estiver ocupada por outro programa, descubra-o antes de encerrá-lo.
`SHC_PORT=<porta>` altera a porta usada pelo comando (só para testes locais; o
IIS continua apontando para 8000).

Caminhos: no devcontainer as curvas ficam em `/data/CN3S/Exceedance` (padrão,
`SHC_DURATION_CURVES_DIR`). No `deploy-test`, execute no host; o Makefile usa
por padrão o caminho do host correspondente ao mount configurado no devcontainer.
`SHC_DURATION_CURVES_HOST_DIR` permite substituí-lo por outro caminho **do host**.
O Makefile verifica que a pasta existe. Se a porta 8000 do
devcontainer estiver encaminhada ao Windows pelo VS Code, ela ocupa a porta no
Windows; pare o `deploy-dev` e, se necessário, remova o encaminhamento antes do
`deploy-test`.

## Desenvolvimento rápido

No terminal do devcontainer, a partir da raiz do projeto:

```bash
pip install -e '.[web]'
PYTHONPATH=src python -m gunicorn --reload --workers 1 --bind 0.0.0.0:8000 web.app:app
```

Encaminhe a porta 8000 no VS Code. Abra `http://localhost:8000/shc` no Windows,
ou use o IIS configurado abaixo para acessar pelo Mac. Alterações em Python
reiniciam o worker; atualize o navegador para HTML/CSS/JavaScript. Uma operação
interrompida pelo reload deve ser iniciada novamente. Login pendente pode ser
cancelado e reiniciado. Não reconstrua a imagem para testar cada edição.

A pasta `/data/CN3S/Exceedance` já está montada no devcontainer. Para outro
local, configure `SHC_DURATION_CURVES_DIR` antes de iniciar o servidor. A pasta
precisa existir; a SHC não cria silenciosamente uma pasta científica vazia.

## Configuração do IIS

No **Default Web Site → URL Rewrite**, substitua a antiga regra de teste por:

| Configuração | Desenvolvimento | Container implantado |
|---|---|---|
| Nome | SHC | SHC |
| Padrão | `^shc(?:/.*)?$` | `^shc(?:/.*)?$` |
| Ação | Rewrite | Rewrite |
| URL | `http://127.0.0.1:8000/{R:0}` | `http://127.0.0.1:8000/{R:0}` |

Mantenha **Append query string** e **Stop processing of subsequent rules** ativos,
e **Enable proxy** habilitado em ARR. A regra encaminha também CSS, JavaScript,
login e operações. Não é necessário reiniciar o IIS. A página `/` do IIS continua
separada e pode hospedar o índice geral de aplicações. As rotas `/cn3s-test`
foram removidas; o endereço agora é `http://172.20.28.3/shc`.

## Diagnóstico de acesso pela rede ao IIS

A regra **inbound** mostrada em URL Rewrite é uma regra de reescrita de URL,
não uma regra de entrada do firewall. Ela não informa quais IPs de clientes
podem alcançar o servidor. O fato de a URL funcionar no próprio servidor não
comprova acesso a partir de outra máquina.

1. **No computador do colega**, conectado à mesma rede corporativa ou VPN,
   execute no PowerShell:

   ```powershell
   Test-NetConnection 172.20.28.3 -Port 80
   curl.exe -v --noproxy "*" http://172.20.28.3/shc/permanencia
   ```

   `TcpTestSucceeded : True` confirma a conexão TCP à porta 80 a partir daquele
   computador, não que a página ou autenticação estejam funcionando. Qualquer
   resposta HTTP no `curl`, inclusive redirecionamento ou erro, mostra que um
   servidor HTTP respondeu; confira o status e o destino do redirecionamento.
   `False` indica que a conexão TCP não foi estabelecida: investigue endereço,
   rota/VPN, firewall do Windows e filtros de rede. A falha de ping, sozinha,
   não prova que TCP está bloqueado. `--noproxy` evita que um proxy configurado
   no cliente interfira nesse teste; se a rede exigir proxy, teste também pelo
   navegador e siga a orientação da equipe de rede.
2. **No Windows que executa o IIS**, confirme com `ipconfig` que `172.20.28.3`
   ainda é um endereço acessível pela rede/VPN do colega. Em PowerShell:

   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 80 | Format-Table LocalAddress,LocalPort,OwningProcess
   Get-NetConnectionProfile | Format-Table Name,InterfaceAlias,NetworkCategory
   curl.exe -v --noproxy "*" http://127.0.0.1:8000/shc/permanencia
   curl.exe -v --noproxy "*" http://172.20.28.3/shc/permanencia
   ```

   O primeiro `curl` testa o backend encaminhado ao Windows; o segundo testa IIS
   usando o mesmo endereço da rede. Um listener em `0.0.0.0:80` aceita conexões
   nos endereços IPv4 locais, sujeito a bindings e filtros; um listener somente
   em `127.0.0.1:80` não recebe conexões remotas. A lista de listeners, por si só,
   não confirma que o site correto aceitará a requisição.
3. No **IIS Manager → Sites → Default Web Site → Bindings...**, confirme uma
   entrada `http`, porta `80`, endereço `All Unassigned` ou `172.20.28.3`, e
   hostname vazio para acesso pela URL com IP. Verifique também se o site está
   iniciado e se não há conflito com outro site. Em **IP Address and Domain
   Restrictions**, confira eventuais restrições de clientes. O binding é o
   endereço de destino do servidor; ele não determina sozinho os IPs de origem
   autorizados. Se for relevante, `netsh http show iplisten` mostra a lista de
   endereços do HTTP Service; uma lista vazia significa ausência de restrição
   explícita por essa lista.
4. No Windows, abra **Windows Defender Firewall with Advanced Security → Inbound
   Rules** e verifique as regras ativas para TCP porta local 80, o perfil de
   rede ativo, endereços locais e remotos e eventuais regras de bloqueio. Políticas
   de domínio podem controlar essas regras. O comando abaixo lista filtros de
   porta 80 ou `Any` em regras de entrada ativas; examine também os demais filtros
   e não interprete a lista isoladamente como autorização efetiva:

   ```powershell
   Get-NetFirewallRule -PolicyStore ActiveStore -Direction Inbound -Enabled True |
     Where-Object { (($_ | Get-NetFirewallPortFilter).LocalPort) -match '(^|,)\s*(80|Any)\s*(,|$)' } |
     ForEach-Object {
       $_ | Select-Object DisplayName, Action, Profile,
         @{Name='Port'; Expression={($_ | Get-NetFirewallPortFilter).LocalPort}},
         @{Name='Protocol'; Expression={($_ | Get-NetFirewallPortFilter).Protocol}},
         @{Name='RemoteAddress'; Expression={($_ | Get-NetFirewallAddressFilter).RemoteAddress}}
     } | Format-List
   ```

   Se for necessária uma regra, peça à equipe responsável que libere TCP 80
   apenas para a rede de colegas aprovada e no perfil apropriado. Não desative o
   firewall nem exponha a porta 8000 para resolver o acesso ao IIS.
5. Se o colega alcançar TCP 80 mas receber erro HTTP, confira bindings, hostname,
   restrições de IP, logs do IIS e URL Rewrite/ARR. Uma resposta `502` pode
   indicar que o IIS não alcança o backend: verifique o `curl` local para a porta
   8000, o encaminhamento do VS Code e o processo Gunicorn. Se o backend também
   falhar localmente, verifique o terminal e as dependências da aplicação.

Referências Microsoft: [bindings do IIS](https://learn.microsoft.com/en-us/iis/configuration/system.applicationhost/sites/site/bindings/binding),
[inspeção de regras do Firewall](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/configure-with-command-line)
e [HTTP Service e iplisten](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netsh-http).

## Container independente

No WSL normal do servidor, fora do devcontainer, entre na pasta real do projeto:

```bash
make deploy-test-build  # primeira vez ou após alteração do código incluído na imagem
make deploy-test
```

Depois de parar o container com `make deploy-test-stop`, use apenas
`make deploy-test` para reiniciá-lo sem rebuild. Esse comando exige uma imagem
local existente e não incorpora alterações de código até a próxima construção.
Após reconstruir, execute `make deploy-test` para iniciar a nova imagem.

Por padrão, o Makefile usa
`/mnt/e/OneDrive/OneDrive - Agência Nacional de Águas/data/CN3S/Exceedance`,
correspondente ao mount atualmente configurado no devcontainer. Confirme que essa
pasta existe no host. Para outro local, informe o caminho **no host**, não o
`/data` do devcontainer:

```bash
export SHC_DURATION_CURVES_HOST_DIR="/seu/caminho/no/host/CN3S/Exceedance"
make deploy-test
```

O Makefile passa a variável ao Compose; comandos `docker compose` executados
diretamente ainda precisam dela exportada no terminal. O Compose não cria a pasta
do host se ela não existir. O volume
é de leitura/escrita para inserir estações e salvar limites. Os resultados
científicos permanecem após a recriação do container; o cache de sessões e resultados temporários fica no volume Docker shc-sessions e respeita a expiração de cada entrada.

Teste `http://127.0.0.1:8000/shc` no Windows (com o `deploy-dev` parado) e depois
pelo IIS/Mac; feche o VS Code e teste novamente. A imagem inclui
Microsoft ODBC Driver 18, dependências de leitura Parquet e os módulos locais.
Os dados e o cache de autenticação dos notebooks não entram no build.

O runtime atual é Docker Desktop. Ele precisa estar funcionando. O modo detached
remove a dependência do terminal e `restart: unless-stopped` reinicia a aplicação
quando o Docker inicia, salvo parada deliberada. Isso não configura inicialização
sem login do Windows. Docker Desktop não tem suporte oficial em Windows Server;
o setup autônomo após reboot/logoff permanece uma etapa de infraestrutura separada.

## Entrada Microsoft e permissões

Acesse `/shc`, clique em **Entrar com a Microsoft**, abra o endereço indicado e
informe o código na página da Microsoft. Volte à SHC: a confirmação é automática.
Quem já estiver autenticado segue diretamente para `/shc/home`.

O protótipo usa o mesmo cliente de desenvolvimento padrão do Azure Identity que
os notebooks usam. Não exige callback ou segredo de aplicativo; políticas do
tenant ainda podem bloquear o fluxo ou pedir consentimento. A implantação
institucional deve usar uma inscrição de aplicativo aprovada pela organização.

Cada visitante tem credencial e token próprios. O token nunca é retornado no
HTML, JSON público ou cookie. `UserSqlConnector` reutiliza as operações SQL sem
abrir o cache compartilhado dos notebooks. `SqlConnector` permanece inalterado.
O SHC renova silenciosamente o token SQL com o cache MSAL privado da sessão. A sessão expira após oito horas sem requisições autenticadas. Configure o prazo em horas com `SHC_SESSION_IDLE_HOURS`. Sair remove o cache da conta daquela sessão. A política institucional pode exigir nova entrada antes desse prazo.

O ambiente atual usa HTTP na rede/VPN. Ao configurar HTTPS, defina
`SHC_COOKIE_SECURE=true` no ambiente do servidor/container. `FLASK_SECRET_KEY`
pode receber uma chave aleatória estável, sem incluí-la no código. A pasta de
sessões pode ser definida por `SHC_SESSION_DIR` (padrão `/tmp/shc-sessions`).

## Curvas de Permanência

- O catálogo lê código e nome diretamente de `<codigo>/metadata.json`, sem criar
  objetos `Station` ou consultar SQL. Metadados inválidos aparecem indisponíveis;
  os Parquets são verificados ao abrir a estação. A lista é compacta, pesquisável
  e apresentada em lotes de 50 itens. O catálogo fica em memória sem expiração por tempo;
  inserir ou editar uma estação invalida esse cache imediatamente.
- Selecionar uma estação preserva os Parquets históricos e carrega somente
  **cota da telemetria** dos três anos exibidos. `Station.load_series()` continua
  carregando tudo por padrão; filtros opcionais permitem restringir a consulta:
  `station.load_series(source="telemetria", series_type="cota", start="2024-01-01")`.
- As leituras de `UserSqlConnector.read_sql_with_retries` ficam em memória
  **sem expiração por tempo**, com limiar de 512 consultas; ao atingir a capacidade,
  o cache descarta entradas antigas. Os resultados são isolados pela credencial e banco.
  Os parâmetros e opções fazem parte da chave; erros não são armazenados e os
  DataFrames retornados podem ser alterados sem modificar o cache. O conector
  autentica na primeira consulta efetiva, evitando um `SELECT 1` adicional.
  **Atualizar observações** ignora o cache e busca dados novos. Reiniciar o worker
  esvazia esses caches; uma nova credencial usa um conjunto separado de entradas.
  Alterações externas em arquivos do catálogo exigem reiniciar o worker para
  aparecerem na lista. O `SqlConnector` dos notebooks permanece inalterado.
- **Inserir nova estação:** consultar o histórico e revisar `station.stats` por
  fonte/variável; escolher from_discharge (padrão) ou direct; informar correções
  e limites opcionais; então calcular e inserir. As séries carregadas na análise
  são reutilizadas. Análises expiram em 30 minutos.
- **Editar estação:** ao lado de **Atualizar observações**, abre a mesma janela
  com o código fixo. Consulta as estatísticas e preenche método, correções e
  limites salvos. **Recalcular e salvar** substitui a curva histórica para toda
  a equipe. Uma alteração concorrente exige reabrir a edição. Falhas de cálculo
  ou de gravação preservam os resultados anteriores.
- **Visualização:** Plotly é o padrão, com valores ao passar o mouse, zoom e
  seleção de séries na legenda. O seletor **Imagem (Matplotlib)** mostra o gráfico
  anterior; **Baixar PNG** continua exportando essa imagem. Alternar não consulta
  o SQL nem recalcula a curva. Ambos usam as mesmas referências e observações.
  Plotly.js Basic 3.1.0 e a tradução pt-BR são servidos em `static/vendor/`, com
  licença MIT incluída; o navegador não depende de CDN ou serviço externo.
  A biblioteca é carregada sob demanda, depois da lista, e pode ser reutilizada
  pelo cache do navegador. O bundle principal tem uma cópia `.js.gz` pré-comprimida;
  Flask a envia com `Content-Encoding: gzip` e `Vary: Accept-Encoding` quando o
  navegador aceita gzip. Ao atualizar o bundle, gere essa cópia novamente com
  `gzip.compress(..., compresslevel=9, mtime=0)`. Se o download falhar, a imagem Matplotlib continua
  disponível; selecionar **Interativo (Plotly)** tenta carregar a biblioteca novamente.
  Falhas de carregamento incluem a URL no Console do navegador para diagnóstico.
- As estatísticas de revisão descrevem os registros originais, antes da combinação
  das fontes e da sanitização. Correções substituem valores em datas existentes,
  após a combinação, sem alterar SQL. Cotas em cm e vazões em m³/s.
- As três variáveis são calculadas juntas: vazão, cota observada e cota derivada.
  A escolha de método controla o gráfico. Se a conversão falhar, as colunas
  derivadas ficam vazias com o motivo nos metadados; escolha cotas observadas
  explicitamente para exibir essa referência.
- Limites são compartilhados. Salvá-los altera `thresholds` e a seleção de linhas
  C95/C5 (`reference_exceedances`) em `metadata.json`,
  sem recalcular o histórico. Edições concorrentes exigem recarga. Para limites
  ausentes, vazios, decimais ou negativos não são aplicadas restrições artificiais.
- A publicação de novos resultados é atômica: uma falha não deixa uma estação
  parcial na lista. Na inserção, uma estação já cadastrada é aberta; a substituição
  do histórico acontece somente pelo fluxo explícito de edição.
- Gráficos e operações temporários são privados à sessão; os arquivos científicos
  não são expostos como uma pasta pública. PNGs e dados Plotly expiram em 30 minutos: use
  **Atualizar observações** para gerar outro. Sem telemetria recente, mostrar
  apenas as referências históricas com aviso explícito.

Manter **um worker Gunicorn**, como no Dockerfile: as operações usam threads de
fundo, cache local e locks por estação, sem Celery ou Redis. A primeira versão
prevê um único container. Recarregar/reiniciar durante um processamento interrompe
a operação; o navegador recebe uma mensagem para tentar novamente.

## Organização e operação

- `app.py`: configuração, proteção das rotas e página inicial.
- `login.py`: autenticação por dispositivo e sessão.
- `permanencia.py`: catálogo, estatísticas, curvas e persistência dos limites.
- `templates/` e `static/`: layout, estilos e interações do navegador.

Chuvas e CN3S aparecem como módulos futuros. O processamento científico continua
em `src/hydro`; não é duplicado no JavaScript.

```bash
docker compose -f web/compose.yaml logs --tail 100
make deploy-test-stop
make deploy-test
```

A variável do volume deve estar exportada ao executar os comandos `docker compose`
diretamente; o padrão do Makefile não altera o ambiente do terminal.

Os resultados novos ficam em `/data/CN3S/Exceedance/<codigo>/`: `daily_curve.parquet`,
`exceedance_curve.parquet`, `summary.parquet`, `stats.parquet`, `station_stats.parquet`
e `metadata.json`. Os limites `Cota de Alerta` e `Cota de Inundação` sempre existem
como entradas editáveis; `null` significa não informado e não gera linha no gráfico.
As pastas antigas precisam de recálculo a partir das observações.

## CN3S — prova de conceito mensal

O cartão CN3S abre `/shc/cn3s`. A página usa o mesmo login Microsoft do SHC e
executa preparação, calibração e inferência em segundo plano. Os dados de SQL
são consultados com a conta do visitante; nenhuma operação inicia o login de
terminal dos notebooks.

Para a primeira demonstração, clique em **Carregar exemplo de Marabá**:

- Estação `29050000`, calibração mensal `optim/PlainNSE_alfa_livre.json`.
- Inicialização CDS `10/2026`, referência `13/10/2026`, cinco meses de chuva.
- Chuva histórica salva até setembro; ACT = 1 mês, com vazões até março de 2027.
- O NSE de validação registrado nessa calibração é aproximadamente 0,02. O
  exemplo demonstra a integração; não comprova habilidade de previsão.

A página inspeciona bacia, áreas, cobertura e falhas das séries; permite salvar
chuva e vazão separadamente, preparar uma estação e salvar uma nova calibração
mensal. A confirmação de substituição indica quais arquivos serão escritos.
Use uma **cópia de trabalho das estações** para experimentar essas ações.

Calibrações novas ficam em `stations/<código>/Monthly/optim/<nome>.json` e nunca
substituem silenciosamente um arquivo existente. Os arquivos antigos em
`stations/<código>/optim/` continuam disponíveis, mas frequência e unidade de
ACT devem ser explicitamente mensais nos metadados. O primeiro mês dos dados define a origem da chuva e de `r0`, reutilizada na previsão. O aquecimento fica dentro do período. O formulário permite escolher objetivo, limites, semente e relação treino/teste de 10/90 a 95/5 em passos de cinco pontos percentuais. O corte pertence ao teste. O padrão é 20 gerações e o limite pode ser configurado de 1 a 1.000. A execução usa um trabalhador, população de cinco por parâmetro e sem polimento. Treinar até convergência permite ajustar tol e atol com teto de 1.000 gerações. O resultado informa se
o solver convergiu, atingiu o limite ou foi interrompido pelo usuário. O acompanhamento exibe a função objetivo
e os melhores parâmetros por geração. **Parar treino** encerra após a geração atual e abre para revisão o melhor resultado encontrado. Depois de revisar o gráfico e as métricas,
use **Salvar calibração** para publicar o resultado ou **Descartar resultado**.
Na revisão de uma calibração salva, **Atualizar dados** refaz o gráfico com os
Parquets atuais e os mesmos parâmetros. **Apagar calibração** remove do disco
o arquivo selecionado após confirmação.

**Ajuste manual** reavalia os parâmetros editados com o período, os dados e o
corte da calibração de origem. As métricas originais e ajustadas aparecem lado
a lado. Ao salvar um treino ou ajuste, informe o nome que aparecerá no
histórico. Cada novo resultado inclui o gráfico e uma cópia das entradas
usadas. Para calibrações anteriores sem essa cópia, o ajuste manual verifica
o SHA-256 dos arquivos mensais disponíveis contra o registro original.

A aquisição CDS permanece no notebook 03. O módulo exige os arquivos `prec` e
`hindcast` dos nove centros para a inicialização selecionada; os arquivos
`anomaly` não são necessários. Referência e horizonte devem pertencer aos leads
realmente presentes. Para executar novembro, por exemplo, atualize antes a
chuva histórica até outubro. Meses ausentes não são preenchidos.

As figuras preservam as convenções dos notebooks: cenário de chuva média e
cenário da mediana das chuvas corrigidas, ACT aplicado uma única vez, séries
mensais em mm/mês e vazões em m³/s. O ajuste visual à observação fica desligado.
P10–P90 representa variabilidade histórica; não é intervalo de confiança de
previsão. A referência não congela fontes online e as observações atuais podem
ser parciais ou estar em cache. Uma falha na comparação SQL não apaga as vazões
simuladas. As duas vistas observadas são produzidas quando há dados disponíveis.

Baixe os CSVs, a calibração e `settings.json` para manter o registro. São
exportados o histórico de chuva usado, os cenários completos, os resumos de chuva
por modelo, as observações/estatísticas disponíveis e a procedência dos arquivos.
Os resultados pertencem à sessão que iniciou o trabalho e expiram até uma hora
após a conclusão. Alterar a configuração invalida as figuras na página.

### Dados e execução local

`SHC_CN3S_DATA_DIR` aponta para uma pasta com `stations/`, `forecasts/` e
`downloads/` (padrão `/data/CN3S`). `SHC_HYDROGRAPHY_DIR` aponta para a pasta BHO
2017 50k com `geoft_bho_2017_50k_area_drenagem.parquet`. A hidrografia só é lida ao preparar
uma bacia. As séries salvas e os forecasts podem ser inspecionados sem SQL.

Instale o extra `web` no ambiente Python usado pelo servidor:

```bash
pip install -e '.[web]'
SHC_CN3S_DATA_DIR=/data/CN3S-poc make deploy-dev
```

Esse extra inclui as dependências científicas usadas pelo módulo, incluindo
SciPy, scikit-learn, Plotly, xarray, rioxarray e NetCDF4. O MERGE downloader usa o
commit `5660c84f76da244fb057d0f188a76158ecc14013`, correspondente ao ambiente dos
notebooks, por um arquivo fonte com SHA-256 verificado. Earthkit e credenciais
CDS não são necessários para a aplicação. O JavaScript Plotly completo 4.1.1
fica em `static/vendor/`, com cópia gzip, para suportar os boxplots; o módulo
Permanência mantém seu bundle existente.

### Container com os volumes CN3S

`compose.yaml` continua atendendo à configuração existente de Permanência.
Acrescente `compose.cn3s.yaml` para habilitar os volumes científicos. Exemplo
executado no host/WSL, com caminhos do host e diretórios já existentes:

```bash
export SHC_CN3S_HOST_DIR='/caminho/CN3S-poc'
export SHC_FORECASTS_HOST_DIR='/caminho/CN3S/forecasts'
export SHC_HYDROGRAPHY_HOST_DIR='/data/Geospatial_BR_Data/Hidrografia/BHO_2017_50k'
export SHC_STATES_HOST_DIR='/caminho/BR_UF_2022'
export SHC_CODE_REVISION="$(git rev-parse HEAD)"

make deploy-test-build SHC_COMPOSE='docker compose -f web/compose.yaml -f web/compose.cn3s.yaml'
make deploy-test SHC_COMPOSE='docker compose -f web/compose.yaml -f web/compose.cn3s.yaml'
```

`SHC_DURATION_CURVES_HOST_DIR` mantém o significado descrito acima. O diretório
`SHC_CN3S_HOST_DIR` precisa conter `stations/` e `downloads/`, ambos graváveis.
Forecasts e hidrografia são montados somente para leitura. O número de revisão
é incorporado na construção; os registros também incluem hashes dos arquivos
Python para identificar fontes modificadas. Sem revisão informada, o registro
informa `unknown`; sem `.git` no container, o estado da árvore é desconhecido.

Mantenha **um worker Gunicorn**: o módulo serializa operações CN3S com um lock
no processo, incluindo leituras NetCDF que não podem sobrepor uma inferência.
As requisições HTTP só iniciam trabalhos e consultam progresso. Reiniciar o
worker (inclusive com `--reload`) interrompe operações; a interface informa a
interrupção em vez de tentar retomá-las. Não há fila durável, cancelamento ou
agendamento automático nesta prova de conceito. Operações nos arquivos por
notebooks externos não participam desse lock; evite editar a mesma cópia de
trabalho simultaneamente.


O CN3S agora tem três páginas: **Estação** (`/shc/cn3s`), **Calibrar Estação**
(`/shc/cn3s/calibrar`) e **Previsão** (`/shc/cn3s/previsao`). A seleção da estação
acompanha a navegação. Na página Estação, selecionar um código abre a ficha e a
bacia e lê as estatísticas de `overview.json` com sua data de atualização.
**Atualizar estatísticas** consulta as fontes com a conta SQL conectada, substitui
o resumo ao concluir e renova as entradas das consultas no cache SQL. O cadastro
e as leituras posteriores reutilizam o cache do conector para consultas idênticas.
Município, UF e rio vêm dos códigos do inventário Hidro e das tabelas
`municipio`, `estado` e `rio`. Latitude e longitude vêm de `estacao`, em
graus decimais. A ficha aparece assim que o inventário chega. Uma barra de
atividade acompanha a consulta diária. Durante a consulta, ou em caso de falha,
o último resumo disponível mantém a data de atualização. Cota e vazão são apresentadas por fonte e código de série.
**Adicionar estação** abre o diálogo de cadastro. O servidor consulta o inventário,
prepara a bacia e salva o resumo em `overview.json`. Após a publicação da pasta, a
nova estação passa a ser a seleção atual. O cadastro lê somente os polígonos de drenagem da BHO 2017 50k.
A área hidrográfica é a soma de `nuareacont` (km²) dos polígonos a montante,
incluindo o do exutório. A camada nacional sai de escopo após a delimitação.
A chuva/vazão mensal e a calibração ficam
na segunda página.

Para desenhar estados no mapa, configure `SHC_STATES_PATH` com o shapefile IBGE
(padrão local `/data/Geospatial_BR_Data/BR_UF_2022/BR_UF_2022.shp`). Na sobreposição
Compose CN3S, defina `SHC_STATES_HOST_DIR` como a pasta contendo todos os arquivos
`.shp`, `.shx`, `.dbf` e `.prj` de `BR_UF_2022`; ela será montada somente para leitura.
O mapa reprojeta bacia e estados para EPSG:4326. O localizador nacional e o fundo
alternativo usam `web/static/br-uf-2022.geojson`, derivado da malha estadual
BR_UF_2022 do IBGE, simplificada em 0,045° com coordenadas arredondadas a 0,001°.
O fundo alternativo entra quando o shapefile configurado está ausente ou ilegível.
O painel regional usa a geometria original da bacia. O
marcador é exibido quando o inventário fornece as coordenadas da estação.
