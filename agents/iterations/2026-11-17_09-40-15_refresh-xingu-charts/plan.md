# Atualizar gráficos e relatórios do Xingu a partir de referências salvas

- Acrescentar seção independente ao final do notebook: criar Station, carregar ExceedanceAnalysis.from_saved, carregar séries Hidro/Telemetria e atualizar PNG/Word.
- Usar método, percentuais e limites já salvos. Não chamar calculate nem save_results; preservar metadata.json e todas as tabelas Parquet.
- Corrigir a descrição de origem das séries nos relatórios e mensagens do gráfico para refletir Hidro > Telemetria.
- Executar para as sete estações do Xingu, comparar hashes dos arquivos científicos e verificar as imagens incorporadas aos relatórios.

## Registro da sessão

- Acrescentada ao final do notebook uma seção com configuração própria e laço de recarga, respeitando as escolhas salvas de método/percentuais/limites.
- Atualizados os sete PNGs a partir das séries combinadas Hidro/Telemetria. Boa Sorte estava inicialmente bloqueado para gravação e recebeu uma cópia atualizada; após o usuário fechar o documento, a cópia substituiu report.docx. Os sete relatórios estão nos nomes finais, sem cópia intermediária.
- Comparados hashes dos 42 arquivos científicos (metadata.json e Parquet): todos idênticos antes/depois.
- Verificadas duas tabelas, imagem incorporada idêntica ao PNG e descrição das fontes em todos os sete relatórios entregues. Gráfico de Boa Sorte inspecionado visualmente.
- Ruff format --check e Ruff check completos passaram nos dois módulos modificados e no notebook. Mypy sem cache passou no módulo de relatório, com aviso preexistente sobre strict_equality_for_none.

## Exemplos de chamadas

```python
station = Station(station_id, connector=conn)
analysis = ExceedanceAnalysis.from_saved(station_dir, station)
station.load_series(source="hidro/telemetria")
analysis.plot_annual_stage_chart(ax, ref_year=XINGU_REF_YEAR, lookback=XINGU_LOOKBACK)
save_station_report(station, station_dir / "report.docx", result=analysis.results,
                    chart_path=station_dir / "annual_stage_chart.png")
```
