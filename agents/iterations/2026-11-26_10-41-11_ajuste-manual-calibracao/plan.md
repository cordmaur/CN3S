# Ajuste manual e nome da calibração

## Implementação

- Abrir o ajuste manual na revisão do resultado salvo, preenchendo os oito parâmetros com os valores originais. Recalcular o modelo uma vez para cada conjunto editado. Exibir a função objetivo e o NSE de treino e teste lado a lado com a referência. Manter o período, a chuva, a vazão observada, a função objetivo e a convenção de corte originais. A revisão mostra o gráfico do ajuste e volta à referência ao descartar.
- Salvar um treino ou um ajuste exige um nome de exibição. O histórico e a previsão mostram esse nome, a data e a função objetivo. O identificador interno mantém os caminhos de previsão e a publicação atômica. O resultado manual fica em um arquivo próprio e guarda a referência de origem e as mudanças nos parâmetros.
- Gravar as entradas originais junto aos novos resultados. Para resultados anteriores sem entradas anexadas, aceitar os Parquets locais quando sua identidade puder ser comprovada pelo SHA-256 do registro. Informar quando a reprodução não é possível.

## Registro da sessão

Conferidos os hashes dos dois Parquets associados à calibração de 46 gerações de Lábrea. Em Chromium, com uma cópia temporária da estação, recalculados dois ajustes sucessivos em k0 e beta, comparados os indicadores, salvo um resultado com nome e verificada a integridade do original. Um segundo ajuste usou as entradas anexadas após remover a chuva da cópia temporária. O descarte voltou ao histórico. Um treino real em cópia de Marabá também foi interrompido e salvo com o nome escolhido. Passaram Ruff completo, formatação, mypy estrito e sintaxe JavaScript.

## Exemplos de chamadas

```text
POST stations/13870000/manual-calibration {"calibration":"Monthly/optim/<original>.json","params":{"k0":0.98,"beta":0.02}}
GET  operations/<ajuste>
POST operations/<ajuste>/save {"name":"Lábrea · ajuste de k0 e beta"}
```
