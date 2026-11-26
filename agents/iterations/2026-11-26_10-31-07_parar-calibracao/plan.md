# Limite de gerações e parada do treino CN3S

## Implementação

- O teto de 20 gerações vinha da prova de conceito. Manter 20 como valor inicial e aceitar de 1 a 1.000 no formulário e no servidor. Em ambos os modos o SciPy pode encerrar por convergência antes do máximo.
- **Parar treino** solicita uma parada ao fim da geração atual. A operação só aceita a solicitação da sessão que iniciou o treino. O callback guarda a geração e pede a parada via StopIteration, conforme a API do SciPy. O melhor resultado passa pelo cálculo final de métricas e fica em revisão com o motivo da parada. [Documentação do SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html)

## Registro da sessão

As mudanças foram preparadas em uma cópia isolada enquanto Lábrea treinava. Após a execução de Lábrea concluir em 46 gerações, os arquivos foram aplicados ao repositório. O Gunicorn recarregou e as rotas de login direta e via IIS responderam HTTP 200. Ruff, formatação, mypy estrito e sintaxe JavaScript passaram nos arquivos da iteração.

O teste no Chromium usou uma cópia temporária de Marabá, com máximo de 60 gerações. A parada encerrou o SciPy na segunda geração, exibiu a revisão e permitiu salvar o JSON com as quatro métricas, o gráfico e o motivo da parada.

## Exemplos de chamadas

```text
POST stations/13870000/calibrate {"start":"2000-01-01","end":"2026-10-01","maxiter":60}
POST operations/<treino>/stop   {}
GET  operations/<treino>
POST operations/<treino>/save   {}
```
