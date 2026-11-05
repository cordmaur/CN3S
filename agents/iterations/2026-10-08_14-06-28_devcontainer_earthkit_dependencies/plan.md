# Configure Earthkit development-container dependencies

## Proposed changes

1. Add `earthkit`, the exact requirement `cftime==1.6.6`, and the Git-based
   `merge-downloader` dependency pinned to the `databricks2` branch to the project
   dependencies in `pyproject.toml`. This keeps the dependencies versioned with
   the package and makes them available in editable installs.
2. Update `.devcontainer/devcontainer.json` so its existing editable install
   invokes pip with `--ignore-installed`. This allows pip to overlay the
   Earthkit-required NumPy version without attempting to remove the
   Debian-managed NumPy distribution. Remove the now-duplicated direct
   `merge-downloader` installation.
3. Keep the post-create command concise by retaining `pyproject.toml` as the
   sole requirements source; no separate requirements file is needed.
4. Rebuild the dev container or execute the post-create command, then verify
   `import earthkit` and `import cftime` and confirm that
   `cftime.__version__ == "1.6.6"`.

## Proposed method-call examples

```sh
pip install -e . --ignore-installed --break-system-packages
```

The Git dependency is declared using the PEP 508 form:

```toml
merge-downloader @ git+https://github.com/cordmaur/merge-downloader.git@databricks2
```

```python
import cftime
import earthkit

assert cftime.__version__ == "1.6.6"
```
