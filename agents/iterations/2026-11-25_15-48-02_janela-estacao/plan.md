# Janela Estação do CN3S

**Iteração encerrada e aprovada pelo usuário.** O [mockup HTML](mockup.html) registra a referência validada. A seleção muda para a nova estação após o servidor publicar o cadastro completo. No fechamento, a navegação passou a abrir o resumo salvo e a atualização de séries passou a ser manual.

## Fluxo proposto

1. O seletor abre a janela. Restaurar a estação indicada pela navegação ou a última seleção válida. Na primeira visita, apresentar “Selecione uma estação” e o botão **Adicionar estação**. No mockup, Valparaíso começa selecionada para permitir a comparação com a captura enviada.
2. Ao selecionar, mostrar a ficha e o mapa da mesma estação. Exibir nome, código ANA, cobacia, áreas do inventário e hidrográfica (km²), latitude e longitude (graus decimais), rio, município e UF quando disponíveis no inventário. Identificar valores ausentes. Enquadrar a bacia na escala regional, marcar a estação nas coordenadas observadas e situá-la em um mapa menor do Brasil.
3. Consultar as estatísticas automaticamente a cada seleção. Havendo um resumo salvo, mostrá-lo com data e hora enquanto chega o novo. Na primeira consulta, exibir o estado de carregamento. Apresentar séries diárias de cota e vazão por fonte e código, preservando início, fim, anos, anos efetivos, falhas e consistência. As abas alternam a variável sem iniciar outra consulta. Em falha, informar o problema junto às séries e identificar a data do último resumo válido.
4. **Adicionar estação** abre um diálogo com o código ANA. Digitar ou cancelar mantém a estação em exibição. Ao confirmar, apresentar a etapa informada pelo servidor e uma barra por etapas concluídas. Rejeitar duplicatas no diálogo. Em falha, manter a seleção anterior, explicar a etapa que falhou e permitir corrigir ou tentar novamente. Em sucesso, incluir e selecionar a nova estação, fechar o diálogo e exibir sua ficha com o resumo recém-calculado.
5. Em tela estreita, empilhar seletor, ficha e mapa. A tabela pode rolar horizontalmente dentro da própria seção.

## Plano de implementação aprovado

- **Interface.** Concentrar a alteração em `web/templates/cn3s_estacao.html`, no trecho do seletor em `cn3s.html`, em `web/static/cn3s.js` e nos estilos existentes. Usar um diálogo HTML nativo, devolver o foco ao fechar e anunciar o andamento. Acionar o carregamento pela seleção inicial e pelo evento de troca.
- **Seleção e concorrência.** Hoje o polling compartilhado pode selecionar o código do trabalho ao concluir, e a consulta da ficha pode receber HTTP 409 enquanto há uma operação. Separar a conclusão de cadastro da conclusão de atualização. Manter a seleção navegável e guardar apenas a última seleção pendente durante o bloqueio. Reaproveitar a consulta em andamento para o mesmo código. Validar código e revisão da seleção antes de aplicar ficha, imagem, estatísticas ou erro. Ao concluir o trabalho antigo, atender a seleção atual, inclusive quando o usuário tiver voltado à estação anterior. Evitar reiniciar a operação ao renderizar seu resultado.
- **Estatísticas.** Reutilizar as operações autenticadas `overview` e `prepare` de `web/cn3s.py`, a gravação atômica e o cálculo de `Station.load_series()`. Recuperar o novo resumo por código após a conclusão. Tratar a ausência de `overview.json`, a falta de registros por variável e a indisponibilidade do SQL. Reaproveitar os campos de inventário disponíveis ao montar o resumo. Preservar a identidade de cada série, inclusive quando o código telemétrico difere do código ANA da estação selecionada.
- **Mapa.** Reproduzir primeiro a requisição autenticada de `basin.png` para 13710001 no ambiente que falha. Conferir status HTTP, tipo da resposta, exceção do servidor, leitura do GeoParquet, CRS, arquivos auxiliares do shapefile e montagem de `SHC_STATES_PATH`. A captura sozinha não identifica a causa. A geometria dessa estação existe no volume local, embora falte o resumo com coordenadas. Carregar o polígono independentemente do resumo e inserir o marcador ao obter coordenadas válidas. Verificar também o formato legado encontrado no volume (`watershed.parquet` e chaves de área antigas). Distinguir ausência de bacia de ausência de fundo cartográfico.
- **Contexto cartográfico.** O mockup mostra limites do IBGE já disponíveis no projeto, enquadramento regional e localizador nacional. Se for desejado um fundo com rios, cidades e relevo, avaliar Contextily na validação visual. Nesse caso, alinhar o CRS da geometria e dos tiles, manter a atribuição do provedor e usar o fundo local se os tiles estiverem indisponíveis. A escolha do fundo é independente do diagnóstico da imagem quebrada.
- **Cadastro.** Reutilizar o trabalho assíncrono de preparação e seu diretório temporário. Informar avanço real entre inventário, delimitação da bacia, consulta das séries e publicação. Selecionar o novo código somente após a publicação bem-sucedida.

## Critérios de aceite da implementação

- Abrir sem seleção, restaurar uma seleção e trocar rapidamente A → B → A durante uma consulta. Conferir identidade, mapa, estatísticas, mensagens de erro e ausência de consultas em ciclo.
- Abrir uma estação antiga sem resumo, outra com resumo e uma sem observações em uma das variáveis. Conferir a atualização automática, as unidades e os valores contra as estatísticas por fonte. Simular falha SQL com e sem resumo salvo.
- Verificar a bacia real de Valparaíso e outra bacia de extensão diferente. Testar separadamente coordenadas ausentes, limites estaduais indisponíveis e geometria ausente. Verificar o PNG e seu enquadramento no ambiente onde a falha foi observada.
- Conferir cancelamento, duplicata, falha e sucesso do cadastro. Durante a criação, o código da ficha permanece o anteriormente selecionado. Ao concluir, ficha, mapa e séries passam juntos à nova estação.
- Conferir teclado, tela estreita e seleção ao navegar para Calibrar Estação e Previsão. Executar checagens do JavaScript e, nos arquivos Python modificados, Ruff completo, formatação e mypy estrito.

## Registro do planejamento

Revisados os planos da prova de conceito e da divisão em três etapas, o template de Estação, o carregamento no navegador e as rotas de mapa, resumo e operações. O HTML é autocontido. Os mapas usam geometrias locais das bacias, limites IBGE de 2022 e pontos do inventário ANA de agosto de 2023. Rio e município também vêm desse inventário. As áreas usam os metadados locais. A tabela usa valores ilustrativos e o cadastro simula Belo Oriente (56719998) apenas na memória da página.

No Chromium, foram verificados a troca rápida de seleção, o carregamento da imagem, a alternância de variável, a duplicata, o cancelamento, a seleção vazia e o cadastro com progresso seguido da seleção automática em tela estreita. A aplicação e as pastas das estações não foram modificadas. A reprodução da falha na rota de mapa e a consulta institucional estão previstas para a implementação.

## Registro da implementação

- A página Estação usa um seletor, ficha com inventário expansível, mapa regional e localizador do Brasil. A seleção acompanha a URL e a navegação. As abas de cota e vazão mostram separadamente o código de cada fonte e indicam cobertura ausente.
- A seleção consulta os registros diários com o conector do usuário, sem reutilizar resultados SQL antigos. O resumo salvo continua visível com sua data durante a atualização e em caso de falha. A leitura da ficha independe do bloqueio do trabalho científico. O navegador descarta respostas de seleções anteriores e acompanha o trabalho em curso para o mesmo código.
- O diálogo de cadastro acompanha as etapas reais do servidor. A pasta temporária é preparada no mesmo volume das estações e publicada por renomeação após o sucesso. O cadastro usa o resumo já produzido ao selecionar a nova estação.
- Diagnóstico reproduzido na rota autenticada de Valparaíso (13710001). O erro HTTP 500 ocorreu durante a leitura do shapefile estadual porque o binário local de Pyogrio falhou ao importar. O polígono da bacia estava íntegro. A rota passou a retornar PNG com HTTP 200 nesse ambiente e no ambiente com o driver funcional. O localizador e o fundo de contingência usam a malha estadual IBGE de 2022 incluída com a aplicação. A leitura da bacia contempla os arquivos atuais e legados.
- Verificação local em Chromium com geometrias reais e cópias temporárias das estações. Foram exercitados seleção inicial vazia, troca rápida durante consulta, alternância de variável, série sem observações, falha com e sem resumo, mapa sem shapefile regional, bacia ausente, duplicata, cancelamento, falha de cadastro seguida de sucesso, progresso, visualização em tela estreita e navegação entre etapas. Os provedores SQL e BHO do cadastro foram substituídos na verificação. A obtenção de dados com a conta institucional e o ambiente publicado não foram exercitados.
- Ruff completo, formatação, mypy estrito e verificação de sintaxe JavaScript aprovados.

## Correção da ficha e do andamento das séries

1. Conferir no Hidro as linhas de Marabá (29050000) e da estação 13300000. Reproduzir a leitura do inventário com a geometria binária fornecida pelo SQL.
2. Resolver os códigos de município, estado e rio nas tabelas de referência e usar as coordenadas observadas da tabela Estacao. Representar campos binários em hexadecimal no inventário completo. Disponibilizar a ficha assim que a leitura terminar, preservando a última estatística durante a consulta diária.
3. Exibir uma barra indeterminada na seção de séries da seleção atual. Encerrá-la em sucesso, falha ou mudança de seleção. Verificar o cadastro e a atualização usando diretórios temporários.

**Verificação da correção.** O SQL real confirmou que a coluna geom_wkb contém bytes. O cadastro integral de 13300000 foi executado com o inventário, as séries Hidro/Telemetria e a BHO reais em uma pasta temporária. A ficha retornou Sena Madureira/AC, rio Iaco, latitude −9,3744° e longitude −68,7239°. No Chromium, a atualização real de Marabá exibiu a ficha enquanto o progresso estava indeterminado e depois salvou as duas linhas por fonte. Uma falha de séries induzida preservou os campos e a data anterior e encerrou a barra. O diálogo de cadastro também foi verificado durante a fase de consulta e após falha. O acesso SQL da verificação local usou o conector do projeto; a aplicação segue usando a credencial delegada do visitante. Ruff, formatação, mypy estrito e sintaxe JavaScript passaram.

## Fechamento da iteração

1. Ao selecionar ou reabrir a estação, ler somente a ficha e o resumo salvos. Mostrar a data da última consulta bem-sucedida ou indicar a ausência de estatísticas. O botão **Atualizar estatísticas** inicia a consulta com indicador de atividade. O cadastro continua preparando o primeiro resumo.
2. Reutilizar o cache de consultas já implementado nos conectores. Na aplicação web, ligar o cadastro ao cache compartilhado no processo e isolado por credencial e banco. A atualização manual busca os dados nas fontes e renova as entradas do cache para consultas idênticas posteriores, incluindo séries e inventários.
3. Na implementação anterior à adoção da 50k, a delimitação usava as camadas de áreas e trechos da BHO 2017 5k (campo dsversao: BHO bho_2017_v_01_05_5k de 2018-06-20). A referência local à base nacional terminava com a função de preparo; agora é removida logo após a gravação da bacia, antes da consulta das séries. Apenas a geometria dissolvida da estação é usada ao reabrir o mapa.

Verificação de fechamento em Chromium com consultas controladas: navegar A → B → A não iniciou operação de séries. Um clique iniciou uma única atualização mesmo com saída e retorno durante a consulta. A data foi renovada no sucesso, e a falha permitiu nova tentativa. Verificada a reutilização do cache entre conectores por consulta e credencial, inclusive sua renovação no modo de atualização.

## Atualização da base de drenagem

- Usar o GeoParquet de áreas BHO 2017 50k no cadastro web e no notebook 01. Preservar chamadas existentes que recebem uma instância de Hydrography.
- Identificar o polígono que contém a estação, selecionar as contribuições a montante na mesma versão Otto e dissolvê-las. Somar as áreas locais nuareacont, em km². Registrar dsversao na geometria salva. O Parquet nacional sai de escopo ao retornar a bacia dissolvida.
- Conferência na base montada: as áreas e os trechos possuem cocursodag e cobacia. A área acumulada nuareamont existe apenas nos trechos. Na comparação por cotrecho e dsversao, os 816 polígonos sem código de curso têm área acumulada igual à sua própria contribuição. O caminho de cadastro lê somente as áreas. O teste consultou os trechos separadamente como referência.
- Verificados o notebook como JSON e suas células de código, a distinção de polígonos isolados com o mesmo código Otto em versões diferentes e a mensagem para uma estação fora da cobertura. Ruff completo e formatação passaram nos quatro arquivos Python envolvidos. O mypy estrito conjunto reproduziu os oito apontamentos de tipagem já presentes no baseline em station.py e web/cn3s.py.

Validação em Marabá (29050000): o cadastro com SQL real concluiu em pasta temporária contendo apenas o Parquet de áreas. A área de 696.359,029529 km² coincidiu com nuareamont do trecho 63911 na base 50k; a geometria gravada é válida. Em uma execução local por configuração, somente a etapa espacial (leitura, seleção e dissolução) passou de 94.17 s e 8.27 GiB de pico RSS no processo 5k para 18.39 s e 2.34 GiB na 50k.

## Exemplos propostos de chamadas

Fluxo HTTP relativo ao prefixo do módulo, com os mecanismos de sessão e CSRF já empregados pela aplicação.

```text
GET  stations/13710001?view=station → ficha e último resumo disponível
GET  stations/13710001/basin.png   → bacia da seleção atual
POST stations/13710001/overview    → botão Atualizar estatísticas
GET  operations/<id>               → acompanhar a operação
GET  stations/13710001?view=station → ler o resumo atualizado uma vez

POST stations/56719998/prepare     → cadastro iniciado no diálogo
GET  operations/<id>               → exibir a etapa de criação
GET  stations/56719998?view=station → selecionar e ler o resultado após sucesso
```

Preparo de uma estação a partir dos polígonos 50k:

```python
watersheds = Path("/data/Geospatial_BR_Data/Hidrografia/BHO_2017_50k/geoft_bho_2017_50k_area_drenagem.parquet")
station.prepare_station(watersheds, output_dir=stations_dir)
```
