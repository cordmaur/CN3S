/* CN3S controls use existing Python equations and authenticated SHC operations. */
(() => {
  const $ = id => document.getElementById(id);
  const root = '/shc/cn3s';
  const workspace = $('cn3s-workspace');
  if (!workspace) return;
  const step = workspace.dataset.step;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let selection = 0;
  const number = value => value == null ? 'indisponível' : Number(value).toLocaleString('pt-BR', {maximumFractionDigits: 4});
  function error(message = '') { $('cn-error').textContent = message; $('cn-error').hidden = !message; }
  async function api(path, payload) {
    const response = await fetch(root + path, payload === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(payload)
    });
    if (response.status === 404) throw new Error('Operação expirada ou indisponível.');
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Resposta indisponível. Recarregue a página.');
    const data = await response.json();
    if (data.login_required) { location.reload(); throw new Error(data.error); }
    if (!response.ok) throw Object.assign(new Error(data.error || 'Operação expirada ou indisponível.'), {status: response.status});
    return data;
  }
  function option(value, text, disabled = false) { const node = new Option(text, value); node.disabled = disabled; return node; }
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
  function monthlyLink(code, source, start, end) {
    const query = new URLSearchParams({station: code, monthly: source, start, end});
    return root + '/estacao?' + query + '#cn-monthly';
  }
  async function stationPage() {
    const select = $('cn-station'), dialog = $('cn-dialog');
    const wait = () => new Promise(resolve => setTimeout(resolve, 1100));
    let current = null, variable = 'cota', creating = false, mapKey = '', monthlyBusy = false;
    const monthlyQuery = new URLSearchParams(location.search);
    const refreshes = new Map();

    async function monthlyCoverage(initial = false) {
      const code = select.value, version = selection;
      const data = await api('/stations/' + code + '?view=availability');
      if (version !== selection) return;
      const monthlySeries = data.series;
      $('cn-monthly-coverage').textContent = ['rain', 'discharge'].map(key => {
        const row = monthlySeries[key];
        return (key === 'rain' ? 'Chuva MERGE' : 'Vazão') + ': ' +
          (row?.start ? row.start.slice(0, 7) + ' a ' + row.end.slice(0, 7) +
            (row.missing ? ' · ' + row.missing + ' valores ausentes' : '') : 'ainda não preparada');
      }).join(' | ');
      if (initial) {
        const parts = new Intl.DateTimeFormat('sv-SE', {timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit'}).format(new Date()).split('-').map(Number);
        const last = new Date(Date.UTC(parts[0], parts[1] - 2, 1)).toISOString().slice(0, 7);
        const linked = monthlyQuery.get('station') === code && monthlyQuery.has('monthly');
        const requestedSource = monthlyQuery.get('monthly');
        const source = linked && ['rain', 'discharge', 'both'].includes(requestedSource) ? requestedSource : 'rain';
        $('cn-monthly-source').value = source;
        const row = monthlySeries[source === 'both' ? 'rain' : source];
        const next = row?.end ? new Date(row.end + 'T00:00:00Z') : null;
        if (next) next.setUTCMonth(next.getUTCMonth() + 1);
        const first = next ? [next.toISOString().slice(0, 7), last].sort()[0] : '2000-01';
        $('cn-monthly-start').value = linked && monthlyQuery.get('start') ? monthlyQuery.get('start') : first;
        $('cn-monthly-end').value = linked && monthlyQuery.get('end') ? monthlyQuery.get('end') : last;
        $('cn-monthly-editor').open = linked;
      }
    }

    function monthlyLock(value) {
      monthlyBusy = value;
      $('cn-monthly-fields').disabled = value;
      select.disabled = value;
      $('cn-add').disabled = value;
      $('cn-refresh').disabled = value;
      document.querySelectorAll('.cn-section-nav a').forEach(link => {
        if (value) link.setAttribute('aria-disabled', 'true');
        else link.removeAttribute('aria-disabled');
      });
      $('cn-monthly-progress').hidden = !value;
    }

    async function updateMonthly(existingId, settings) {
      const code = select.value;
      const source = settings?.series || $('cn-monthly-source').value;
      const start = settings?.start || $('cn-monthly-start').value + '-01';
      const end = settings?.end || $('cn-monthly-end').value + '-01';
      $('cn-monthly-source').value = source;
      $('cn-monthly-start').value = start.slice(0, 7);
      $('cn-monthly-end').value = end.slice(0, 7);
      if (start > end) {
        $('cn-monthly-status').textContent = 'O mês inicial deve ser anterior ou igual ao mês final.';
        return;
      }
      monthlyLock(true);
      $('cn-monthly-editor').open = true;
      try {
        const sources = source === 'both' ? ['rain', 'discharge'] : [source];
        for (const key of sources) {
          const label = key === 'rain' ? 'Chuva MERGE' : 'Vazão SQL';
          $('cn-monthly-status').textContent = label + ' · Iniciando atualização…';
          const id = existingId || (await api('/stations/' + code + '/inputs', {series: key, start, end, replace: true})).operation_id;
          await watch(id, job => { $('cn-monthly-status').textContent = label + ' · ' + job.phase; });
          await monthlyCoverage();
        }
        $('cn-monthly-status').textContent = 'Dados mensais atualizados. Você pode seguir para Calibrar Estação ou Previsão.';
      } catch (exc) {
        $('cn-monthly-status').textContent = 'Atualização interrompida. ' + exc.message;
        await monthlyCoverage().catch(() => {});
      } finally { monthlyLock(false); }
    }

    function renderSeries() {
      const parent = $('cn-stats'), overview = current?.overview;
      parent.replaceChildren();
      document.querySelectorAll('[data-series]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.series === variable));
      });
      if (!overview?.updated_at) return;
      const columns = overview.columns;
      const source = columns.findIndex(([group]) => group === 'Fonte');
      const metrics = ['Inicio','Fim','Anos','Anos (Efet.)','Falhas (%)','Consist (%)'];
      const positions = metrics.map(metric => columns.findIndex(([group, name]) => group === variable && name === metric));
      const table = document.createElement('table');
      const head = table.createTHead().insertRow();
      for (const label of ['Fonte','Código da série','Início','Fim','Anos','Anos efetivos','Falhas (%)','Consistência (%)']) {
        const th = document.createElement('th'); th.textContent = label; head.append(th);
      }
      const body = table.createTBody();
      overview.data.forEach((values, i) => {
        const row = body.insertRow();
        const hasRecords = Boolean(values[positions[0]]);
        const measurements = positions.map(index => hasRecords ? values[index] : null);
        if (!hasRecords) measurements[0] = 'Sem registros';
        if (values[source] !== 'Hidro') measurements[5] = null;
        for (const value of [values[source], String(overview.index[i]), ...measurements]) {
          row.insertCell().textContent = typeof value === 'number' ? number(value) : value ?? '—';
        }
      });
      if (!overview.data.some(values => values[positions[0]])) parent.textContent = 'Sem registros de ' + (variable === 'cota' ? 'cota' : 'vazão') + ' nas séries consultadas.';
      if (body.rows.length) parent.append(table);
    }

    function renderFicha(data) {
      current = data;
      const m = data.metadata, o = data.overview || {}, code = select.value;
      $('cn-details').hidden = false;
      $('cn-station-info').textContent = '';
      $('cn-name').textContent = o.name || m.station_name;
      select.selectedOptions[0].textContent = $('cn-name').textContent + ' · ' + code;
      const unit = (value, suffix) => value == null ? 'Indisponível' : number(value) + suffix;
      const fields = [
        ['Código ANA', code], ['Cobacia', m.cobacia], ['Município / UF', [o.city, o.uf].filter(Boolean).join(' · ')],
        ['Rio', o.river], ['Área do inventário', unit(m.drainage_area ?? o.inventory?.AreaDrenagem, ' km²')],
        ['Área hidrográfica', unit(m.drainage_area_geo, ' km²')], ['Latitude', unit(o.latitude, '°')], ['Longitude', unit(o.longitude, '°')]
      ];
      function showFields(parent, entries) {
        parent.replaceChildren();
        for (const [label, value] of entries) {
          const group = document.createElement('div'), term = document.createElement('dt'), dd = document.createElement('dd');
          term.textContent = label; dd.textContent = value === '' || value == null ? 'Indisponível' : value;
          group.append(term, dd); parent.append(group);
        }
      }
      showFields($('cn-fields'), fields);
      $('cn-inventory').hidden = !o.inventory;
      showFields($('cn-inventory-fields'), Object.entries(o.inventory || {}));
      const key = [code, data.basin, o.latitude, o.longitude].join('/');
      if (key !== mapKey) {
        mapKey = key;
        const parent = $('cn-map'), note = $('cn-map-note');
        parent.replaceChildren();
        $('cn-marker').hidden = o.latitude == null || o.longitude == null;
        note.textContent = data.basin ? 'Carregando mapa…' : 'Geometria da bacia indisponível.';
        if (data.basin) {
          const image = new Image();
          image.alt = 'Bacia contribuinte de ' + $('cn-name').textContent;
          image.onload = () => {
            if (key !== mapKey) return;
            parent.replaceChildren(image);
            note.textContent = $('cn-marker').hidden ? 'Coordenadas da estação indisponíveis.' : '';
          };
          image.onerror = () => { if (key === mapKey) note.textContent = 'Não foi possível carregar a geometria da bacia.'; };
          image.src = root + '/stations/' + code + '/basin.png';
        }
      }
      renderSeries();
    }

    async function watch(id, update) {
      for (;;) {
        const job = await api('/operations/' + id);
        if (job.status === 'failed') throw new Error(job.phase + ' ' + job.error);
        if (job.status === 'completed') return job;
        if (update) await update(job);
        await wait();
      }
    }

    async function start(code, kind) {
      // A single server worker owns the SQL and preparation operations.
      while (kind === 'prepare' || select.value === code) {
        try { return await api('/stations/' + code + '/' + kind, {}); }
        catch (exc) {
          if (exc.status !== 409) throw exc;
          if (kind === 'prepare') $('cn-phase').textContent = 'Aguardando a operação em andamento…';
          await wait();
        }
      }
      return null;
    }

    async function refresh(code, existingId) {
      const job = existingId ? {operation_id: existingId} : await start(code, 'overview');
      if (!job) return;
      let shown = false;
      await watch(job.operation_id, async state => {
        if (shown || select.value !== code || (state.completed_steps ?? 0) < 2) return;
        const version = selection;
        const data = await api('/stations/' + code + '?view=station');
        if (version === selection) {
          renderFicha(data);
          shown = true;
        }
      });
    }

    function status(message = '') {
      const stamp = current?.overview?.updated_at;
      const saved = stamp ? 'Última atualização: ' + new Date(stamp).toLocaleString('pt-BR') : 'Estatísticas ainda não salvas.';
      $('cn-status').textContent = [message, saved].filter(Boolean).join(' · ');
    }

    async function updateStats(existingId, pending) {
      const code = select.value, version = selection;
      const path = '/stations/' + code + '?view=station';
      $('cn-refresh').disabled = true;
      try {
        status('Consultando séries…');
        $('cn-series-progress').hidden = false;
        if (!pending) {
          pending = refresh(code, existingId).finally(() => refreshes.delete(code));
          refreshes.set(code, pending);
        }
        await pending;
        if (version !== selection) return;
        const updated = await api(path);
        if (version !== selection) return;
        renderFicha(updated); status();
      } catch (exc) {
        if (version !== selection) return;
        // Inventory may already be published even when the series query failed.
        const latest = await api(path).catch(() => null);
        if (version !== selection) return;
        if (latest) renderFicha(latest);
        status('Falha na atualização. ' + exc.message);
      } finally {
        if (version === selection) {
          $('cn-series-progress').hidden = true;
          $('cn-refresh').disabled = monthlyBusy;
        }
      }
    }

    async function load(existingId) {
      const code = select.value, version = ++selection;
      const pending = refreshes.get(code);
      $('cn-series-progress').hidden = true; $('cn-refresh').disabled = monthlyBusy;
      $('cn-inventory').open = false;
      current = null; mapKey = ''; $('cn-details').hidden = true; error();
      $('cn-station-info').textContent = code ? 'Carregando ficha…' : 'Selecione uma estação para visualizar os dados.';
      rememberStation(code);
      if (!code) return;
      try {
        const data = await api('/stations/' + code + '?view=station');
        if (version !== selection) return;
        renderFicha(data); status();
        $('cn-monthly-status').textContent = '';
        $('cn-monthly-coverage').textContent = 'Carregando cobertura mensal…';
        await monthlyCoverage(true);
        if (existingId || pending) await updateStats(existingId, pending);
      } catch (exc) {
        if (version === selection) $('cn-station-info').textContent = exc.message;
      }
    }

    function openDialog() {
      $('cn-form').reset(); $('cn-phase').textContent = ''; $('cn-dialog-error').textContent = '';
      $('cn-bar').value = 0; $('cn-bar').hidden = true; dialog.showModal();
    }
    async function create(code, existingId) {
      creating = true;
      for (const id of ['cn-prepare', 'cn-cancel', 'cn-code']) $(id).disabled = true;
      $('cn-bar').hidden = false; $('cn-bar').value = 0;
      $('cn-phase').textContent = 'Iniciando cadastro…'; $('cn-dialog-error').textContent = '';
      try {
        const id = existingId || (await start(code, 'prepare')).operation_id;
        await watch(id, job => {
          $('cn-phase').textContent = job.phase;
          // The daily SQL queries report no fraction of rows completed.
          if (job.completed_steps === 2) $('cn-bar').removeAttribute('value');
          else $('cn-bar').value = job.completed_steps || 0;
        });
        $('cn-bar').value = 4;
        if (![...select.options].some(o => o.value === code)) select.add(option(code, code));
        select.value = code; dialog.close(); select.focus(); await load();
      } catch (exc) {
        $('cn-phase').textContent = ''; $('cn-dialog-error').textContent = exc.message;
      } finally {
        $('cn-bar').hidden = true;
        creating = false;
        for (const id of ['cn-prepare', 'cn-cancel', 'cn-code']) $(id).disabled = false;
      }
    }

    select.onchange = () => load();
    $('cn-refresh').onclick = () => updateStats();
    $('cn-monthly-form').onsubmit = event => { event.preventDefault(); updateMonthly(); };
    document.querySelectorAll('[data-series]').forEach(button => {
      button.onclick = () => { variable = button.dataset.series; renderSeries(); };
    });
    $('cn-add').onclick = openDialog;
    $('cn-cancel').onclick = () => dialog.close();
    dialog.oncancel = event => { if (creating) event.preventDefault(); };
    $('cn-form').onsubmit = event => {
      event.preventDefault();
      const code = $('cn-code').value.trim();
      if ([...select.options].some(o => o.value === code)) {
        $('cn-dialog-error').textContent = 'Esta estação já está no seletor.'; return;
      }
      create(code);
    };
    const id = workspace.dataset.operation;
    const job = id && await api('/operations/' + id).catch(() => null);
    if (job?.status === 'running' && job.kind === 'prepare') {
      openDialog(); $('cn-code').value = job.code;
      const original = load();
      await create(String(job.code), id); await original;
    } else {
      const resume = job?.status === 'running' && job.kind === 'overview' && String(job.code) === select.value;
      await load(resume ? id : null);
      if (job?.status === 'running' && job.kind === 'inputs' && String(job.code) === select.value) {
        await updateMonthly(id, job.settings);
      }
    }
  }
  function calibrationName(run) {
    const stem = run.id.split('/').at(-1).replace(/\.json$/,'');
    return run.metadata?.display_name || (/^mensal_[a-f0-9]{16}$/.test(stem) ? 'Calibração mensal' : stem);
  }
  function calibrationLabel(run) {
    if (!run.compatible) return calibrationName(run)+' · incompatível';
    const stamp = Date.parse(run.metadata?.saved_at);
    const date = Number.isFinite(stamp) ? new Date(stamp).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}) : 'Data indisponível';
    return [calibrationName(run),date,run.metadata?.objective?.name].filter(Boolean).join(' · ');
  }
  async function calibrationPage() {
    const select = $('cn-station'), form = $('calibration-form');
    const chartOptions = {responsive:true, locale:'pt-BR', displaylogo:false};
    let catalog = [], series = {}, overview, running = false, draft = '', chartVersion = 0;
    let manualParent = null, manualDirty = false;
    const manualInputs = [...document.querySelectorAll('[data-manual-param]')];
    const nameDialog = $('calibrationNameDialog');
    function checkBounds(){
     const rows=Array.from($('bounds').rows);
     const invalid=rows.find(tr=>{
      const [lo,hi]=tr.querySelectorAll('input');
      return !lo.validity.valid || !hi.validity.valid || lo.valueAsNumber>=hi.valueAsNumber;
     });
     $('boundError').textContent=invalid ? invalid.cells[0].textContent+' · Informe limites não negativos com mínimo menor que máximo. ACT usa meses inteiros.' : '';
     return !invalid;
    }
    function solverMode(){
     const checked=$('converge').checked;
     $('iterLabel').hidden=$('iter').disabled=checked;
     $('tolerances').hidden=$('tol').disabled=$('atol').disabled=!checked;
    }

    const keys = Array.from($('bounds').rows, tr => tr.dataset.param);
    function cells(tr, values, tag='td') {
      for (const value of values) {
        const cell = document.createElement(tag);
        cell.textContent = value;
        tr.append(cell);
      }
    }
    document.querySelectorAll('.calibration-parameter-head').forEach(row =>
      cells(row, Array.from($('bounds').rows, tr => tr.cells[0].textContent), 'th'));
    function review(run, saved) {
      $('review').hidden = !run;
      $('reviewError').textContent = '';
      $('chartStatus').textContent = '';
      if (!run) { ++chartVersion; return; }
      const m = run.metadata, metrics = m.final_metrics || {};
      $('period').textContent = [saved ? 'Calibração salva' : 'Resultado em avaliação',
        m.display_name, m.status === 'manual' ? 'Ajuste manual' : '', m.objective?.name, m.input_start && m.input_end ? m.input_start+' a '+m.input_end : '',
        Number.isInteger(m.iterations) ? m.iterations+' gerações' : '',
        m.status === 'completed' ? 'Convergência atingida' :
          m.status === 'stopped_by_user' ? 'Treino interrompido pelo usuário' :
          m.status === 'stopped' ? 'Limite de gerações atingido' : m.message,
        run.inputs_changed ? 'Os arquivos mensais mudaram desde a calibração.' : '',
        saved && !run.has_chart ? 'Gráfico reconstituído com os dados mensais disponíveis.' : ''].filter(Boolean).join(' · ');
      for (const id of ['refreshChart','deleteCalibration','editManual']) $(id).hidden = !saved || Boolean(manualParent);
      $('saveCalibration').textContent = m.status === 'manual' ? 'Salvar como nova calibração' : 'Salvar calibração';
      for (const id of ['saveCalibration','discard']) $(id).hidden = saved;
      $('params').replaceChildren();
      cells($('params'),keys.map(k => number(run.params[k])));
      const baseline = saved ? null : m.parent_metrics;
      $('scoreHead').replaceChildren();
      cells($('scoreHead'), baseline ? ['Amostra','Objetivo original ↓','Objetivo ajustado ↓','NSE original ↑','NSE ajustado ↑'] :
        ['Amostra','Função objetivo ↓','NSE ↑'], 'th');
      $('scores').replaceChildren();
      for (const [key,label] of [['train','Treino'],['test','Teste']]) {
        const objective = key+'_objective', nse = key+'_nse';
        const values = baseline ? [baseline[objective], metrics[objective], baseline[nse], metrics[nse]] :
          [metrics[objective], metrics[nse]];
        cells($('scores').insertRow(),[label,...values.map(number)]);
      }
    }
    async function drawReview(path, refreshed=false) {
      const version = ++chartVersion;
      if (!refreshed) Plotly.purge($('finalChart'));
      $('chartStatus').textContent = refreshed ? 'Atualizando gráfico com os arquivos mensais…' : 'Carregando gráfico…';
      try {
        const figure = await api(path);
        if (version !== chartVersion) return;
        await Plotly.react($('finalChart'), figure.data, figure.layout, chartOptions);
        if (version === chartVersion) $('chartStatus').textContent = refreshed ?
          'Gráfico atualizado com os arquivos mensais atuais. As métricas exibidas são as da calibração salva.' : '';
      } catch (exc) {
        if (version === chartVersion) $('chartStatus').textContent = exc.message;
      }
    }
    function renderRun(refreshed=false) {
      const run = catalog.find(c => c.compatible && c.id === $('history').value);
      review(run,true);
      if (run) return drawReview('/stations/'+select.value+'/calibrations/chart?calibration='+encodeURIComponent(run.id)+(refreshed?'&refresh=1':''),refreshed);
    }
    function showHistory() {
      draft = ''; manualParent = null; manualDirty = false; $('manualForm').hidden = true;
      $('calibration-setup').hidden = $('execution').hidden = true;
      $('panel').hidden = false;
      review(null,true);
    }
    async function load(preferredId) {
      const code = select.value, version = ++selection;
      rememberStation(code); showHistory(); error(); $('panel').hidden = true;
      $('cn-station-info').textContent = code ? 'Carregando…' : 'Selecione uma estação.';
      if (!code) return;
      let data;
      try { data = await api('/stations/'+code+'?view=calibrations'); }
      catch (exc) { if (selection === version) error(exc.message); return; }
      if (selection !== version) return;
      overview = data.overview;
      catalog = data.calibrations.sort((a,b) => Number(b.compatible)-Number(a.compatible) ||
        (Date.parse(b.metadata?.saved_at)||0)-(Date.parse(a.metadata?.saved_at)||0) || a.id.localeCompare(b.id));
      $('cn-station-info').textContent = data.metadata.station_name+' · '+code;
      $('panel').hidden=false;
      $('history').replaceChildren(...catalog.map(c=>option(c.id,calibrationLabel(c),!c.compatible)));
      $('historyLabel').hidden=!catalog.length;
      $('empty').textContent=catalog.some(c=>c.compatible)?'':'Nenhuma calibração mensal compatível.';
      if (catalog.some(c=>c.id===preferredId)) $('history').value=preferredId;
      return renderRun();
    }
    function availability() {
      const a=$('start').value, b=$('end').value;
      const date=new Date(a+'-01T00:00:00Z');
      date.setUTCMonth(date.getUTCMonth()+Number($('warm').value));
      const first=Number.isFinite(date.getTime()) ? date.toISOString().slice(0,7) : '';
      const valid=a && b && $('warm').validity.valid && first && first<=b;
      $('first').textContent=first ? 'Primeiro mês simulado com ACT = 0: '+first+'.' : '';
      const needs=[];
      if (valid) {
        const rain=new Set(series.rain?.months);
        const cursor=new Date(a+'-01T00:00:00Z');
        while (cursor.toISOString().slice(0,7)<=b) {
          if (!rain.has(cursor.toISOString().slice(0,7))) {needs.push('rain');break;}
          cursor.setUTCMonth(cursor.getUTCMonth()+1);
        }
        if (!series.discharge?.start || series.discharge.start.slice(0,7)>a || series.discharge.end.slice(0,7)<b) needs.push('discharge');
      }
      const pairs=(series.discharge?.months||[]).filter(m=>m>=first && m<=b).length;
      const split=Math.floor(pairs*(Number($('ratio').value)/100));
      const enough=Math.min(split,pairs-split)>=2;
      $('notice').textContent=!valid?'Confira o período e o aquecimento.':needs.length?'Preparar '+needs.map(k=>k==='rain'?'chuva MERGE':'vazão SQL').join(' e ')+'.':
        pairs+' meses com vazão após o aquecimento (ACT = 0). '+(enough?'':'Aumente o intervalo ou ajuste a relação treino/teste.');
      if (b===new Date().toISOString().slice(0,7)) $('notice').textContent+=' O mês atual pode estar parcial.';
      const boundsOK=checkBounds();
      if (valid && needs.length) $('prepare').href=monthlyLink(select.value, needs.length===2?'both':needs[0], a, b);
      $('prepare').hidden=running || !valid || !needs.length || Boolean(draft);
      $('run').disabled=running || !valid || !!needs.length || !enough || !boundsOK || Boolean(draft);
      return needs;
    }
    async function coverage(initial) {
      const data=await api('/stations/'+select.value+'?view=availability');
      series=data.series;
      $('monthlyCsv').hidden=!series.rain || !series.discharge;
      $('monthlyCsv').href=root+'/stations/'+select.value+'/inputs.csv';
      $('coverage').textContent=['rain','discharge'].map(k=>(k==='rain'?'Chuva':'Vazão')+' · '+(series[k]?.start?series[k].start+' a '+series[k].end:'ausente')).join(' | ');
      if(initial){
        const [year,month] = new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit'}).format(new Date()).split('-').map(Number);
        $('end').value = new Date(Date.UTC(year,month-2,1)).toISOString().slice(0,7);
      }
      availability();
    }
    async function watch(id, onUpdate) {
      for (;;) {
        const job = await api('/operations/'+id);
        if (job.status === 'failed') throw new Error(job.error);
        onUpdate?.(job);
        if (job.status !== 'running') return job;
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }
    function lock(value) {
      running = value;
      for (const control of [select,...['settings','create','cancel','history','refreshChart',
        'deleteCalibration','editManual','manualFields','recalculate','cancelManual','confirmSave','cancelSave',
        'saveCalibration','discard'].map($)]) control.disabled = value;
      $('saveCalibration').disabled = value || manualDirty;
      availability();
    }
    async function trainReview(id) {
      $('execution').hidden = false;
      $('executionTitle').focus();
      $('runStatus').textContent = 'Inicializando a população…';
      const progress = $('runProgress');
      progress.removeAttribute('value');
      $('bestParams').replaceChildren();
      Plotly.purge($('liveChart'));
      let count = -1;
      const stop = $('stopTraining'), stopStatus = $('stopStatus');
      let requestingStop = false;
      stopStatus.textContent = '';
      stop.onclick = async () => {
        requestingStop = true;
        stop.disabled = true;
        stopStatus.textContent = 'Solicitando parada…';
        try {
          const result = await api('/operations/'+id+'/stop',{});
          stopStatus.textContent = result.stop_requested ? 'Parada solicitada. Aguardando o fim da geração atual…' : '';
        } catch (exc) {
          requestingStop = false;
          stop.disabled = false;
          stopStatus.textContent = exc.message;
        }
      };
      try {
        await watch(id, job => {
          stop.hidden = job.status !== 'running';
          stop.disabled = requestingStop || job.stop_requested;
          if (job.stop_requested) stopStatus.textContent = 'Parada solicitada. Aguardando o fim da geração atual…';

          const generations = job.generations || [];
          const latest = generations.at(-1);
          $('runStatus').textContent = job.status === 'completed' ? 'Treino concluído' :
            job.phase+(latest?.[1] != null ? ' · Melhor objetivo de treino '+number(latest[1]) : '');
          if (job.status === 'completed' || !job.settings.until_convergence) {
            progress.max = job.status === 'completed' ? Math.max(1,generations.length) : (job.settings.maxiter || 20);
            progress.value = job.status === 'completed' ? progress.max : generations.length;
          }
          if (count === generations.length) return;
          count = generations.length;
          $('bestParams').replaceChildren();
          if (job.best_params) cells($('bestParams'),keys.map(key=>number(job.best_params[key])));
          Plotly.react($('liveChart'),[{x:generations.map(row=>row[0]),y:generations.map(row=>row[1]),
            mode:'lines+markers',name:'Melhor objetivo de treino',line:{color:'#145d83'}}],
            {height:300,margin:{l:65,r:20,t:16,b:50},xaxis:{title:{text:'Geração'},dtick:generations.length <= 20 ? 1 : undefined},
              yaxis:{title:{text:'Objetivo de treino'}},separators:',.'},chartOptions);
        });
      } finally {
        stop.hidden = true;
        stop.onclick = null;
        stopStatus.textContent = '';
      }
      const artifact = await api('/operations/'+id+'/download/calibration.json?inline=1');
      draft = id;
      if (artifact.metadata.status === 'stopped_by_user') $('runStatus').textContent='Treino interrompido após '+artifact.metadata.iterations+' gerações.';
      review(artifact,false);
      await drawReview('/operations/'+id+'/download/calibration-chart.json?inline=1');
      $('reviewTitle').focus();
    }
    async function execute() {
      const code=select.value, start=$('start').value+'-01', end=$('end').value+'-01';
      if (availability().length) return;
      lock(true); $('setupError').textContent='';
      try {
        const bounds=Object.fromEntries(Array.from($('bounds').rows,tr=>[tr.dataset.param,Array.from(tr.querySelectorAll('input'),i=>i.valueAsNumber)]));
        const payload={start,end,bounds,objective:$('objective').value,train_ratio:Number($('ratio').value)/100,
          seed:$('seed').valueAsNumber,warmup_steps:$('warm').valueAsNumber,until_convergence:$('converge').checked,
          maxiter:$('iter').valueAsNumber,tol:$('converge').checked?$('tol').valueAsNumber:0.0001,atol:$('converge').checked?$('atol').valueAsNumber:0};
        $('execution').hidden=false;
        $('runStatus').textContent='Iniciando calibração…';
        const job=await api('/stations/'+code+'/calibrate',payload);
        await trainReview(job.operation_id);
      } catch (exc) {
        $('runStatus').textContent = exc.message;
        $('runProgress').hidden = true;
        $('setupError').textContent=exc.message;
      } finally { lock(false); }
    }
    $('create').onclick=async()=>{
      form.reset(); solverMode(); $('setupError').textContent='';
      $('panel').hidden=$('execution').hidden=true;
      $('calibration-setup').hidden=false;
      review(null,true);
      $('stamp').textContent=overview?.updated_at?'Resumo de '+overview.updated_at:'Resumo ausente. Atualize as estatísticas de cota e vazão na aba Estação.';
      $('stats').replaceChildren();
      for(const [i,row] of (overview?.data||[]).entries()){
        const field=(g,k)=>row[overview.columns.findIndex(([group,metric])=>group===g && (!k||metric===k))];
        cells($('stats').insertRow(),[field('Fonte')+' / '+overview.index[i],(field('vazao','Inicio')||'—')+' a '+(field('vazao','Fim')||'—'),number(field('vazao','Anos (Efet.)')),number(field('vazao','Falhas (%)'))]);
      }
      series={}; lock(true);
      try { await coverage(true); }
      catch (exc) { $('setupError').textContent=exc.message; }
      finally { lock(false); }
      $('start').focus();
    };
    function editManual(parent, params) {
      manualParent = parent;
      manualDirty = false;
      $('panel').hidden = true;
      $('manualForm').hidden = false;
      for (const input of manualInputs) input.value = params[input.dataset.manualParam];
      for (const id of ['refreshChart','deleteCalibration','editManual']) $(id).hidden = true;
      $('manualStatus').textContent = '';
    }
    async function reviewManual(id, parent) {
      const artifact = await api('/operations/'+id+'/download/calibration.json?inline=1');
      draft = id;
      const original = catalog.find(c=>c.id===parent);
      if (original) editManual(original,artifact.params);
      review(artifact,false);
      await drawReview('/operations/'+id+'/download/calibration-chart.json?inline=1');
    }
    $('editManual').onclick=()=>{
      const parent=catalog.find(c=>c.id===$('history').value);
      if (!parent) return;
      editManual(parent,parent.params);
      manualInputs[0].focus();
    };
    $('manualForm').oninput=()=>{
      manualDirty = Boolean(draft);
      $('saveCalibration').disabled = running || manualDirty;
      if (draft) $('manualStatus').textContent='Recalcule antes de salvar os valores alterados.';
    };
    $('manualForm').onsubmit=async event=>{
      event.preventDefault();
      if (running || !manualParent) return;
      const parent=manualParent.id;
      const params=Object.fromEntries(manualInputs.map(input=>[input.dataset.manualParam,input.valueAsNumber]));
      lock(true);
      $('reviewError').textContent='';
      $('manualStatus').textContent='Recalculando…';
      try {
        const job = await api('/stations/'+select.value+'/manual-calibration',{calibration:parent,params});
        await watch(job.operation_id);
        const previous = draft;
        await reviewManual(job.operation_id,parent);
        if (previous) await api('/operations/'+previous+'/discard',{}).catch(()=>{});
        $('manualStatus').textContent='Indicadores recalculados.';
      } catch (exc) { $('manualStatus').textContent=exc.message; }
      finally { lock(false); }
    };
    async function finish(action, payload={}) {
      lock(true);
      const errorNode = $(action==='save'?'saveError':'reviewError');
      errorNode.textContent='';
      try {
        const result=await api('/operations/'+draft+'/'+action,payload);
        if (nameDialog.open) nameDialog.close();
        await load(result.calibration || manualParent?.id);
        $('create').focus();
      } catch (exc) { errorNode.textContent=exc.message; }
      finally { lock(false); }
    }
    $('cancelManual').onclick=()=>{ if (draft) finish('discard'); else load(manualParent?.id); };
    $('cancel').onclick=async()=>{ if (draft) await finish('discard'); else await load(); };
    form.oninput=availability; $('converge').onchange=solverMode;
    form.onsubmit=e=>{e.preventDefault();$('runProgress').hidden=false;execute();};
    $('saveCalibration').onclick=()=>{
      $('saveError').textContent='';
      $('calibrationName').value='';
      nameDialog.showModal();
    };
    $('cancelSave').onclick=()=>nameDialog.close();
    nameDialog.oncancel=event=>{ if (running) event.preventDefault(); };
    $('calibrationNameForm').onsubmit=event=>{
      event.preventDefault();
      if (!running && !manualDirty) finish('save',{name:$('calibrationName').value});
    };
    $('discard').onclick=()=>finish('discard');
    $('refreshChart').onclick=async()=>{
      lock(true);
      try { await renderRun(true); } finally { lock(false); }
    };
    $('deleteCalibration').onclick=async()=>{
      if (!window.confirm('Apagar a calibração selecionada do histórico da estação?')) return;
      lock(true);
      try {
        await api('/stations/'+select.value+'/calibrations/delete',{calibration:$('history').value});
        await load();
      } catch (exc) { $('reviewError').textContent=exc.message; }
      finally { lock(false); }
    };
    $('history').onchange=()=>renderRun();
    select.onchange=async()=>{
      if (draft) {
        const requested = select.value;
        select.value = new URLSearchParams(location.search).get('station') || '';
        if (!window.confirm('Descartar o resultado em avaliação e trocar de estação?')) return;
        lock(true);
        try {
          await api('/operations/'+draft+'/discard',{});
          select.value=requested;
        } catch (exc) { $('reviewError').textContent=exc.message; return; }
        finally { lock(false); }
      }
      await load();
    };
    await load();
    const id=workspace.dataset.operation;
    if (id) {
      const job=await api('/operations/'+id).catch(()=>null);
      if (!job || String(job.code)!==select.value || !['calibrate','manual-calibration'].includes(job.kind) || job.published ||
          catalog.some(run=>run.id===job.result?.calibration)) return;
      if (job.status==='running' || job.status==='completed') {
        $('panel').hidden=true;
        lock(true);
        try {
          if (job.kind==='calibrate') await trainReview(id);
          else { await watch(id); await reviewManual(id,job.settings.calibration); }
        }
        catch (exc) { showHistory(); error(exc.message); }
        finally { lock(false); }
      }
    }
  }
  function rememberStation(code) {
    sessionStorage.setItem('cn3s-station', code);
    const page = new URL(location.href);
    if (page.searchParams.get('station') !== code) {
      for (const key of ['monthly', 'start', 'end']) page.searchParams.delete(key);
    }
    if (code) page.searchParams.set('station', code);
    else page.searchParams.delete('station');
    history.replaceState(history.state, '', page);
    document.querySelectorAll('.cn-section-nav a').forEach(link => {
      const url = new URL(link.href); url.searchParams.set('station', code); link.href = url;
    });
  }
  async function forecastPage() {
    const stationSelect = $('cn-station'), calibrationSelect = $('cn-calibration-select');
    const cycleSelect = $('cn-cycle'), monthSelect = $('cn-months');
    const center = $('cn-flow-centered'), anchor = $('cn-flow-anchor');
    const flowChart = $('cn-flow-chart'), calibrationChart = $('cn-calibration-chart');
    const options = {responsive: true, locale: 'pt-BR', displaylogo: false};
    const dateLabel = new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeZone: 'UTC'});
    const monthLabel = new Intl.DateTimeFormat('pt-BR', {month: 'long', year: 'numeric', timeZone: 'UTC'});
    const date = value => new Date(value.slice(0, 10) + 'T00:00:00Z');
    const cycleLabel = id => monthLabel.format(date(id.slice(0, 4) + '-' + id.slice(4) + '-01'));
    const nextMonth = (value, increment) => {
      const [year, month] = value.split('-').map(Number);
      return new Date(Date.UTC(year, month - 1 + increment, 1)).toISOString().slice(0, 10);
    };
    const wait = () => new Promise(resolve => setTimeout(resolve, 1200));
    let station, cycles = [], busy = false;
    let chartVersion = 0, flowVersion = 0, flow;
    const compatible = () => (station?.calibrations || []).filter(run => run.compatible);
    const cycle = () => cycles.find(item => item.id === cycleSelect.value);

    function readiness() {
      const lead = cycle()?.months[0];
      const required = lead ? nextMonth(lead, -1).slice(0, 7) : '';
      const rain = station?.series.rain;
      const needsRain = Boolean(station && required && (!rain?.end || rain.end.slice(0, 7) < required || rain.missing));
      $('cn-update-rain-wrap').hidden = busy || !needsRain;
      if (needsRain) {
        const first = rain?.end && rain.end.slice(0, 7) < required ? nextMonth(rain.end, 1).slice(0, 7) : rain?.start?.slice(0, 7) || '2000-01';
        $('cn-update-rain').href = monthlyLink(stationSelect.value, 'rain', first, required);
      }
      calibrationSelect.disabled = busy || !compatible().length;
      cycleSelect.disabled = busy || !cycles.some(item => item.ready);
      monthSelect.disabled = busy || !monthSelect.options.length;
      let reason = '';
      if (!station) reason = 'Selecione uma estação.';
      else if (!compatible().length) reason = 'Salve uma calibração mensal em Calibrar Estação.';
      else if (!station.basin || !station.series.rain?.end) reason = 'Prepare a bacia e a chuva mensal da estação.';
      else if (!calibrationSelect.value) reason = 'Selecione uma calibração mensal.';
      else if (!cycle()?.ready || !monthSelect.value) reason = 'Selecione um ciclo CDS completo e o horizonte.';
      else if (station.series.rain.end < nextMonth(lead, -1)) {
        reason = 'Atualize a chuva mensal até ' + monthLabel.format(date(nextMonth(lead, -1))) + '.';
      } else if (station.series.rain.missing) reason = 'A chuva mensal contém valores ausentes.';
      $('cn-ready').textContent = reason;
      $('cn-run').disabled = busy || Boolean(reason);
    }

    function setBusy(value) {
      busy = value;
      stationSelect.disabled = value;
      document.querySelectorAll('.cn-section-nav a').forEach(link => {
        if (value) link.setAttribute('aria-disabled', 'true');
        else link.removeAttribute('aria-disabled');
      });
      $('cn-progress').hidden = !value;
      readiness();
    }

    function clearResults() {
      ++flowVersion;
      flow = undefined;
      if (flowChart.data) Plotly.purge(flowChart);
      document.querySelectorAll('#cn-charts .cn-chart').forEach(node => Plotly.purge(node));
      $('cn-charts').replaceChildren();
      $('cn-results').hidden = true;
    }

    async function showCalibration() {
      const version = ++chartVersion;
      const run = compatible().find(item => item.id === calibrationSelect.value);
      const status = $('cn-calibration-chart-status');
      if (calibrationChart.data) Plotly.purge(calibrationChart);
      $('cn-calibration-review').hidden = !run;
      readiness();
      if (!run) return;
      const p = run.params, m = run.metadata;
      document.querySelectorAll('#cn-parameter-values td').forEach(cell => {
        const value = p[cell.dataset.parameter];
        cell.textContent = value == null ? 'indisponível' : Number(value).toLocaleString('pt-BR', {maximumSignificantDigits: 8});
      });
      const period = m.input_start && m.input_end ? m.input_start + ' a ' + m.input_end : '';
      $('cn-calibration-info').textContent = [period, 'Área calibrada ' + number(p.area) + ' km²',
        'Aquecimento ' + number(p.warmup_steps) + ' meses'].filter(Boolean).join(' · ');
      status.textContent = 'Carregando gráfico…';
      try {
        const figure = await api('/stations/' + stationSelect.value + '/calibrations/chart?calibration=' + encodeURIComponent(run.id));
        if (version !== chartVersion) return;
        // Ignore a saved zoom range so the initial view always shows the full period.
        for (const [axis, layout] of Object.entries(figure.layout)) {
          if (/^xaxis\d*$/.test(axis)) {
            delete layout.range;
            layout.autorange = true;
          }
        }
        await Plotly.react(calibrationChart, figure.data, figure.layout, options);
        if (version !== chartVersion) return;
        status.textContent = run.has_chart ? '' : 'Gráfico reconstituído com os dados mensais disponíveis.';
      } catch (exc) {
        if (version === chartVersion) status.textContent = 'Gráfico indisponível. ' + exc.message;
      }
    }

    async function loadStation(preferredCalibration) {
      const version = ++selection, code = stationSelect.value;
      station = undefined;
      clearResults();
      rememberStation(code);
      error();
      calibrationSelect.replaceChildren(option('', code ? 'Carregando calibrações…' : 'Selecione uma estação'));
      $('cn-station-info').textContent = '';
      await showCalibration();
      if (!code || version !== selection) return;
      try {
        const data = await api('/stations/' + code);
        if (version !== selection) return;
        station = data;
        const runs = compatible().sort((a, b) => (b.metadata.saved_at || '').localeCompare(a.metadata.saved_at || ''));
        calibrationSelect.replaceChildren(...runs.map(run => option(run.id, calibrationLabel(run))));
        if (!runs.length) calibrationSelect.add(option('', 'Nenhuma calibração mensal disponível'));
        if (runs.some(run => run.id === preferredCalibration)) calibrationSelect.value = preferredCalibration;
        const name = data.overview?.name || data.metadata.station_name;
        if (name) stationSelect.selectedOptions[0].textContent = name + ' · ' + code;
        await showCalibration();
      } catch (exc) {
        if (version !== selection) return;
        calibrationSelect.replaceChildren(option('', 'Calibrações indisponíveis'));
        $('cn-station-info').textContent = exc.message;
      }
    }

    function setHorizon(preferredMonths) {
      const item = cycle(), start = item?.months[0];
      const previous = Number(preferredMonths ?? monthSelect.value);
      const lengths = [];
      if (item?.ready) {
        for (const lead of item.months) {
          if (lead !== nextMonth(start, lengths.length)) break;
          lengths.push(lead);
        }
      }
      monthSelect.replaceChildren(...lengths.map((_, i) => option(i + 1, i === 0 ? '1 mês' : (i + 1) + ' meses')));
      if (lengths.length) monthSelect.value = String(Math.min(previous || lengths.length, lengths.length));
      showHorizon();
    }

    function showHorizon() {
      const start = cycle()?.months[0];
      const count = Number(monthSelect.value);
      $('cn-cycle-info').textContent = start && count
        ? 'Chuva prevista de ' + monthLabel.formatRange(date(start), date(nextMonth(start, count - 1))) + '.'
        : (cycles.some(item => item.ready) ? '' : 'Nenhum ciclo completo. Prepare os arquivos CDS no notebook 03.');
      readiness();
    }

    async function loadCycles(preferredCycle, preferredMonths) {
      cycles = await api('/cycles');
      cycleSelect.replaceChildren(...cycles.map(item =>
        option(item.id, cycleLabel(item.id) + (item.ready ? '' : ' · incompleto'), !item.ready)));
      const ready = cycles.find(item => item.id === preferredCycle && item.ready) || cycles.find(item => item.ready);
      if (ready) cycleSelect.value = ready.id;
      else cycleSelect.replaceChildren(option('', 'Nenhum ciclo completo'), ...cycleSelect.options);
      setHorizon(preferredMonths);
    }

    async function drawFlow() {
      const version = ++flowVersion;
      if (!flow) return;
      const name = 'monthly' + (center.checked ? '' : '-calendar') + (anchor.checked ? '-anchored' : '') + '.json';
      const {figures, id} = flow;
      const status = $('cn-flow-notice');
      try {
        if (!figures.has(name)) figures.set(name, api('/operations/' + id + '/download/' + name + '?inline=1'));
        const figure = await figures.get(name);
        if (version !== flowVersion) return;
        const hidden = new Set([...$('cn-flow-years').querySelectorAll('input:not(:checked)')].map(input => input.value));
        const traces = figure.data.map(trace => hidden.has(trace.legendgroup) ? {...trace, visible: false} : trace);
        const layout = {...figure.layout, title: undefined, height: window.innerWidth <= 600 ? 490 : 600,
          margin: {...figure.layout.margin, l: 65, r: 16, t: 48, b: 140},
          xaxis: {...figure.layout.xaxis, automargin: true},
          legend: {...figure.layout.legend, itemclick: false, itemdoubleclick: false}};
        await Plotly.react(flowChart, traces, layout, options);
        if (version === flowVersion) {
          status.textContent = flow.cutoff;
          $('cn-flow-anchor-note').textContent = flow.anchorMessage
            || (anchor.checked ? 'As duas curvas foram ajustadas à vazão média observada no mês de referência, até a data de corte.' : '');
        }
      } catch (exc) {
        figures.delete(name);
        if (version === flowVersion) status.textContent = 'Gráfico mensal indisponível. ' + exc.message;
      }
    }

    function addAnomalyControl(id, chart, percent) {
      const controls = document.createElement('div'); controls.className = 'forecast-plot-controls';
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.id = 'cn-anomaly-mm';
      const status = document.createElement('p'); status.className = 'muted';
      status.setAttribute('role', 'status');
      input.setAttribute('aria-describedby', 'cn-anomaly-status');
      status.id = 'cn-anomaly-status';
      label.append(input, 'Exibir anomalia em mm'); controls.append(label, status);
      chart.before(controls);
      let mmFigure, version = 0;
      input.addEventListener('change', async () => {
        const requested = ++version;
        status.textContent = '';
        try {
          if (input.checked && !mmFigure) mmFigure = api('/operations/' + id + '/download/anomaly-mm.json?inline=1');
          const figure = input.checked ? await mmFigure : percent;
          if (requested !== version || !chart.isConnected) return;
          await Plotly.react(chart, figure.data, figure.layout, options);
        } catch (exc) {
          mmFigure = undefined;
          if (requested !== version || !chart.isConnected) return;
          input.checked = false;
          status.textContent = 'Não foi possível exibir a anomalia em mm. ' + exc.message;
        }
      });
    }

    async function showResult(id, job) {
      clearResults();
      const {result} = job;
      const downloads = result.downloads || [];
      $('cn-results').hidden = false;
      const calibration = compatible().find(run => run.id === job.settings.calibration);
      $('cn-result-label').textContent = [stationSelect.selectedOptions[0]?.textContent || job.code,
        calibration ? calibrationName(calibration) : '', 'CDS ' + cycleLabel(job.settings.cycle)].filter(Boolean).join(' · ');
      $('cn-warnings').textContent = (result.warnings || []).join(' ');
      $('cn-warnings').hidden = !result.warnings?.length;
      $('cn-record').textContent = JSON.stringify(result.summary, null, 2);
      $('cn-downloads').replaceChildren();
      $('cn-result-tables').replaceChildren();
      $('cn-flow-years').replaceChildren();
      $('cn-flow-anchor-note').textContent = '';
      const asOf = result.summary?.forecast?.as_of || job.settings.as_of;
      const forecastStart = result.summary?.forecast_discharge_start;
      $('cn-flow-scenario-start').textContent = forecastStart && forecastStart.slice(0, 7) > asOf.slice(0, 7)
        ? ' As curvas usam chuva observada nos meses iniciais. A chuva prevista passa a influenciar a vazão em ' + monthLabel.format(date(forecastStart)) + '.'
        : '';
      const hasMonthly = downloads.includes('monthly.json');
      $('cn-flow-controls').hidden = $('cn-flow-caption').hidden = !hasMonthly;
      $('cn-flow-notice').textContent = hasMonthly ? 'Carregando gráfico…' : 'Comparação de vazão observada indisponível.';
      if (hasMonthly) {
        const year = Number(asOf.slice(0, 4));
        for (const yearsAgo of [1, 2, 3]) {
          if (yearsAgo === 3 && !downloads.includes('monthly-calendar.json')) continue;
          const label = document.createElement('label'), input = document.createElement('input');
          input.type = 'checkbox'; input.value = String(year - yearsAgo); input.checked = yearsAgo < 3;
          input.addEventListener('change', drawFlow);
          label.append(input, input.value); $('cn-flow-years').append(label);
        }
        center.checked = true; center.disabled = !downloads.includes('monthly-calendar.json');
        anchor.checked = false; anchor.disabled = !downloads.includes('monthly-anchored.json');
        flow = {id, figures: new Map(), cutoff: 'Observações consultadas até ' + dateLabel.format(date(asOf)) + '.',
          anchorMessage: anchor.disabled ? result.anchor_message || 'Esta operação não possui uma figura ancorada.' : ''};
        await drawFlow();
      }

      for (const name of result.charts.filter(name => name !== 'monthly.json')) {
        const figure = await api('/operations/' + id + '/download/' + name + '?inline=1');
        const chart = document.createElement('div'); chart.className = 'cn-chart'; $('cn-charts').append(chart);
        await Plotly.newPlot(chart, figure.data, figure.layout, options);
        if (name === 'anomaly.json' && downloads.includes('anomaly-mm.json')) addAnomalyControl(id, chart, figure);
      }
      for (const name of downloads.filter(name => name !== 'raw-rainfall.png')) {
        const link = document.createElement('a');
        link.href = root + '/operations/' + id + '/download/' + name;
        link.textContent = name; link.className = 'button quiet'; $('cn-downloads').append(link);
      }
      if (result.rain) addTable($('cn-result-tables'), 'Chuva dos cenários · mm/mês', result.rain);
      if (result.discharge) addTable($('cn-result-tables'), 'Vazão dos cenários · m³/s · datas com ACT', result.discharge);
    }

    async function poll(id, job) {
      let latest = job || await api('/operations/' + id);
      while (latest.status === 'running') {
        $('cn-progress').textContent = latest.phase + ' · ' + Math.round(Date.now() / 1000 - latest.started) + ' s';
        await wait();
        latest = await api('/operations/' + id);
      }
      return latest;
    }

    stationSelect.addEventListener('change', () => loadStation());
    calibrationSelect.addEventListener('change', () => { clearResults(); showCalibration(); });
    cycleSelect.addEventListener('change', () => { clearResults(); setHorizon(); });
    monthSelect.addEventListener('change', () => { clearResults(); showHorizon(); });
    center.addEventListener('change', drawFlow);
    anchor.addEventListener('change', drawFlow);
    document.querySelectorAll('.cn-section-nav a').forEach(link => {
      link.addEventListener('click', event => { if (busy) event.preventDefault(); });
    });
    $('cn-run').addEventListener('click', async () => {
      error(); clearResults(); setBusy(true); $('cn-progress').textContent = 'Iniciando…';
      try {
        const started = await api('/stations/' + stationSelect.value + '/forecast', {
          calibration: calibrationSelect.value, cycle: cycleSelect.value, months: Number(monthSelect.value),
        });
        const job = await poll(started.operation_id);
        if (job.status === 'failed') throw new Error(job.error);
        await showResult(started.operation_id, job);
        $('cn-results').scrollIntoView({block: 'start'});
      } catch (exc) { error(exc.message); }
      finally { setBusy(false); }
    });

    const id = workspace.dataset.operation;
    setBusy(true);
    $('cn-progress').textContent = 'Carregando configuração…';
    try {
      let job = id ? await api('/operations/' + id).catch(() => null) : null;
      if (job?.status === 'running') {
        if (job.kind === 'forecast' && [...stationSelect.options].some(option => option.value === String(job.code))) {
          stationSelect.value = String(job.code);
        }
        job = await poll(id, job);
      }
      const sameStation = job?.kind === 'forecast' && String(job.code) === stationSelect.value;
      // Both catalog routes use the same server lock.
      await loadCycles(sameStation ? job.settings.cycle : undefined, sameStation ? job.settings.months : undefined);
      await loadStation(sameStation ? job.settings.calibration : undefined);
      if (sameStation && job.status === 'completed') await showResult(id, job);
      if (sameStation && job.status === 'failed') error(job.error);
    } finally { setBusy(false); }
  }
  const preferred = new URLSearchParams(location.search).get('station');
  const saved = sessionStorage.getItem('cn3s-station');
  const catalog = [...$('cn-station').options];
  const restored = [preferred, saved].find(code => code && catalog.some(item => item.value === code));
  if (restored) $('cn-station').value = restored;
  if (step === 'estacao') {
    stationPage().catch(exc => error(exc.message));
    return;
  }
  if (step === 'calibrar') {
    calibrationPage().catch(exc => error(exc.message));
    return;
  }
  forecastPage().catch(exc => error(exc.message));
})();
