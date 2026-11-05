/* Browser interactions for SHC. Scientific processing stays in Python. */
(() => {
  const $ = selector => document.querySelector(selector);
  const csrf = $('meta[name="csrf-token"]').content;
  const title = text => text.toLocaleLowerCase('pt-BR').replace(/(^|\s)\S/g, c => c.toLocaleUpperCase('pt-BR'));
  function notify(message) {
    $('#toast').textContent = message;
    $('#toast').hidden = false;
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => { $('#toast').hidden = true; }, 7000);
  }
  async function api(url, payload) {
    const response = await fetch(url, payload === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(payload),
    });
    if (!response.headers.get('Content-Type')?.includes('application/json')) {
      throw new Error('Resposta inválida do servidor. Atualize a página e tente novamente.');
    }
    const data = await response.json();
    if (data.login_required) { window.location.assign('/shc/login'); throw new Error(data.error); }
    if (!response.ok) throw new Error(data.error || 'Não foi possível concluir a solicitação.');
    return data;
  }
  const login = $('[data-login-status]');
  if (login && ['starting', 'pending'].includes(login.dataset.loginStatus)) {
    const initial = login.dataset.loginStatus;
    async function checkLogin() {
      try {
        const state = await api('/shc/login/status');
        if (state.status === 'signed_in') { window.location.replace('/shc/home'); return; }
        if (state.status !== initial) { window.location.replace('/shc/login'); return; }
        $('#login-error').textContent = '';
      } catch (error) { $('#login-error').textContent = 'Não foi possível verificar a entrada. Tentando novamente…'; }
      setTimeout(checkLogin, 2000);
    }
    setTimeout(checkLogin, 1000);
  }
  if (!$('#station-data')) return;

  const catalog = JSON.parse($('#station-data').textContent);
  let listLimit = 50;
  let activeStation = null;
  let dirty = false;
  let busy = false;
  let analysis = null;
  let editingStation = false;
  const root = '/shc/permanencia';
  function showError(message) {
    $('#workspace-error').textContent = message;
    $('#workspace-error').hidden = !message;
  }
  function setBusy(value) {
    busy = value;
    $('#operation-progress').hidden = !value;
    document.querySelectorAll('#limit-rows input, #limit-rows button').forEach(control => { control.disabled = value; });
    for (const id of ['new-station', 'edit-station', 'refresh', 'save-limits', 'add-limit', 'calculate-insert']) {
      $('#' + id).disabled = value;
    }
  }
  async function pollOperation(id, onDone) {
    try {
      const job = await api(`${root}/operacoes/${id}`);
      if (job.status === 'running') {
        $('#operation-phase').textContent = job.phase;
        if (!$('#insert-progress').hidden) $('#calculation-phase').textContent = job.phase;
        setTimeout(() => pollOperation(id, onDone), 1000);
        return;
      }
      setBusy(false);
      if (job.status === 'failed') throw new Error(job.error);
      onDone(job.result);
    } catch (error) {
      setBusy(false);
      showError(error.message);
      if ($('#insert-dialog').open) {
        $('#insert-progress').hidden = true;
        $('#review-step').hidden = !analysis;
        $('#consult-step').hidden = Boolean(analysis);
        $('#insert-error').textContent = error.message;
        $('#insert-error').hidden = false;
      }
    }
  }
  async function operate(url, payload, onDone) {
    if (busy) { notify('Aguarde a operação atual terminar.'); return; }
    setBusy(true);
    showError('');
    $('#insert-error').hidden = true;
    $('#operation-phase').textContent = 'Preparando consulta…';
    try {
      const result = await api(url, payload);
      pollOperation(result.operation_id, onDone);
    } catch (error) { setBusy(false); showError(error.message); $('#insert-error').textContent = error.message; $('#insert-error').hidden = false; }
  }
  function renderList() {
    const query = $('#search').value.toLocaleLowerCase('pt-BR');
    const matching = catalog.filter(item => `${item.code} ${item.name}`.toLocaleLowerCase('pt-BR').includes(query));
    const list = $('#station-list');
    list.replaceChildren();
    for (const item of matching.slice(0, listLimit)) {
      const button = document.createElement('button');
      button.className = 'station' + (activeStation?.code === item.code ? ' selected' : '') + (item.available ? '' : ' unavailable');
      button.title = `${item.code} / ${item.name}${item.available ? '' : ' — ' + item.error}`;
      button.setAttribute('aria-pressed', String(activeStation?.code === item.code));
      const code = document.createElement('code'); code.textContent = item.code;
      const separator = document.createElement('span'); separator.className = 'station-separator'; separator.textContent = '/';
      const name = document.createElement('span'); name.className = 'station-name'; name.textContent = title(item.name) + (item.available ? '' : ' · indisponível');
      button.append(code, separator, name);
      button.onclick = () => item.available ? openStation(item.code) : showError(item.error);
      list.append(button);
    }
    const count = document.createElement('p'); count.className = 'station-count-note';
    count.textContent = matching.length ? `${Math.min(listLimit, matching.length)} de ${matching.length} estações` : 'Nenhuma estação encontrada.';
    list.append(count);
    if (matching.length > listLimit) {
      const more = document.createElement('button'); more.className = 'quiet'; more.textContent = 'Carregar mais 50';
      more.onclick = () => { listLimit += 50; renderList(); }; list.append(more);
    }
    $('#station-count').textContent = catalog.length;
  }
  function discardChanges() {
    return !dirty || window.confirm('Há limites não salvos. Deseja descartar as alterações?');
  }
  function addLimit(container, label = '', value = '', changed = () => {}) {
    const row = document.createElement('tr');
    const nameCell = document.createElement('td');
    const name = document.createElement('input'); name.value = label; name.required = true; name.placeholder = 'Nome do limite'; name.setAttribute('aria-label', 'Nome do limite');
    nameCell.append(name);
    const valueCell = document.createElement('td'); valueCell.className = 'value';
    const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.required = true; input.value = value; input.setAttribute('aria-label', 'Cota em centímetros'); valueCell.append(input);
    const removeCell = document.createElement('td'); removeCell.className = 'remove';
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'danger'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remover limite');
    remove.onclick = () => { row.remove(); changed(); }; removeCell.append(remove);
    name.oninput = input.oninput = changed;
    row.append(nameCell, valueCell, removeCell); container.append(row);
  }
  function readLimits(container) {
    const values = [];
    for (const row of container.rows) {
      const inputs = row.querySelectorAll('input');
      if (![...inputs].every(input => input.reportValidity())) return null;
      const name = inputs[0].value.trim(), value = Number(inputs[1].value);
      if (!name || !Number.isFinite(value) || values.some(item => item.name === name)) {
        notify('Informe nomes distintos e valores numéricos válidos para os limites.'); return null;
      }
      values.push({ name, value });
    }
    return values;
  }
  function markDirty() { dirty = true; $('#save-note').textContent = 'Alterações não salvas. O salvamento será compartilhado com toda a equipe.'; }
  // Load the graph library only when needed; catalog rendering never waits for it.
  let plotlyReady = null;
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const timer = setTimeout(() => fail(new Error(`Tempo excedido ao carregar ${url}`)), 30000);
      function fail(error) {
        clearTimeout(timer); script.remove(); reject(error);
      }
      script.src = url;
      script.onload = () => { clearTimeout(timer); resolve(); };
      script.onerror = () => fail(new Error(`Falha ao carregar ${url}`));
      document.head.append(script);
    });
  }
  function ensurePlotly() {
    if (!plotlyReady) {
      plotlyReady = (async () => {
        if (!window.Plotly) await loadScript('/shc/static/vendor/plotly-basic-3.1.0.min.js');
        if (!window.Plotly?.react) throw new Error('A biblioteca Plotly não iniciou após o carregamento.');
        await loadScript('/shc/static/vendor/plotly-locale-pt-br-3.1.0.js');
      })().catch(error => {
        plotlyReady = null;
        console.error('SHC: carregamento do Plotly', error);
        throw new Error('Não foi possível carregar o gráfico interativo. Tente novamente.');
      });
    }
    return plotlyReady;
  }
  let interactiveData = null;
  let chartRequest = 0;
  let chartError = null;
  async function showChartMode() {
    const request = ++chartRequest;
    const station = activeStation;
    if (!station) return;
    const interactive = $('input[name=chart-mode]:checked').value === 'plotly';
    $('#interactive-chart').hidden = !interactive;
    $('#chart').hidden = interactive;
    $('#interactive-loading').hidden = !interactive;
    if (!interactive) return;
    try {
      const [, figure] = await Promise.all([ensurePlotly(), interactiveData || api(`${root}/graficos/${station.chart_id}.json`)]);
      if (request !== chartRequest || activeStation?.chart_id !== station.chart_id) return;
      interactiveData = figure;
      await Plotly.react($('#interactive-chart'), figure.data, figure.layout, {
        responsive: true, locale: 'pt-BR', displaylogo: false, scrollZoom: true,
        toImageButtonOptions: { format: 'png', filename: `SHC_cotas_${station.code}` },
      });
      if ($('#workspace-error').textContent === chartError) showError(station.warning || '');
      chartError = null;
    } catch (error) {
      if (request !== chartRequest) return;
      $('input[name=chart-mode][value=matplotlib]').checked = true;
      $('#interactive-chart').hidden = true; $('#chart').hidden = false;
      chartError = error.message + ' Exibindo a imagem Matplotlib.';
      showError(chartError);
    } finally {
      if (request === chartRequest) $('#interactive-loading').hidden = true;
    }
  }
  document.querySelectorAll('input[name=chart-mode]').forEach(input => { input.onchange = showChartMode; });
  function displayChart(data) {
    if ($('#insert-dialog').open) $('#insert-dialog').close();
    if (data.saved_only) {
      dirty = false; activeStation = null;
      $('#station-details').hidden = true; $('#initial-panel').hidden = false;
      showError(data.warning); renderList(); return;
    }
    activeStation = data; dirty = false; interactiveData = null;
    $('#initial-panel').hidden = true; $('#station-details').hidden = false;
    $('#station-title').textContent = title(data.name); $('#station-code').textContent = 'Estação ' + data.code;
    $('#source-label').textContent = 'Fonte: ' + data.source.toLocaleUpperCase('pt-BR');
    $('#method-label').textContent = data.method === 'cota/vazao' ? 'Cota a partir da vazão' : 'Cota observada';
    $('#period-label').textContent = data.description;
    const image = `${root}/graficos/${data.chart_id}.png`;
    $('#chart').src = image; $('#chart').alt = 'Gráfico anual de cotas da estação ' + data.name;
    $('#download').href = image + '?download=1';
    $('.image-note').textContent = data.latest ? 'Última observação telemétrica: ' + data.latest : 'Sem observações telemétricas recentes. O gráfico apresenta as referências históricas.';
    $('#limit-rows').replaceChildren();
    Object.entries(data.thresholds).forEach(([name, value]) => addLimit($('#limit-rows'), name, value, markDirty));
    $('#save-note').textContent = 'As alterações salvas serão compartilhadas com toda a equipe.';
    if (!catalog.some(item => item.code === data.code)) {
      catalog.push({ code: data.code, name: data.name, available: true, error: '' });
      catalog.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));
    }
    showError(data.warning || '');
    if (data.requested_method === 'from_discharge' && data.method !== 'cota/vazao') notify('A curva foi calculada diretamente das cotas: houve troca automática do método solicitado.');
    renderList(); showChartMode();
  }
  function openStation(code, refresh = false) {
    if (busy || !discardChanges()) return;
    operate(`${root}/estacoes/${code}/atualizar`, { refresh }, displayChart);
  }
  $('#chart').onerror = () => { if (activeStation) showError('O gráfico está indisponível ou expirou. Atualize as observações e entre novamente se necessário.'); };
  $('#search').oninput = () => { listLimit = 50; renderList(); };
  $('#add-limit').onclick = () => { addLimit($('#limit-rows'), '', '', markDirty); markDirty(); };
  $('#refresh').onclick = () => { if (activeStation) openStation(activeStation.code, true); };
  $('#save-limits').onclick = () => {
    if (!activeStation) return;
    const thresholds = readLimits($('#limit-rows')); if (thresholds === null) return;
    operate(`${root}/estacoes/${activeStation.code}/limites`, { thresholds, revision: activeStation.revision }, data => {
      displayChart(data); if (!data.saved_only) notify('Limites salvos para toda a equipe.');
    });
  };

  function insertionStep(step) {
    $('#consult-step').hidden = step !== 'consult'; $('#review-step').hidden = step !== 'review'; $('#insert-progress').hidden = step !== 'progress';
    $('#consult-step-label').classList.toggle('active', step === 'consult'); $('#review-step-label').classList.toggle('active', step !== 'consult');
    $('#insert-dialog').scrollTop = 0;
  }
  function corrections(validate = false) {
    const rows = [];
    for (const row of $('#sanitization-rows').rows) {
      const variable = row.querySelector('select').value, day = row.querySelector('[type=date]'), value = row.querySelector('[type=number]');
      if (!day.value || value.value === '' || !Number.isFinite(Number(value.value))) {
        if (validate) { day.reportValidity(); value.reportValidity(); return null; } continue;
      }
      if (rows.some(item => item.variable === variable && item.date === day.value)) {
        if (validate) { notify('Informe somente uma correção por variável e data.'); return null; } continue;
      }
      rows.push({ variable, date: day.value, value: Number(value.value) });
    }
    return rows;
  }
  function correctionPreview() {
    const mapping = {};
    for (const row of corrections()) (mapping[row.variable] ??= {})[row.date] = row.value;
    $('#sanitization-preview').textContent = JSON.stringify(mapping, null, 2);
    $('#no-sanitization').hidden = $('#sanitization-rows').rows.length > 0;
  }
  function addCorrection(variable = 'cota', day = '', value = '') {
    const row = document.createElement('tr');
    row.innerHTML = '<td><select aria-label="Variável a corrigir"><option value="cota">Cota (cm)</option><option value="vazao">Vazão (m³/s)</option></select></td><td><input type="date" required aria-label="Data da observação"></td><td><input type="number" step="any" required placeholder="Valor em cm" aria-label="Valor substituto em centímetros"></td><td class="remove"><button type="button" class="danger" aria-label="Remover correção">×</button></td>';
    row.querySelector('button').onclick = () => { row.remove(); correctionPreview(); };
    row.querySelector('select').onchange = event => {
      const input = row.querySelector('[type=number]');
      input.placeholder = event.target.value === 'cota' ? 'Valor em cm' : 'Valor em m³/s';
      input.setAttribute('aria-label', input.placeholder); correctionPreview();
    };
    row.querySelectorAll('input').forEach(input => { input.oninput = correctionPreview; });
    row.querySelector('select').value = variable;
    row.querySelector('[type=date]').value = day;
    row.querySelector('[type=number]').value = value;
    row.querySelector('[type=number]').placeholder = variable === 'cota' ? 'Valor em cm' : 'Valor em m³/s';
    row.querySelector('[type=number]').setAttribute('aria-label', row.querySelector('[type=number]').placeholder);
    $('#sanitization-rows').append(row); correctionPreview();
  }
  function reviewAnalysis(data) {
    analysis = data; editingStation = Boolean(data.editing);
    if (!$('#insert-dialog').open) $('#insert-dialog').showModal();
    $('#new-code').value = data.code;
    $('#new-code').readOnly = Boolean(data.editing);
    $('#insert-title').textContent = data.editing ? 'Editar estação' : 'Inserir nova estação';
    $('#change-code').hidden = $('#back-to-code').hidden = Boolean(data.editing);
    if (data.editing) {
      $('#review-form').reset();
      const settings = data.settings;
      const method = settings.requested_method || (settings.method === 'cota/vazao' ? 'from_discharge' : 'direct');
      $(`input[name=calculation-method][value=${method}]`).checked = true;
      $('#new-limits').replaceChildren();
      Object.entries(settings.thresholds || {}).forEach(([name, value]) => addLimit($('#new-limits'), name, value));
      $('#sanitization-rows').replaceChildren();
      Object.entries(settings.sanitization || {}).forEach(([variable, replacements]) => {
        Object.entries(replacements).forEach(([day, value]) => addCorrection(variable, day, value));
      });
      correctionPreview();
    }
    $('#review-name').textContent = data.name; $('#review-code').textContent = 'Estação ' + data.code;
    $('#existing-station-notice').hidden = !data.existing;
    $('#existing-station-notice').textContent = data.editing
      ? 'Ao recalcular e salvar, a curva histórica, as correções e os limites serão atualizados para toda a equipe.'
      : 'Esta estação já está cadastrada. Abra a curva existente sem recalcular os resultados.';
    $('#calculation-settings').disabled = data.existing && !data.editing;
    $('#calculate-insert').textContent = data.editing ? 'Recalcular e salvar' : data.existing ? 'Abrir estação existente' : 'Calcular e inserir';
    $('#stats-rows').replaceChildren();
    for (const item of data.stats) {
      const row = document.createElement('tr');
      for (const value of [String(item.code), item.source, ...item.cota, ...item.vazao]) {
        const cell = document.createElement('td'); cell.textContent = value === null ? '—' : typeof value === 'number' ? value.toLocaleString('pt-BR') : value; row.append(cell);
      }
      $('#stats-rows').append(row);
    }
    insertionStep('review');
  }
  $('#new-station').onclick = () => {
    if (!discardChanges()) return;
    editingStation = false;
    $('#insert-title').textContent = 'Inserir nova estação'; $('#new-code').readOnly = false;
    $('#change-code').hidden = $('#back-to-code').hidden = false;
    analysis = null; $('#new-code').value = ''; $('#review-form').reset(); $('#calculation-settings').disabled = false;
    $('#new-limits').replaceChildren(); $('#sanitization-rows').replaceChildren(); correctionPreview();
    $('#insert-error').hidden = true; insertionStep('consult'); $('#insert-dialog').showModal();
  };
  $('#edit-station').onclick = () => {
    if (!activeStation || busy || !discardChanges()) return;
    analysis = null; editingStation = true;
    $('#change-code').hidden = $('#back-to-code').hidden = true;
    $('#insert-title').textContent = 'Editar estação';
    $('#new-code').value = activeStation.code; $('#new-code').readOnly = true;
    $('#insert-error').hidden = true;
    $('#calculation-summary').textContent = 'Carregando estatísticas e configurações salvas. A curva será substituída para toda a equipe somente após a confirmação.';
    insertionStep('progress'); $('#insert-dialog').showModal();
    operate(`${root}/estacoes/analisar`, { code: activeStation.code, editing: true }, reviewAnalysis);
  };
  $('#consult-form').onsubmit = event => {
    event.preventDefault(); if (busy) return;
    analysis = null; $('#review-form').reset(); $('#new-limits').replaceChildren(); $('#sanitization-rows').replaceChildren(); correctionPreview();
    const code = Number($('#new-code').value);
    insertionStep('progress'); $('#calculation-phase').textContent = 'Consultando séries e preparando estatísticas…';
    operate(`${root}/estacoes/analisar`, { code, editing: editingStation }, reviewAnalysis);
  };
  $('#change-code').onclick = $('#back-to-code').onclick = () => { analysis = null; insertionStep('consult'); };
  $('#add-sanitization').onclick = () => addCorrection();
  $('#new-add-limit').onclick = () => addLimit($('#new-limits'));
  for (const id of ['close-dialog', 'cancel-insert', 'close-progress']) $('#' + id).onclick = () => $('#insert-dialog').close();
  $('#review-form').onsubmit = event => {
    event.preventDefault(); if (!analysis || busy) return;
    if (analysis.existing && !analysis.editing) { $('#insert-dialog').close(); openStation(analysis.code); return; }
    const rows = corrections(true), thresholds = readLimits($('#new-limits'));
    if (rows === null || thresholds === null) return;
    const method = $('input[name=calculation-method]:checked').value;
    $('#calculation-summary').textContent = `Estação ${analysis.code} · ${rows.length} correção(ões) pontual(is) · ${thresholds.length} limite(s).`;
    insertionStep('progress');
    operate(`${root}/estacoes`, { code: analysis.code, analysis_id: analysis.analysis_id, editing: Boolean(analysis.editing), method, corrections: rows, thresholds }, displayChart);
  };
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  renderList();
  const previous = JSON.parse($('#operation-data').textContent);
  if (previous) { setBusy(true); pollOperation(previous, data => data.analysis_id ? reviewAnalysis(data) : displayChart(data)); }
})();
