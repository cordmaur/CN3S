# Ancoragem no mês de referência com ACT

## Plano

- Incluir no gráfico mensal principal a vazão simulada desde o mês de referência, seguindo o mesmo recorte do gráfico de janela móvel.
- Identificar a partir de que mês a chuva prevista influencia a vazão. Preservar a duração dos cenários de chuva e os resultados numéricos.
- Habilitar a ancoragem quando houver vazão observada e simulada no mês de referência, inclusive com ACT positivo. Usar a média da vazão observada até a data de corte e aplicar o deslocamento somente ao gráfico mensal.
- Reproduzir o caso de Lábrea com os artefatos salvos e verificar a caixa no Chromium.

## Registro da sessão

No caso de novembro de 2026, a simulação tem um ponto comum aos dois cenários antes de a chuva prevista chegar à vazão. Esse ponto permite ancorar a curva no mesmo mês da observação.

Reprocessados os gráficos com os CSVs da execução concluída em Lábrea. As duas janelas do gráfico principal incluíram novembro a março e a ancoragem alinhou novembro à média observada de 914,76 m³/s. O deslocamento foi constante nos meses seguintes. O Chromium confirmou a caixa de ancoragem e o aviso de que a chuva prevista passa a influenciar a vazão em dezembro. Também foram verificados os avisos quando faltam dados observados ou simulados no mês de referência. Ruff e mypy estrito passaram.

## Exemplos de chamadas

```python
inference.plot_monthly_discharge(previous_years=3)
inference.plot_monthly_discharge(previous_years=3, anchor_to_observed=True)
```
