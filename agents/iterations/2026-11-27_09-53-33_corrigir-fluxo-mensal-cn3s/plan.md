# Corrigir o fluxo mensal do CN3S

Status: implementado e verificado localmente.

A ficha de Estação e a tela de Previsão deixavam de iniciar quando o servidor entregava templates antigos com o JavaScript de `f5a1236`. O Flask agora recarrega templates modificados, e o endereço do script CN3S inclui uma versão derivada do conteúdo. Os novos controles de dados mensais e o atalho de chuva são opcionais para a inicialização de páginas antigas. Ao retomar uma atualização mensal em andamento, Estação acompanha o trabalho antes de consultar a cobertura, evitando disputar o bloqueio do servidor.

A verificação no Chromium reproduziu o erro com HTML antigo e JavaScript de `f5a1236`. Com a correção, a ficha e a previsão abriram com o HTML antigo, e os controles novos apareceram quando os templates foram atualizados sem reiniciar o servidor de teste. Com dados temporários e gravação simulada, foram verificados os atalhos de Calibrar e Previsão, a retomada após recarregar a página com uma operação ativa, a atualização das duas fontes e a habilitação da previsão após preencher a chuva faltante. Também foram conferidos os catálogos reais de Lábrea, Beruri e Marabá. A previsão de um mês para Marabá foi calculada com o MERGE e o CDS de novembro de 2026. A comparação opcional de vazão via SQL foi substituída nesse teste.

O fluxo usa a interface existente e não acrescenta métodos públicos.

Ruff passou nos dois arquivos Python alterados. O mypy apontou `no-any-return` no retorno de `login.require_login()` em `web/app.py`. O mesmo erro foi reproduzido com o arquivo de HEAD.
