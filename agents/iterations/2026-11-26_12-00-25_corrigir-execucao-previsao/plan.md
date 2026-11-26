# Execução da previsão em estações legadas

## Plano

- Reproduzir a falha a partir da operação registrada para Lábrea e localizar a etapa que interrompe a execução.
- Reusar a resolução de nome da ficha da estação ao inicializar a previsão, com a alteração limitada à instância em memória.
- Mostrar o progresso e as falhas da operação junto ao botão de execução.
- Verificar a operação com a cópia dos arquivos de Lábrea e exercitar progresso, sucesso e falha no Chromium.

## Registro da sessão

O servidor recebeu a operação. Em Lábrea, o nome consta em `overview.json`, enquanto a inicialização da previsão exigia `station_name` em `metadata.json` e falhava com `KeyError`. A situação aparecia no topo da página, longe do botão.

O Chromium concluiu a operação com uma cópia da estação de Lábrea, a calibração da operação original e os arquivos CDS de novembro de 2026. Os cubos MERGE e a vazão consultada foram substituídos por dados de verificação. A interface mostrou o progresso perto do botão, apresentou o gráfico e tornou o botão disponível ao concluir. Uma falha simulada também apareceu junto ao botão. O cadastro em disco permaneceu idêntico. Passaram a formatação Ruff, o lint completo e o mypy estrito de `web/cn3s.py`. O servidor de desenvolvimento recarregou após a alteração.

## Exemplos de chamadas

```text
POST /shc/cn3s/stations/13870000/forecast
     {"calibration":"Monthly/optim/<calibracao>.json","cycle":"202611","months":4}
GET  /shc/cn3s/operations/<id>
```
