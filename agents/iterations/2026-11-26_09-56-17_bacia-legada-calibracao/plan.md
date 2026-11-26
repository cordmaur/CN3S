# Bacia legada e mês inicial da calibração

## Diagnóstico e ajustes

- O cadastro de Lábrea (13870000) contém `watershed.parquet`. O mapa já reconhecia esse nome, mas `Station.from_folder` exigia `upstream_watershed.parquet`. Usar a mesma resolução no carregamento da estação e no mapa, priorizando o arquivo atual quando os dois existem. A proveniência de previsão usa o caminho efetivamente lido.
- O mesmo cadastro traz `area_station_km2` nulo. O último inventário salvo contém `AreaDrenagem` de 226.000 km². Ler esse valor como área de inventário para a calibração. Conservar a área geográfica como informação separada.
- Inicializar o mês inicial com janeiro de 2000 a cada nova calibração. Conservar a escolha do usuário durante o preparo.

## Registro da sessão

O Chromium executou **Preparar dados faltantes** com a geometria real da estação copiada para uma pasta temporária e respostas controladas de chuva e vazão. Foi verificada a publicação dos dois Parquets mensais, a geometria válida, a área recuperada do inventário, a preferência pelo nome atual quando ambos existem e a reabertura de **Nova calibração** em janeiro de 2000. Ruff completo, formatação e sintaxe JavaScript passaram. O mypy estrito reportou sete apontamentos preexistentes nos trechos de tipagem de séries e estatísticas do par de arquivos.

## Exemplos de chamadas

```python
station = Station.from_folder(stations_dir / "13870000")
```

```text
POST stations/13870000/inputs  {"series":"rain","start":"2000-01-01","end":"2026-10-01","replace":true}
GET  operations/<preparo>
```
