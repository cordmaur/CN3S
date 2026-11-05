# SHC — Sistema Hidrológico da COVEC

## Como uma requisição chega à aplicação

```text
Navegador → IIS porta 80: /shc/...
          → URL Rewrite identifica o caminho
          → ARR encaminha para localhost:18000/shc/...
          → Docker encaminha para a porta 8000 do container
          → Gunicorn → Flask
```

URL Rewrite seleciona o destino e ARR faz o encaminhamento HTTP. O mapeamento
`127.0.0.1:18000:8000` é publicado pelo Docker e independe do VS Code. Somente o
servidor acessa essa porta de loopback; outros computadores acessam o IIS.
Em desenvolvimento, o IIS usa a porta 8000 encaminhada pelo VS Code.

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

A pasta `/data/CN3S/duration_curves` já está montada no devcontainer. Para outro
local, configure `SHC_DURATION_CURVES_DIR` antes de iniciar o servidor. A pasta
precisa existir; a SHC não cria silenciosamente uma pasta científica vazia.

## Configuração do IIS

No **Default Web Site → URL Rewrite**, substitua a antiga regra de teste por:

| Configuração | Desenvolvimento | Container implantado |
|---|---|---|
| Nome | SHC | SHC |
| Padrão | `^shc(?:/.*)?$` | `^shc(?:/.*)?$` |
| Ação | Rewrite | Rewrite |
| URL | `http://127.0.0.1:8000/{R:0}` | `http://127.0.0.1:18000/{R:0}` |

Mantenha **Append query string** e **Stop processing of subsequent rules** ativos,
e **Enable proxy** habilitado em ARR. A regra encaminha também CSS, JavaScript,
login e operações. Não é necessário reiniciar o IIS. A página `/` do IIS continua
separada e pode hospedar o índice geral de aplicações. As rotas `/cn3s-test`
foram removidas; o endereço agora é `http://172.20.28.3/shc`.

## Container independente

No WSL normal do servidor, fora do devcontainer, entre na pasta real do projeto.
Informe o caminho da pasta científica **no host**, não `/data` do devcontainer:

```bash
export SHC_DURATION_CURVES_HOST_DIR="/seu/caminho/no/host/CN3S/duration_curves"
docker compose -f web/compose.yaml up --build -d
docker compose -f web/compose.yaml ps
```

Por exemplo, se o mount do devcontainer ainda corresponder ao caminho atual:

```bash
export SHC_DURATION_CURVES_HOST_DIR="/mnt/e/OneDrive/OneDrive - Agência Nacional de Águas/data/CN3S/duration_curves"
```

O Compose exige a variável e não cria a pasta do host se ela não existir. O volume
é de leitura/escrita para inserir estações e salvar limites. Os resultados
científicos permanecem após a recriação do container; sessões, análises e gráficos
temporários ficam no próprio container e podem ser descartados.

Teste `http://127.0.0.1:18000/shc` no Windows antes de mudar a regra do IIS para
18000. Depois teste pelo Mac, feche o VS Code e teste novamente. A imagem inclui
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
O token é usado até expirar; nesse caso, o usuário entra novamente. A SHC atual
não implementa renovação automática de tokens.

O ambiente atual usa HTTP na rede/VPN. Ao configurar HTTPS, defina
`SHC_COOKIE_SECURE=true` no ambiente do servidor/container. `FLASK_SECRET_KEY`
pode receber uma chave aleatória estável, sem incluí-la no código. A pasta de
sessões pode ser definida por `SHC_SESSION_DIR` (padrão `/tmp/shc-sessions`).

## Curvas de Permanência

- O catálogo lê código e nome diretamente de `<codigo>/meta.json`, sem criar
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
- O fallback automático para cotas diretas permanece. A SHC informa o método
  aplicado e preserva o método solicitado e a sanitização nos metadados.
- Limites são compartilhados. Salvá-los altera somente `thresholds` em meta.json,
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
docker compose -f web/compose.yaml stop
docker compose -f web/compose.yaml up -d
```

A variável do volume deve continuar disponível ao executar esses comandos.
