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
    if (response.status === 404) throw new Error('Operação expirada ou indisponível.');
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Resposta indisponível. Recarregue a página.');
    const data = await response.json();
    if (data.login_required) { location.reload(); throw new Error(data.error); }
    if (!response.ok) throw Object.assign(new Error(data.error || 'Operação expirada ou indisponível.'), {status: response.status});
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
  async function stationPage() {
    const select = $('cn-station'), dialog = $('cn-dialog');
    const wait = () => new Promise(resolve => setTimeout(resolve, 1100));
    let current = null, variable = 'cota', creating = false, mapKey = '';
    const refreshes = new Map();

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
          $('cn-refresh').disabled = false;
        }
      }
    }

    async function load(existingId) {
      const code = select.value, version = ++selection;
      const pending = refreshes.get(code);
      $('cn-series-progress').hidden = true; $('cn-refresh').disabled = false;
      $('cn-inventory').open = false;
      current = null; mapKey = ''; $('cn-details').hidden = true; error();
      $('cn-station-info').textContent = code ? 'Carregando ficha…' : 'Selecione uma estação para visualizar os dados.';
      rememberStation(code);
      if (!code) return;
      try {
        const data = await api('/stations/' + code + '?view=station');
        if (version !== selection) return;
        renderFicha(data); status();
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
      $('prepare').hidden=!needs.length;
      const boundsOK=checkBounds();
      $('prepare').disabled=running || !valid || Boolean(draft);
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
    async function execute(prepare) {
      const code=select.value, start=$('start').value+'-01', end=$('end').value+'-01';
      const needs=availability();
      if (prepare && needs.some(k=>series[k]) && !window.confirm('Atualizar os arquivos mensais compartilhados de '+start+' a '+end+'? Os meses fora do intervalo serão preservados.')) return;
      lock(true); $('setupError').textContent='';
      try {
        if (prepare) {
          $('prepStatus').hidden=false;
          $('prepProgress').max=needs.length;
          $('prepProgress').value=0;
          for (const [index,key] of needs.entries()) {
            const prefix=(index+1)+' de '+needs.length+' · '+(key==='rain'?'Chuva MERGE':'Vazão SQL');
            $('prepText').textContent=prefix;
            const job=await api('/stations/'+code+'/inputs',{series:key,start,end,replace:true});
            await watch(job.operation_id, state=>{$('prepText').textContent=prefix+' · '+state.phase;});
            $('prepProgress').value=index+1;
          }
          $('prepText').textContent='Preparo concluído.';
          await coverage(false);
        } else {
          const bounds=Object.fromEntries(Array.from($('bounds').rows,tr=>[tr.dataset.param,Array.from(tr.querySelectorAll('input'),i=>i.valueAsNumber)]));
          const payload={start,end,bounds,objective:$('objective').value,train_ratio:Number($('ratio').value)/100,
            seed:$('seed').valueAsNumber,warmup_steps:$('warm').valueAsNumber,until_convergence:$('converge').checked,
            maxiter:$('iter').valueAsNumber,tol:$('converge').checked?$('tol').valueAsNumber:0.0001,atol:$('converge').checked?$('atol').valueAsNumber:0};
          $('execution').hidden=false;
          $('runStatus').textContent='Iniciando calibração…';
          const job=await api('/stations/'+code+'/calibrate',payload);
          await trainReview(job.operation_id);
        }
      } catch (exc) {
        if (prepare) {
          $('prepText').textContent += ' · Preparo interrompido.';
          await coverage(false).catch(()=>{});
        } else {
          $('runStatus').textContent = exc.message;
          $('runProgress').hidden = true;
        }
        $('setupError').textContent=exc.message;
      } finally {
        lock(false);
      }
    }
    $('create').onclick=async()=>{
      form.reset(); solverMode(); $('setupError').textContent='';
      $('panel').hidden=$('prepStatus').hidden=$('execution').hidden=true;
      $('calibration-setup').hidden=false;
      review(null,true);
      $('stamp').textContent=overview?.updated_at?'Resumo de '+overview.updated_at:'Resumo ausente. Atualize as estatísticas na etapa Estação.';
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
    $('prepare').onclick=()=>execute(true);
    form.onsubmit=e=>{e.preventDefault();$('runProgress').hidden=false;execute(false);};
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
  function rememberStation(code) {
    sessionStorage.setItem('cn3s-station', code);
    const page = new URL(location.href);
    if (code) page.searchParams.set('station', code);
    else page.searchParams.delete('station');
    history.replaceState(history.state, '', page);
    document.querySelectorAll('.cn-section-nav a').forEach(link => {
      const url = new URL(link.href); url.searchParams.set('station', code); link.href = url;
    });
  }
  async function loadStation() {
    error();
    const version = ++selection, code = $('cn-station').value;
    station = null; clearResults();
    if ($('cn-input-download')) $('cn-input-download').hidden = true;
    for (const id of ['cn-inputs', 'cn-parameter-values']) $(id)?.replaceChildren();
    $('cn-calibration-select')?.replaceChildren(option('', 'Selecione uma calibração'));
    if ($('cn-calibration-info')) $('cn-calibration-info').textContent = '';
    rememberStation(code);
    readiness();
    if (!code) { $('cn-station-info').textContent = 'Selecione uma estação.'; return; }
    const data = await api(`/stations/${code}`);
    if (version !== selection) return;
    station = data;
    const selectedOption = [...$('cn-station').options].find(o => o.value === code);
    if (selectedOption) selectedOption.textContent = `${data.metadata.station_name} · ${code}`;
    const m = data.metadata;
    $('cn-station-info').textContent = `${m.station_name} · ${m.station_code} · Cobacia ${m.cobacia} · Área do inventário: ${number(m.drainage_area)} km² · Área hidrográfica: ${number(m.drainage_area_geo)} km²`;
    if (data.overview) $('cn-station-info').append(` · Latitude: ${number(data.overview.latitude)} · Longitude: ${number(data.overview.longitude)} (graus decimais)`);
    if ($('cn-inputs')) for (const [name, series] of Object.entries(data.series)) {
      addTable($('cn-inputs'), `${name === 'rain' ? 'Chuva (mm/mês)' : 'Vazão (m³/s)'} · ${series.start} a ${series.end} · ${series.rows} meses · ${series.missing} ausentes`, series.preview);
    }
    if ($('cn-input-download') && data.series.rain && data.series.discharge) {
      $('cn-input-download').href = `${root}/stations/${code}/inputs.csv`; $('cn-input-download').hidden = false;
      $('cn-cal-end').value = data.series.rain.end.slice(0, 7);
    }
    if (!$('cn-calibration-select')) { readiness(); return; }
    data.calibrations.forEach(c => $('cn-calibration-select').append(option(c.id, calibrationLabel(c), !c.compatible)));
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
      const code = $('cn-station').value;
      const job = await api(`/stations/${code}/${kind}`, payload); await poll(job.operation_id);
    } catch (exc) { setBusy(false); error(exc.message); }
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
  $('cn-station').addEventListener('change', () => loadStation().catch(exc => error(exc.message)));
  $('cn-calibration-select')?.addEventListener('change', () => {clearResults(); calibrationInfo();});
  for (const id of ['cn-cycle', 'cn-as-of']) $(id)?.addEventListener('change', () => {clearResults(); horizon();});
  $('cn-months')?.addEventListener('change', clearResults);
  $('cn-replace')?.addEventListener('change', readiness);
  for (const series of ['rain', 'discharge']) $(`cn-save-${series}`)?.addEventListener('click', () => operate('inputs', {series, start: $('cn-start').value + '-01', end: $('cn-end').value + '-01', replace: $('cn-replace').checked}));
  $('cn-run')?.addEventListener('click', () => operate('forecast', {calibration: $('cn-calibration-select').value, cycle: $('cn-cycle').value, as_of: $('cn-as-of').value, months: Number($('cn-months').value)}));
  document.querySelectorAll('.cn-section-nav a').forEach(link => link.addEventListener('click', event => { if (busy) event.preventDefault(); }));
  async function initialize() {
    const job = workspace.dataset.operation ? await api(`/operations/${workspace.dataset.operation}`).catch(() => null) : null;
    if (job?.status === 'running' && job.kind === 'overview') {
      // Finish the background read before requesting lock-protected forecast files.
      let active = job;
      while (active.status === 'running') {
        await new Promise(resolve => setTimeout(resolve, 1000));
        active = await api('/operations/' + workspace.dataset.operation);
      }
    } else if (job?.status === 'running') {
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
