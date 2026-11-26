# Diagnóstico do 502 entre IIS e Gunicorn

## Roteiro e resultados

1. Comparar a rota de login diretamente no devcontainer com a URL do IIS. O Gunicorn em execução respondeu HTTP 200 no loopback e no endereço da interface do devcontainer. A raiz /shc/ retornou HTTP 302 para /shc/login. O IIS retornou 502.3 nas duas rotas com o código 0x80072efd (12029, ERROR_WINHTTP_CANNOT_CONNECT).
2. Testar o reload em uma instância isolada, com a mesma aplicação e um worker. Após uma alteração no arquivo monitorado, o worker foi substituído e o login voltou a retornar 200 em 5,28 segundos. Durante a troca, nove sondas com timeout de 350 ms falharam. A instância do usuário seguiu em execução.
3. Confirmar a conexão a partir do Windows que hospeda o IIS. Esse loopback não está disponível no devcontainer. Se o teste direto no Windows falhar, verificar na aba Ports do VS Code se o encaminhamento do devcontainer aponta para 127.0.0.1:8000 no host. Se responder e o IIS continuar retornando 502.3, conferir o alvo efetivo do URL Rewrite/ARR.

O erro persistente foi reproduzido após o Gunicorn estar atendendo normalmente. O trecho entre o IIS e seu destino configurado ainda requer confirmação no host. [Erros WinHTTP](https://learn.microsoft.com/en-us/windows/win32/winhttp/error-messages)

## Chamadas de verificação

No devcontainer:

```bash
curl --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/shc/login
```

No Windows que hospeda o IIS:

```powershell
curl.exe --noproxy "*" -v http://127.0.0.1:8000/shc/login
```
