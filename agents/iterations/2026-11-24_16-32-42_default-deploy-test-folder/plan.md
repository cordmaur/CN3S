# Default standalone data folder

## Plan
- Default the Makefile host data directory to the devcontainer mount's host path
  plus `CN3S/Exceedance`, while allowing explicit overrides.
- Document that the folder must exist and direct Compose commands still require
  the variable in the shell.
- Verify default, override and missing-directory behavior without starting Docker.

## Verification
- Verified the exported default and a space-containing override.
- Simulated Docker deployment with an existing path containing spaces and
  confirmed a missing path is rejected. Docker is unavailable in this environment.
- Confirmed `make` displays help and the changed tracked files pass `git diff --check`.

## Proposed command examples
```bash
make deploy-test
SHC_DURATION_CURVES_HOST_DIR="/another/host/path" make deploy-test
make deploy-test-stop
```
