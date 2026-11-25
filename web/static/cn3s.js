/* CN3S controls use existing Python equations and authenticated SHC operations. */
(() => {
  const $ = id => document.getElementById(id);
  const root = '/shc/cn3s';
  const workspace = $('cn3s-workspace');
  if (!workspace) return;
  const step = workspace.dataset.step;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let station = null, forecastCycles = [], busy = false, selection = 0;
  const number = value => value == null ? 'indisponível' : Number(value).toLocaleString('pt-BR', {maximumFractionDigits: 4});
  function error(message = '') { $('cn-error').textContent = message; $('cn-error').hidden = !message; }
  async function api(path, payload) {
    const response = await fetch(root + path, payload === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(payload)
    });
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Resposta indisponível. Recarregue a página.');
    const data = await response.json();
    if (data.login_required) { location.assign('/shc/login'); throw new Error(data.error); }
    if (!response.ok) throw new Error(data.error || 'Operação expirada ou indisponível.');
    return data;
  }
  function option(value, text, disabled = false) { const node = new Option(text, value); node.disabled = disabled; return node; }
  function clearResults() {
    document.querySelectorAll('#cn-charts .cn-chart').forEach(node => Plotly.purge(node));
    $('cn-charts').replaceChildren(); $('cn-results').hidden = true;
  }
  function setBusy(value) {
    busy = value;
    document.querySelectorAll('#cn-controls input, #cn-controls select, #cn-controls button').forEach(node => { node.disabled = value; });
    document.querySelectorAll('.cn-section-nav a').forEach(node => { node.setAttribute('aria-disabled', String(value)); });
    $('cn-progress').hidden = !value;
    if ($('cn-input-download')) $('cn-input-download').hidden = value || !station?.series.rain || !station?.series.discharge;
    if (!value) readiness();
  }
  function addTable(parent, title, data) {
    const heading = document.createElement('h3'); heading.textContent = title; parent.append(heading);
    const wrapper = document.createElement('div'); wrapper.className = 'cn-table-wrap';
    const table = document.createElement('table'), head = document.createElement('tr');
    ['Mês/data', ...data.columns].forEach(label => {const th = document.createElement('th'); th.textContent = label; head.append(th);});
    table.append(head);
    data.data.forEach((values, index) => {
      const row = document.createElement('tr');
      [String(data.index[index]).slice(0, 10), ...values.map(number)].forEach(text => {const cell = document.createElement('td'); cell.textContent = text; row.append(cell);});
      table.append(row);
    });
    wrapper.append(table); parent.append(wrapper);
  }
  function renderStats(overview) {
    const parent = $('cn-stats');
    if (!overview) { parent.textContent = 'Estatísticas ainda não salvas. Clique em Atualizar estatísticas para consultar as séries disponíveis.'; return; }
    const note = document.createElement('p'); note.className = 'muted';
    note.textContent = `Atualizado em ${new Date(overview.updated_at).toLocaleString('pt-BR')}`;
    parent.append(note);
    const wrapper = document.createElement('div'); wrapper.className = 'cn-table-wrap';
    const table = document.createElement('table'), thead = document.createElement('thead');
    const groups = document.createElement('tr'), metrics = document.createElement('tr');
    const code = document.createElement('th'); code.textContent = 'Código'; code.rowSpan = 2; groups.append(code);
    for (let i = 0; i < overview.columns.length;) {
      const group = overview.columns[i][0]; let end = i + 1;
      while (end < overview.columns.length && overview.columns[end][0] === group) end++;
      const cell = document.createElement('th'); cell.colSpan = end - i;
      cell.textContent = {Fonte: 'Fonte', cota: 'Cota (cm)', vazao: 'Vazão (m³/s)'}[group] || group;
      groups.append(cell);
      for (let j = i; j < end; j++) { const th = document.createElement('th'); th.textContent = overview.columns[j][1]; metrics.append(th); }
      i = end;
    }
    thead.append(groups, metrics); table.append(thead);
    const body = document.createElement('tbody');
    overview.data.forEach((values, i) => {
      const row = document.createElement('tr');
      [String(overview.index[i]), ...values].forEach(value => {
        const cell = document.createElement('td'); cell.textContent = typeof value === 'number' ? number(value) : value ?? '—'; row.append(cell);
      }); body.append(row);
    });
    table.append(body); wrapper.append(table); parent.append(wrapper);
  }
  function calibrationInfo() {
    if (!$('cn-calibration-select')) { readiness(); return; }
    const selected = station?.calibrations.find(c => c.id === $('cn-calibration-select').value);
    const node = $('cn-calibration-info'); node.textContent = '';
    $('cn-parameter-values').replaceChildren();
    if (selected) {
      const m = selected.metadata, p = selected.params, scores = m.final_metrics || {};
      for (const name of ['r0', 'cn_i', 'alfa', 'beta', 'k0', 'k1', 'k2', 'act']) {
        const group = document.createElement('div'), term = document.createElement('dt'), value = document.createElement('dd');
        term.textContent = name + (name === 'r0' ? ' (mm)' : name === 'act' ? ' (meses)' : '');
        value.textContent = number(p[name]); group.append(term, value); $('cn-parameter-values').append(group);
      }
      node.textContent = `Área calibrada: ${number(p.area)} km² · ACT: ${p.act} meses · Aquecimento: ${p.warmup_steps} meses · Objetivo: ${m.objective?.name} · Treino: ${number(m.train_ratio * 100)}% · Estado do solver: ${m.status}. NSE treino: ${number(scores.train_nse)}; validação: ${number(scores.test_nse)}. Objetivo treino: ${number(scores.train_objective)}; validação: ${number(scores.test_objective)}.`;
      if (p.area !== station.metadata.drainage_area) node.append(' A área calibrada difere da área atual do inventário; a simulação preserva a área calibrada.');
      node.append(' Avalie a habilidade fora do treino; esta prova de conceito demonstra a integração e não valida previsões.');
    }
    readiness();
  }
  function readiness() {
    if (busy) return;
    const cycle = forecastCycles.find(c => c.id === $('cn-cycle')?.value);
    if ($('cn-prepare')) $('cn-prepare').disabled = !/^[1-9][0-9]*$/.test($('cn-code').value);
    if ($('cn-refresh')) $('cn-refresh').disabled = !station;
    if ($('cn-calibrate')) $('cn-calibrate').disabled = !station?.series.rain || !station?.series.discharge;
    for (const name of ['rain', 'discharge']) {
      if ($(`cn-save-${name}`)) $(`cn-save-${name}`).disabled = !station?.basin || !$('cn-replace').checked;
    }
    if (step !== 'previsao') return;
    let reason = '';
    if (!station?.basin || !station?.series.rain) reason = 'Prepare a bacia e a chuva mensal.';
    else if (!$('cn-calibration-select').value) reason = 'Selecione uma calibração mensal compatível.';
    else if (!cycle?.ready || !$('cn-months').value) reason = 'Selecione um ciclo completo e uma referência dentro dos meses disponíveis.';
    else {
      const first = $('cn-as-of').value.slice(0, 7);
      const [year, month] = first.split('-').map(Number);
      const previous = new Date(Date.UTC(year, month - 2, 1)).toISOString().slice(0, 10);
      if (station.series.rain.end < previous) reason = `Atualize a chuva salva até ${previous.slice(0, 7)}. Não serão preenchidos meses ausentes.`;
      else if (station.series.rain.missing) reason = 'A chuva salva contém valores ausentes.';
    }
    $('cn-ready').textContent = reason || 'Pronto para executar os dois cenários mensais. A continuidade completa será conferida no servidor.';
    $('cn-run').disabled = Boolean(reason);

  }
  function horizon() {
    const cycle = forecastCycles.find(c => c.id === $('cn-cycle')?.value);
    const reference = $('cn-as-of').value.slice(0, 7) + '-01';
    const months = cycle?.months || [], start = months.indexOf(reference);
    const previous = $('cn-months').value;
    $('cn-months').replaceChildren();
    if (start >= 0 && cycle.ready) {
      months.slice(start).forEach((month, index) => $('cn-months').append(option(index + 1, `${index + 1} · até ${month.slice(0, 7)}`)));
      $('cn-months').value = previous && Number(previous) <= months.length - start ? previous : String(months.length - start);
    }
    $('cn-cycle-info').textContent = cycle ? `Meses de chuva: ${months.map(m => m.slice(0, 7)).join(', ')}. ${cycle.ready ? '18 arquivos necessários presentes; nove modelos.' : [...cycle.errors, ...cycle.missing.map(n => 'Ausente: ' + n)].join(' · ')}` : 'Nenhum ciclo disponível. Prepare os arquivos CDS no notebook 03.';
    readiness();
  }
  async function loadCycles() {
    if (step !== 'previsao') return;
    forecastCycles = await api('/cycles');
    $('cn-cycle').replaceChildren(...forecastCycles.map(c => option(c.id, `${c.id.slice(4)}/${c.id.slice(0, 4)}${c.ready ? '' : ' · incompleto'}`)));
    if (forecastCycles.some(c => c.id === '202610')) $('cn-cycle').value = '202610';
    horizon();
  }
  async function loadStation() {
    error();
    const version = ++selection, code = $('cn-station').value;
    station = null; clearResults();
    if ($('cn-basin')) $('cn-basin').hidden = true;
    if ($('cn-input-download')) $('cn-input-download').hidden = true;
    for (const id of ['cn-inputs', 'cn-stats', 'cn-parameter-values']) $(id)?.replaceChildren();
    $('cn-calibration-select')?.replaceChildren(option('', 'Selecione uma calibração'));
    if ($('cn-calibration-info')) $('cn-calibration-info').textContent = '';
    if ($('cn-map-note')) $('cn-map-note').textContent = '';
    sessionStorage.setItem('cn3s-station', code);
    document.querySelectorAll('.cn-section-nav a').forEach(link => {
      const url = new URL(link.href); url.searchParams.set('station', code); link.href = url;
    });
    readiness();
    if (!code) { $('cn-station-info').textContent = 'Selecione uma estação.'; return; }
    const data = await api(`/stations/${code}`);
    if (version !== selection) return;
    station = data;
    const selectedOption = [...$('cn-station').options].find(o => o.value === code);
    if (selectedOption) selectedOption.textContent = `${data.metadata.station_name} · ${code}`;
    const m = data.metadata;
    $('cn-station-info').textContent = `${m.station_name} · ${m.station_code} · Cobacia ${m.cobacia} · Área do inventário: ${number(m.drainage_area)} km² · Área hidrográfica: ${number(m.drainage_area_geo)} km²`;
    if ($('cn-stats')) renderStats(data.overview);
    if (data.overview) $('cn-station-info').append(` · Latitude: ${number(data.overview.latitude)} · Longitude: ${number(data.overview.longitude)} (graus decimais)`);
    if ($('cn-inputs')) for (const [name, series] of Object.entries(data.series)) {
      addTable($('cn-inputs'), `${name === 'rain' ? 'Chuva (mm/mês)' : 'Vazão (m³/s)'} · ${series.start} a ${series.end} · ${series.rows} meses · ${series.missing} ausentes`, series.preview);
    }
    if ($('cn-map-note')) $('cn-map-note').textContent = data.states_available ? '' : 'Limites estaduais indisponíveis: configure SHC_STATES_PATH no servidor.';
    if (data.basin && $('cn-basin')) { $('cn-basin').src = `${root}/stations/${code}/basin.png?t=${Date.now()}`; $('cn-basin').hidden = false; }
    if ($('cn-input-download') && data.series.rain && data.series.discharge) {
      $('cn-input-download').href = `${root}/stations/${code}/inputs.csv`; $('cn-input-download').hidden = false;
      $('cn-cal-end').value = data.series.rain.end.slice(0, 7);
    }
    if (!$('cn-calibration-select')) { readiness(); return; }
    data.calibrations.forEach(c => $('cn-calibration-select').append(option(c.id, `${c.id}${c.compatible ? '' : ' · incompatível'}`, !c.compatible)));
    const first = data.calibrations.find(c => c.id.endsWith('PlainNSE_alfa_livre.json') && c.compatible) || data.calibrations.find(c => c.compatible);
    if (first) $('cn-calibration-select').value = first.id;
    calibrationInfo();
  }
  async function showResult(id, job) {
    const result = job.result; clearResults(); $('cn-results').hidden = false;
    $('cn-result-label').textContent = `Estação ${job.code} · ${job.kind} · ${number(job.elapsed_seconds)} segundos`;
    $('cn-warnings').textContent = (result.warnings || []).join(' '); $('cn-warnings').hidden = !result.warnings?.length;
    $('cn-record').textContent = JSON.stringify(result.summary, null, 2);
    $('cn-downloads').replaceChildren();
    for (const name of result.downloads) {
      const link = document.createElement('a'); link.href = `${root}/operations/${id}/download/${name}`; link.textContent = name; link.className = 'button quiet'; $('cn-downloads').append(link);
    }
    for (const name of result.charts) {
      const figure = await api(`/operations/${id}/download/${name}?inline=1`);
      const chart = document.createElement('div'); chart.className = 'cn-chart'; $('cn-charts').append(chart);
      await Plotly.newPlot(chart, figure.data, figure.layout, {responsive: true, locale: 'pt-BR', displaylogo: false});
    }
    if (result.downloads.includes('raw-rainfall.png')) {
      const image = document.createElement('img'); image.src = `${root}/operations/${id}/download/raw-rainfall.png?inline=1`; image.alt = 'Chuva bruta em equivalente de 30 dias, observações e climatologia'; image.className = 'cn-result-image'; $('cn-charts').append(image);
    }
    $('cn-result-tables').replaceChildren();
    if (result.rain) addTable($('cn-result-tables'), 'Chuva dos cenários · mm/mês', result.rain);
    if (result.discharge) addTable($('cn-result-tables'), 'Vazão dos cenários · m³/s · datas com ACT', result.discharge);
  }
  async function poll(id) {
    try {
      const job = await api(`/operations/${id}`);
      if (job.status === 'running') {
        $('cn-progress').textContent = `${job.phase} · ${Math.round(Date.now() / 1000 - job.started)} s`;
        setTimeout(() => poll(id), 1500); return;
      }
      if (job.status === 'failed') throw new Error(job.error);
      if (step === 'previsao' && !forecastCycles.length) {
        await loadCycles(); await loadStation();
        if (job.kind === 'forecast') {
          $('cn-cycle').value = job.settings.cycle; $('cn-calibration-select').value = job.settings.calibration;
          $('cn-as-of').value = job.settings.as_of; horizon(); $('cn-months').value = job.settings.months; calibrationInfo();
        }
      }
      if (job.kind !== 'forecast' || !station) {
        if (![...$('cn-station').options].some(o => o.value === String(job.code))) $('cn-station').append(option(job.code, String(job.code)));
        $('cn-station').value = job.code; await loadStation();
        if (job.result.calibration && $('cn-calibration-select')) { $('cn-calibration-select').value = job.result.calibration; calibrationInfo(); }
      }
      if (['calibrate', 'forecast'].includes(job.kind) && ((step === 'calibrar' && job.kind === 'calibrate') || (step === 'previsao' && job.kind === 'forecast'))) await showResult(id, job);
      setBusy(false);
    } catch (exc) { setBusy(false); error(exc.message); }
  }
  async function operate(kind, payload) {
    error(); clearResults(); setBusy(true); $('cn-progress').textContent = 'Iniciando…';
    try {
      const code = kind === 'prepare' ? $('cn-code').value : $('cn-station').value;
      const job = await api(`/stations/${code}/${kind}`, payload); await poll(job.operation_id);
    } catch (exc) { setBusy(false); error(exc.message); }
  }
  $('cn-station').addEventListener('change', () => loadStation().catch(exc => error(exc.message)));
  $('cn-calibration-select')?.addEventListener('change', () => {clearResults(); calibrationInfo();});
  for (const id of ['cn-cycle', 'cn-as-of']) $(id)?.addEventListener('change', () => {clearResults(); horizon();});
  $('cn-months')?.addEventListener('change', clearResults);
  $('cn-replace')?.addEventListener('change', readiness); $('cn-code')?.addEventListener('input', readiness);
  $('cn-prepare')?.addEventListener('click', () => operate('prepare', {}));
  for (const series of ['rain', 'discharge']) $(`cn-save-${series}`)?.addEventListener('click', () => operate('inputs', {series, start: $('cn-start').value + '-01', end: $('cn-end').value + '-01', replace: $('cn-replace').checked}));
  $('cn-run')?.addEventListener('click', () => operate('forecast', {calibration: $('cn-calibration-select').value, cycle: $('cn-cycle').value, as_of: $('cn-as-of').value, months: Number($('cn-months').value)}));
  $('cn-calibrate')?.addEventListener('click', () => {
    const bounds = Object.fromEntries([...document.querySelectorAll('#cn-bounds tr')].map(row => [row.dataset.param, [...row.querySelectorAll('input')].map(i => Number(i.value))]));
    operate('calibrate', {name: $('cn-name').value, end: $('cn-cal-end').value + '-01', train_ratio: Number($('cn-ratio').value), objective: $('cn-objective').value, maxiter: Number($('cn-maxiter').value), seed: Number($('cn-seed').value), warmup_steps: Number($('cn-warmup').value), bounds});
  });
  $('cn-basin')?.addEventListener('error', () => { $('cn-map-note').textContent = 'Não foi possível carregar o mapa. Verifique os dados geográficos no servidor.'; });
  $('cn-refresh')?.addEventListener('click', () => operate('overview', {}));
  document.querySelectorAll('.cn-section-nav a').forEach(link => link.addEventListener('click', event => { if (busy) event.preventDefault(); }));
  async function initialize() {
    const code = new URLSearchParams(location.search).get('station') || sessionStorage.getItem('cn3s-station');
    if (code) $('cn-station').value = code;
    const job = workspace.dataset.operation ? await api(`/operations/${workspace.dataset.operation}`).catch(() => null) : null;
    if (job?.status === 'running') {
      $('cn-station').value = String(job.code);
      setBusy(true); await poll(workspace.dataset.operation); return;
    }
    await loadCycles(); await loadStation();
    const relevant = job && ((step === 'calibrar' && job.kind === 'calibrate') || (step === 'previsao' && job.kind === 'forecast'));
    if (relevant && String(job.code) === $('cn-station').value && job.status === 'completed') {
      if (job.kind === 'forecast') {
        $('cn-calibration-select').value = job.settings.calibration;
        $('cn-cycle').value = job.settings.cycle; $('cn-as-of').value = job.settings.as_of;
        horizon(); $('cn-months').value = job.settings.months; calibrationInfo();
      }
      await showResult(workspace.dataset.operation, job);
    }
  }
  initialize().catch(exc => error(exc.message));
})();
