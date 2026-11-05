# Add earthkit notebook install check

1. Locate the requested editable notebook cell.
2. Replace the cell with an `importlib.util.find_spec` check that invokes `%pip install earthkit` only when the package is unavailable.
   In Debian-managed environments, use pip's targeted `--ignore-installed numpy` option
   when installing `earthkit` so pip can install its required NumPy version without
   trying to uninstall the system-owned NumPy package.
3. Execute the cell to verify the notebook environment accepts the code.

## Proposed method-call example

```python
import importlib.util

if importlib.util.find_spec("earthkit") is None:
    %pip install --ignore-installed numpy earthkit
```
