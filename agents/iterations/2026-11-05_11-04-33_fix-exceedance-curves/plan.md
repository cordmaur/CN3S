# Fix exceedance curves

- Adapt the calculation to the current Station API, including descriptions and period-specific statistics.
- Use the station's rating-curve client and retain the existing failure status when conversion is unavailable.
- Check representative observations, missing data, rating-curve failure, and repository formatting/lint requirements.

Session: The method now uses the current station series and statistics APIs, initializes unloaded stations, and resolves the rating-curve client from the station. Checks and remaining pre-existing lint findings are reported in the handoff.

## Example

```python
reporter = DurationCurveReporter(station)
result = reporter.create_exceedance_curves(source="hidro", period=slice("2000", "2020"))
```
