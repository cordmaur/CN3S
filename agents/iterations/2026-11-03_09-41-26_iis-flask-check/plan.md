# IIS to Flask connection check

## Plan and session record

- Add a small Flask endpoint to the existing project and optional web dependencies.
- Use Gunicorn and VS Code port forwarding for an initial devcontainer check.
- Document an IIS reverse-proxy rule for the test path and remote verification.
- Verify the endpoint locally; IIS and cross-computer access require the user's server.

The Gunicorn endpoint returned HTTP 200 in a local check. IIS forwarding and
access from another computer still need verification on the Windows server.

## Method-call example

```text
GET /cn3s-test
```
