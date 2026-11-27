(() => {
  const byId = id => document.getElementById(id);
  const button = byId('update');
  const note = byId('refresh-status');
  const initialStatus = document.currentScript.dataset.status;
  let progressDialog;
  function taskDialog() {
    progressDialog ??= window.createProgressDialog?.(document.querySelector('.progress-dialog'));
    return progressDialog;
  }
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const entries = [...document.querySelectorAll('.station-entry')];
  const normalize = text => text.normalize('NFD').replace(/\p{Mark}/gu, '').trim().toLowerCase();
  byId('find-station').oninput = event => {
    for (const entry of entries) {
      entry.hidden = !normalize(entry.querySelector('a').textContent).includes(normalize(event.target.value));
    }
    byId('no-match').hidden = entries.some(entry => !entry.hidden);
  };

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    if (response.redirected) {
      location.assign(response.url);
      throw new Error('Entre novamente para continuar.');
    }
    if (!response.headers.get('Content-Type')?.includes('application/json')) {
      throw new Error('Não foi possível concluir a operação.');
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Não foi possível concluir a operação.');
    return data;
  }

  const post = body => ({method: 'POST', headers: {'X-CSRF-Token': csrf}, body});
  const register = byId('register-dialog');
  const registerError = byId('register-error');
  const add = byId('add-station');
  add.onclick = () => {
    registerError.textContent = '';
    register.showModal();
  };
  byId('cancel-register').onclick = () => register.close();
  byId('register-station').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    add.disabled = true;
    const progress = taskDialog();
    register.close();
    progress?.open('Cadastrar estação');
    progress?.update({messages: ['Consultando o código ANA no inventário Hidro.']});
    try {
      const {url} = await api(form.action, post(new FormData(form)));
      location.assign(url);
    } catch (error) {
      progress?.close();
      registerError.textContent = error.message;
      register.showModal();
    } finally {
      add.disabled = false;
    }
  };

  const deletion = byId('delete-dialog');
  const deleteError = byId('delete-error');
  const confirm = byId('confirm-delete');
  let deleteURL;
  for (const trigger of document.querySelectorAll('[data-delete]')) {
    trigger.onclick = () => {
      deleteURL = trigger.dataset.delete;
      byId('delete-confirmation').textContent = 'Excluir ' + trigger.dataset.name
        + ' do catálogo e apagar suas observações e estatísticas locais?';
      deleteError.textContent = '';
      deletion.showModal();
    };
  }
  byId('cancel-delete').onclick = () => deletion.close();
  confirm.onclick = async () => {
    confirm.disabled = true;
    try {
      const {url} = await api(deleteURL, post());
      location.assign(url);
    } catch (error) {
      deleteError.textContent = error.message;
    } finally {
      confirm.disabled = false;
    }
  };

  let polling = false;
  async function refresh(start) {
    if (polling) return;
    polling = true;
    const progress = taskDialog();
    button.disabled = true;
    note.textContent = 'Atualizando o histórico completo…';
    progress?.open('Atualizar observações');
    let data;
    try {
      data = start ? await api(button.dataset.start, post()) : await api(button.dataset.poll);
      progress?.update(data);
      while (data.status === 'running') {
        await new Promise(resolve => setTimeout(resolve, 1000));
        data = await api(button.dataset.poll);
        progress?.update(data);
      }
      if (data.status === 'done') {
        if (progress?.finish) progress.finish('Ver dados', () => location.reload());
        else location.reload();
        return;
      }
      note.textContent = data.messages.at(-1) || 'Atualização interrompida. Tente novamente.';
    } catch {
      const message = 'Não foi possível acompanhar a atualização. Tente novamente.';
      progress?.update({progress: data?.progress, messages: [...(data?.messages || []), message]});
      note.textContent = message;
    } finally {
      polling = false;
      button.disabled = false;
    }
  }
  if (button) {
    button.onclick = () => refresh(true);
    if (initialStatus === 'running') refresh(false);
  }

  const charts = byId('station-charts');
  if (!charts) return;
  const chartStatus = byId('chart-status');
  const range = byId('range');

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const timer = setTimeout(() => {
        script.remove();
        reject(new Error('O navegador excedeu o tempo de carregamento do Plotly.'));
      }, 20000);
      script.onload = () => { clearTimeout(timer); resolve(); };
      script.onerror = () => {
        clearTimeout(timer);
        reject(new Error('O navegador não conseguiu baixar a biblioteca Plotly.'));
      };
      script.src = url;
      document.head.append(script);
    });
  }

  function showChartError(error) {
    chartStatus.textContent = error.message;
    chartStatus.hidden = false;
    console.error('Estações · Plotly', error);
  }

  async function initializeCharts() {
    range.disabled = true;
    try {
      const traces = JSON.parse(byId('series-data').textContent);
      if (!traces.length) {
        chartStatus.textContent = 'Sem observações para exibir.';
        return;
      }
      await loadScript(charts.dataset.plotly);
      if (typeof window.Plotly?.newPlot !== 'function') {
        throw new Error('A biblioteca Plotly foi baixada, mas não iniciou.');
      }
      loadScript(charts.dataset.locale).catch(() => {});

      const graphs = [];
      for (const [kind, unit] of [['cota', 'cm'], ['vazao', 'm³/s']]) {
        const graph = byId(kind);
        const series = traces.filter(trace => trace.kind === kind)
          .map(({name, x, y}) => ({name, x, y, type: 'scatter', mode: 'lines', connectgaps: false}));
        if (!series.length) {
          graph.textContent = 'Sem observações para esta variável.';
          continue;
        }
        try {
          await window.Plotly.newPlot(graph, series, {
            height: 320, margin: {l: 58, r: 18, t: 12, b: 45}, xaxis: {type: 'date'},
            yaxis: {title: {text: unit}}, showlegend: true,
            legend: {orientation: 'h'}, hovermode: 'x unified',
          }, {responsive: true, displaylogo: false, locale: 'pt-br'});
          graphs.push(graph);
        } catch (error) {
          graph.textContent = 'O Plotly não conseguiu renderizar este gráfico.';
          console.error('Estações · Plotly · ' + kind, error);
        }
      }

      const lastDay = traces.map(trace => trace.x[trace.x.length - 1]).sort().pop();
      range.onchange = async () => {
        let axis = {'xaxis.autorange': true};
        if (range.value !== 'all') {
          const lower = new Date(lastDay);
          lower.setUTCFullYear(lower.getUTCFullYear() - Number(range.value));
          axis = {'xaxis.range': [lower.toISOString().slice(0, 10), lastDay]};
        }
        try {
          await Promise.all(graphs.map(graph => window.Plotly.relayout(graph, axis)));
        } catch (error) {
          showChartError(error);
        }
      };
      range.disabled = !graphs.length;
      chartStatus.hidden = true;
    } catch (error) {
      showChartError(error);
    }
  }

  initializeCharts();
})();
