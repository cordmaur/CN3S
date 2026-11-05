# Standalone Flask container

## Plan

- Build the existing Hello endpoint into a standalone image with the web extra.
- Use detached Docker Compose and loopback port 18000, separate from the
  working development port 8000.
- Switch the IIS port 80 exact-path rule after verifying Windows connectivity.
- Verify Mac access with VS Code closed; determine the host runtime before
  configuring Windows/WSL boot startup.

## Session record

- This devcontainer has no Docker CLI, so host deployment cannot run here.
- Added a build-context allowlist excluding local data and Azure login caches.
- Requested host Docker context and OS output to determine startup behavior.
- User confirmed context `default` and OS `Docker Desktop`. Detached Compose
  can remove the VS Code dependency while Desktop runs; unattended startup
  before Windows sign-in requires a different host-runtime arrangement.
- Verified Compose YAML syntax, build-context path, port mapping and restart
  setting; the CN3S wheel built successfully. Docker execution is unverified.
- Docker build, Windows connectivity, logoff and reboot checks remain pending.
- User subsequently confirmed the standalone container runs with
  `127.0.0.1:18000->8000/tcp` and works without VS Code forwarding. Reboot
  and logoff behavior remain unverified.
- Added the requested request-flow explanation at the beginning of web/README.md,
  including exact path matching, ARR forwarding and Docker port mapping.

## Method-call examples

```bash
docker compose -f web/compose.yaml up --build -d
curl -f http://127.0.0.1:18000/cn3s-test
```
