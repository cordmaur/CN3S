# Implement extreme-flow objective

## Plan
Add ExtremeFlowBlend to objectives.py and the Objectives namespace. Use observed lower-20%, middle, and upper-10% groups; mean squared errors divided by squared group mean discharge with a positive floor; default weights 0.4, 0.2, 0.4. Support an optional calibration reference series to freeze thresholds and scales. Keep existing objectives unchanged. Skip empty groups and normalize active weights. Check representative calculations, Ruff, and strict mypy without adding a formal test suite.

## Session record
Implemented ExtremeFlowBlend in objectives.py and registered Objectives.ExtremeFlowBlend. Existing objectives and optimizer code are unchanged. The discharge floor is configurable in m³/s; the numerical default must be selected for the basin when zero flows matter. Optional reference_observed is copied and supplies fixed thresholds/scales. Tied quantiles give low-flow membership precedence; empty groups are skipped and remaining weights normalized.

Validation: Ruff lint and formatting passed; representative temporary assertions passed for a perfect fit, independently calculated loss, equal proportional offsets, zero flows, empty inputs, frozen reference scales/copy, and invalid configuration. The initial hand-calculation check had a middle-group mean typo (55 rather than 55.5); correcting the expected value passed without an implementation change. Initial mypy encountered an internal cache serialization error and flagged an existing unsupported configuration option; retry without caching completed and reported only two no-any-return errors in the existing PlainNSE and NSETopBlend methods (lines 80 and 108). No type errors were reported in ExtremeFlowBlend. These pre-existing typing issues were left unchanged.

## Proposed method-call examples
```python
Objectives.ExtremeFlowBlend.evaluate(df)
objective = ExtremeFlowBlend(reference_observed=train_df["obs_q_m3s"], discharge_floor=0.01)
objective.evaluate(test_df)
CN3SOptimizer(prec=prec, observed_q=q, model=model, objective=objective)
```
