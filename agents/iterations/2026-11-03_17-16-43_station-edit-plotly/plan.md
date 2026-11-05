# Edição de estação e visualização interativa

Reutilizar a janela de inserção para editar uma estação existente: consultar estatísticas originais, preencher código fixo, método solicitado, correções e limites salvos. Recalcular somente ao confirmar; alterações são compartilhadas. Preservar a troca automática de método. Recusar edição se os arquivos mudarem desde a análise; preparar arquivos temporários e preservar os resultados anteriores em caso de falha na publicação.

Apresentar Plotly por padrão, com seletor para o Matplotlib existente. Manter referências históricas, faixa de permanência, três anos telemétricos, limites e unidades. Servir Plotly.js localmente, sem nova dependência Python ou CDN no navegador. Dados e imagens continuam privados por sessão.

Verificar com séries sintéticas os caminhos de edição e inserção, conflitos, falhas, persistência e equivalência dos dados plotados. Não alterar o conector original nem criar uma suíte formal.

## Registro da sessão

Implementação concluída em `web/permanencia.py`, templates e arquivos estáticos. O botão **Editar estação** fica ao lado de **Atualizar observações**, consulta séries originais e reutiliza a janela com código fixo, estatísticas e configurações salvas. **Recalcular e salvar** publica a nova curva para todos. A revisão inclui metadados e atributos dos Parquets, sem carregar os Parquets no catálogo. A publicação usa arquivos temporários, lock por estação e restauração dos arquivos anteriores em caso de erro de substituição. Se a gravação concluir e a consulta posterior falhar, a interface informa que a estação foi salva.

Plotly.js Basic 3.1.0, tradução pt-BR e licença MIT estão em `web/static/vendor/`. Nenhuma dependência Python foi adicionada. O endpoint JSON é privado por sessão, como o PNG. A visualização interativa é padrão e o seletor alterna para Matplotlib sem outra consulta SQL. O botão de download continua exportando o PNG Matplotlib.

Verificações temporárias, sem novos testes no repositório:

- Séries sintéticas exercitaram edição, inserção, métodos direto e a partir da vazão, persistência/remoção de correções e limites, reutilização do histórico, conflito entre usuários, falha científica e restauração após falha de gravação.
- Comparação numérica dos traços Plotly com os valores Matplotlib: min/max, quantis, MLT e três anos telemétricos; mesma exclusão de 29 de fevereiro.
- Chromium verificou renderização local, idioma, hover, zoom, alternância, preenchimento da edição, salvamento de correção, estado limpo da nova inserção e redimensionamento. Sem erros JavaScript ou requisições externas.
- Ruff, compilação Python, sintaxe JavaScript e verificação de espaços passaram. O fluxo anterior também passou na verificação temporária existente.
- Os dados científicos reais não foram alterados; os ensaios usaram diretórios temporários. Autenticação e acesso SQL reais continuam dependendo do ambiente do usuário.

Documentação de referência: [instalação local do Plotly.js](https://plotly.com/javascript/getting-started/), [localização](https://github.com/plotly/plotly.js/blob/main/dist/README.md).

## Exemplos de chamadas

```python
station = Station(code, sanitization=corrections, connector=conn)
station.load_series()
reporter = DurationCurveReporter(station, thresholds=thresholds)
reporter.create_duration_curve(series_type="cota", method="from_discharge")
```
