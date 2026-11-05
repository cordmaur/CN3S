# Ruff em permanencia.py

Executar todas as regras configuradas do Ruff em `web/permanencia.py`, corrigir os avisos sem alterar o comportamento científico ou os fluxos da interface e verificar os caminhos existentes de cálculo, edição e salvamento. Documentar as exceções que forem justificadas na configuração e registrar em `AGENTS.md` a execução do Ruff completo em arquivos Python alterados antes de concluir cada iteração.

Evitar classes de exceção e abstrações criadas apenas para satisfazer regras de estilo; manter as exceções específicas e justificadas. Verificar que o formatador e o lint não entram em conflito.

## Registro da sessão

Executado o Ruff completo em `web/permanencia.py` e no novo `web/__init__.py`; os dois arquivos passaram também em `ruff format --check`. Corrigidos tratamento de exceções, vírgulas/formatação, tipo de parâmetros, `zip`, constante de dia bissexto e tamanho das linhas. A publicação dos resultados foi extraída para uma pequena função para manter claro o bloco de salvamento. A seleção de fonte e a obtenção do objeto Flask mantêm exceções `SLF001` pontuais, comentadas, por serem chamadas específicas necessárias ao fluxo existente.

As únicas regras desabilitadas globalmente nesta iteração foram `TRY003` (evita exigir classes de exceção para mensagens simples) e `COM812` (conflita com o formatador Ruff). `AGENTS.md` agora exige Ruff completo e formatação para arquivos Python criados ou alterados na iteração, além de orientações para as regras relevantes.

Verificação: scripts temporários existentes com séries sintéticas passaram para autenticação simulada, catálogo, carregamento, inserção e edição, conflitos, persistência, restauração em falha, dados Plotly e comparação científica. Adicionalmente, verificados valores numéricos inválidos e catálogo com metadados incompletos. Compilação Python e `git diff --check` passaram. Testes não alteraram dados científicos reais.

Fora do escopo desta alteração, o Ruff ainda aponta `S108` em `web/app.py`, e `TC003` e `SLF001` em `web/login.py`; nenhum desses arquivos foi modificado nesta iteração.

## Exemplos de chamadas

```python
station = Station(code, connector=conn)
reporter = DurationCurveReporter(station)
reporter.create_duration_curve(series_type="cota", method="from_discharge")
```
