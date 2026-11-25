# Reuse the standalone image

## Plan
- Start the existing local `web` image without rebuilding or pulling on each
  `deploy-test`; preserve the existing directory checks and HTTP verification.
- Add an explicit build target for first use and source changes.
- Document the build, start and restart workflow.
- Check the Make commands and failure behavior without starting Docker.

## Verification
- Simulated Docker verified the build command, start-stop-start sequence and
  startup failure reporting; `make` help and `git diff --check` passed.
- Docker is unavailable here, so the real image build and container restart
  could not be tested.

## Proposed command examples
```bash
make deploy-test-build
make deploy-test
make deploy-test-stop
make deploy-test
```
