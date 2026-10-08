# Discuss fitting high and low flows

## Scope and plan
Analyze objectives.py and related scoring/model equations. Discuss a methodology in chat; do not change model, objective, optimizer, or notebook code.

## Session record
- PlainNSE minimizes full-series normalized squared errors.
- NSETopBlend averages full-series and observed upper-decile NSE losses.
- Tail-only NSE divides by tail variance, which can be small or zero, particularly for low flows.
- Proposed first experiment: observed-flow strata (lower 20%, middle, upper 10%), mean squared errors normalized by each stratum mean discharge squared, with a documented positive discharge floor. Trial weights: low 0.4, middle 0.2, high 0.4.
- Freeze thresholds/scales from calibration observations; use paired dates and a common evaluation window.
- Compare against current objectives with chronological validation, repeated optimizer seeds, global NSE, tail error/bias, and recession/peak inspection. Log-NSE/raw-NSE blend is a simpler literature-supported comparator.
- Consulted Thirel et al. (2024), https://doi.org/10.5194/hess-28-4837-2024, and Pushpalatha et al. (2012), https://doi.org/10.1016/j.jhydrol.2011.11.055.
- No implementation or calibration experiment performed. Source code unchanged by this discussion.

## Proposed method-call examples
Existing baseline calls only (the proposed objective is conceptual and has no implemented API):

```python
Objectives.PlainNSE.evaluate(df)
Objectives.NSETopBlend.evaluate(df)
```
