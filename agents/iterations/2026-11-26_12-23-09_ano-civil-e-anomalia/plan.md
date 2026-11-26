# Ano civil, anomalia de chuva e consulta de vazão

## Plano

- Consultar somente vazão diária até a data de corte, usando o cache SQL existente. Informar separadamente o carregamento da série e a preparação dos gráficos.
- Remover a figura de chuva bruta e conservar a comparação com a previsão corrigida. Alternar a figura de anomalia por modelo entre % e mm usando os dois produtos da rotina de chuva.
- Na janela do ano civil, usar janeiro a dezembro. Exibir os meses futuros do ano seguinte nas posições dos meses correspondentes, em um novo segmento, com ano real no hover.
- Encerrar a série observada preta na média de vazão do mês de referência até a data de corte e usar esse valor na ancoragem. Manter as curvas de previsão centradas em datas consecutivas quando a centralização estiver ativa.
- Verificar o fluxo pelo Flask e Chromium e conferir o recorte, as unidades e a ancoragem nos artefatos Plotly.

## Registro da sessão

O cache SQL é em memória e associado à consulta e ao token. O Parquet mensal atende à calibração, enquanto as comparações usam dados diários. Antes, o caminho da previsão também solicitava cota e mantinha a indicação de consulta enquanto os gráficos eram preparados.

O teste pelo Flask e Chromium usou uma cópia da estação de Lábrea, o CDS real de novembro de 2026 e dados de teste para MERGE e vazão observada. Verificou a consulta somente de vazão até 26/11, a ausência do PNG de chuva bruta, as duas unidades da anomalia, os doze meses no eixo anual e o segmento de janeiro a março de 2027 separado do segmento de novembro e dezembro de 2026. A curva preta terminou na média de novembro até o dia 26, e a curva ancorada usou esse mesmo valor. Ruff e mypy estrito passaram.

## Exemplos de chamadas

```python
station.load_series(series_type="vazao", end="2026-11-26")
inference.plot_monthly_discharge(
    centered=False, previous_years=3, anchor_to_observed=True
)
inference.rainfall.plot_rainfall_anomaly(unit="mm")
```
