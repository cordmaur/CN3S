# Document IIS access and diagnose remote connectivity

## Plan and session record

- Inspected the existing README, IIS rewrite screenshot, application and Compose configuration.
- Documented the reported devcontainer/Gunicorn → VS Code forwarding → IIS/ARR path, distinguishing it from the deployed Docker port.
- Added read-only diagnostics for client TCP and HTTP access, local forwarding, IIS bindings and IP restrictions, Windows firewall profiles and filters, and upstream networking.
- Consulted Microsoft documentation for IIS binding and Windows firewall behavior. No access to the Windows host or colleague's machine was available, so the actual cause and allowed source IPs remain unverified.
- Preserved unrelated existing changes. No application code changed.

## Command examples

```powershell
Test-NetConnection 172.20.28.3 -Port 80
curl.exe -v --noproxy "*" http://172.20.28.3/shc/permanencia
```
