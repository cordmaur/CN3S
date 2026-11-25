# Deploy-dev / deploy-test Makefile targets

## Goal
Both the devcontainer dev server and the standalone Docker container must work behind the
existing IIS rule `http://127.0.0.1:8000/{R:0}` (no IIS change).

## Changes
- `web/compose.yaml`: published port `127.0.0.1:${SHC_HOST_PORT:-8000}:8000` (was 18000).
- `Makefile`: `deploy-dev`, `deploy-test`, `deploy-test-stop`; existing targets and default
  `help` preserved (help column widened). Clear errors for busy port, missing docker,
  unset/nonexistent `SHC_DURATION_CURVES_HOST_DIR`.
- `web/README.md`: switching procedure, port conflict, host vs container paths.

## Verification
- `make` help; error paths of `deploy-test` (no docker in the devcontainer).
- `deploy-dev` with SHC_PORT=8123: HTTP 302 from /shc; second run refused (port in use).
- The standalone HTTP check expects the `/shc` redirect (302), not an arbitrary HTTP error.
- Simulated Docker and HTTP responses verified the 302 success and 500 failure paths.
- Not done: real Docker build/run (docker unavailable); IIS end-to-end.

## Proposed method-call examples
```bash
make                       # help
make deploy-dev            # devcontainer
export SHC_DURATION_CURVES_HOST_DIR="/mnt/e/.../data/CN3S/Exceedance"
make deploy-test           # host/WSL
make deploy-test-stop
```
