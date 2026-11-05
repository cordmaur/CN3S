# Carregamento de estações e Plotly

Adicionar cache de consultas SQL no conector web, isolado por credencial, sem expiração temporal, com capacidade de 512 entradas e resultados independentes de mutações. Manter SqlConnector dos notebooks intacto. Permitir atualização explícita sem cache.

Adicionar filtros opcionais de fonte e variável a Station.load_series, preservando a chamada padrão. Ao abrir gráficos consultar somente cota telemétrica no período recente.

Ler o catálogo diretamente de meta.json, reduzir verificações repetidas e manter o catálogo em memória sem expiração temporal, invalidando após gravações. Remover a dependência entre a renderização da lista e o carregamento de Plotly; investigar a falha real usando a URL IIS e o navegador.

Verificar contagem de consultas, isolamento/expiração do cache, resultados das séries filtradas, caminhos de edição/inserção e navegador. Executar Ruff completo em todos os arquivos Python alterados.

## Registro da sessão

Implementado:

- `Station.load_series` aceita `source` e `series_type`; os argumentos omitidos preservam a carga completa. A estrutura de séries mantém frames vazios nas variáveis não solicitadas e cada chamada substitui a janela anterior. Os prints de temporização adicionados pelo usuário foram preservados.
- `load_chart` solicita somente cota telemétrica dos três anos exibidos. O conector web usa cache sem expiração temporal, com limiar de 512 entradas, isolado pelo hash da credencial e banco, além de consulta/parâmetros/opções. DataFrames retornados são independentes e falhas não são armazenadas. Eliminada a consulta antecipada SELECT 1; a conexão autentica na primeira leitura efetiva. Atualizar observações força nova leitura. SqlConnector dos notebooks não foi alterado.
- O catálogo lê somente `meta.json`, sem Station/SQL/revisões dos Parquets, e fica em memória sem expiração temporal. Publicação de resultados invalida o catálogo. Parquets são validados na abertura da estação. Na medição deste workspace, os nove metadados levaram aproximadamente 0,053 s na primeira leitura e 0,00004 s no cache.
- Plotly passou a carregar sob demanda, sem bloquear a lista. Biblioteca e localização versionadas têm cache de navegador; páginas e dados continuam no-store. A interface informa o carregamento, conserva Matplotlib em falha e permite nova tentativa ao selecionar Plotly. Erros detalhados ficam no Console.

Diagnóstico Plotly: a URL IIS respondeu 200, o conteúdo recebido teve hash idêntico ao arquivo local e inicializou corretamente no Chromium. Portanto, a causa exata da falha original no navegador do usuário não foi reproduzida; solicitados detalhes de Console/Network. O novo carregador cobre biblioteca não pré-carregada e permite recuperar falha de download.

Verificações temporárias, sem nova suíte no repositório:

- Leitura completa: quatro consultas de observações; filtro de cota telemétrica: uma, com os mesmos valores. Verificados carga histórica isolada, ausência de telemetria e filtros inválidos.
- Fluxo com UserSqlConnector real e SQL simulado: primeira abertura com cinco leituras SQL (inventários incluídos), segunda abertura sem SQL, atualização explícita com cinco leituras novas.
- Cache verificado quanto a credenciais distintas, parâmetros, mutação de DataFrames, ausência de expiração temporal, descarte por capacidade, atualização forçada e erros não armazenados.
- Catálogo não chama Station nem metadata/revisões; chamadas seguintes usam cache. Arquivos estáticos versionados têm cache; página autenticada permanece no-store.
- Chromium verificou lista sem solicitar Plotly, falha induzida da primeira descarga, recuperação na nova tentativa, idioma, zoom, alternância, edição e inserção. Sem erros JavaScript não tratados ou serviços externos.
- Os scripts temporários anteriores de regressão e edição passaram. Ruff completo, formatação, compilação Python, sintaxe JavaScript e verificação de espaços passaram nos arquivos alterados. Não houve modificação de dados científicos reais nem de SqlConnector.

A correção de Ruff em `web/app.py` usa uma exceção S108 pontual comentada para conservar o diretório de sessões existente, cujos arquivos usam permissão 0600. Nenhuma regra adicional foi desabilitada globalmente.

## Diagnóstico adicional da conexão pelo Mac

O usuário informou `net::ERR_CONNECTION_RESET` ao carregar o bundle pelo Chrome no Mac, via IIS/VPN, usando Gunicorn no VS Code. Esse erro ocorre no transporte do arquivo, antes da execução do JavaScript. A causa exata no caminho do Mac não foi determinada.

Adicionada cópia gzip determinística do bundle, sem dependência nova. Flask negocia gzip conforme Accept-Encoding e distingue as variantes com Vary e ETags próprios. O arquivo passou de 1.036.463 para 356.447 bytes (aproximadamente 66% menor). Verificados conteúdo descomprimido, resposta sem gzip e gzip desabilitado, revalidação 304 e entrega pela URL IIS real com HTTP 200 e Content-Encoding gzip. O teste no Mac permanece necessário para confirmar que o reset foi resolvido.

## Política de cache ajustada a pedido do usuário

Removidos os limites de tempo dos caches SQL e do catálogo. SimpleCache usa `default_timeout=0`; SQL usa `threshold=512`. A capacidade conta resultados de consultas (incluindo inventários), não estações. Atualizar observações continua forçando SQL e gravando os resultados novos; inserir/editar invalida o catálogo. Os caches continuam em memória por worker e isolados por credencial; reiniciar o worker os esvazia. Sessões e operações temporárias mantêm suas validades próprias.

## Exemplos de chamadas

```python
station.load_series(source="telemetria", series_type="cota", start="2024-01-01")
station.load_series()  # comportamento completo existente
```
