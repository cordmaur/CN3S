# Implementação da tela de Previsão CN3S

## Plano

- Implementar o fluxo aprovado no [plano da tela](../2026-11-26_10-52-59_tela-previsao/plan.md), usando os catálogos e a operação Flask existentes. Mostrar o gráfico completo e os oito parâmetros da calibração selecionada.
- Usar a primeira sequência mensal disponível do ciclo CDS para o horizonte de chuva. Resolver o corte de observação no servidor e registrá-lo com o resultado.
- Entregar a vazão mensal como primeiro resultado. Reusar os cenários calculados para as vistas centrada e iniciada em janeiro, com os três anos anteriores opcionais e a ancoragem visual. Calcular a extensão pelo calendário de vazão com ACT, inclusive na virada do ano.
- Verificar formatação, lint completo, tipos, janelas e ações em Chromium com dados preparados de Marabá.

## Registro da sessão

Implementação no fluxo Flask, no JavaScript da tela e nas funções de visualização mensal. A interface mantém os CSVs numéricos e pode exibir a figura original quando a ancoragem está indisponível.

Validados em Chromium a seleção inicial do ciclo, o bloqueio por falta de chuva, uma estação sem calibrações, o gráfico completo da calibração, os três anos anteriores, as duas janelas, a ancoragem, a reabertura da operação e o layout móvel. A execução de Marabá com os arquivos CDS locais exibiu vazões até fevereiro com ACT zero e até março com ACT de um mês. As observações de vazão e os cubos MERGE foram substituídos por dados de verificação no teste completo, pois não havia acesso ao SQL institucional e a leitura do cache GRIB local encontrou um arquivo corrompido. A calibração, a leitura do CDS e a simulação CN3S usaram os caminhos reais da aplicação.

A verificação numérica também cobriu a extensão simétrica para horizontes maiores que seis meses, o bloqueio da ancoragem quando falta a observação de referência e a compatibilidade da API usada pelo notebook. Passaram a formatação Ruff, o lint completo, o mypy estrito e o `git diff --check`.

## Exemplos de chamadas

```text
GET  /shc/cn3s/stations/29050000
GET  /shc/cn3s/cycles
POST /shc/cn3s/stations/29050000/forecast
     {"calibration":"Monthly/optim/mensal_exemplo.json","cycle":"202610","months":5}
GET  /shc/cn3s/operations/<id>/download/monthly-calendar.json?inline=1
```

```python
inference.plot_monthly_discharge(centered=False, previous_years=3, forecast_only=True)
inference.plot_monthly_discharge(
    centered=True, previous_years=3, forecast_only=True, anchor_to_observed=True
)
```
