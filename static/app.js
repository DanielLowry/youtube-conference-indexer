(() => {
  const $ = id => document.getElementById(id);
  const themeButton = $('theme-toggle');
  const themeLabel = () => {
    const dark = document.documentElement.dataset.theme === 'dark';
    $('theme-label').textContent = dark ? 'Light' : 'Dark';
    themeButton.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
  };
  themeButton.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('extractor-theme', theme); } catch (_) { /* Theme still works without storage. */ }
    themeLabel();
  });
  themeLabel();

  const form = $('extraction-form');
  if (form) {
    if ($('form-values')) {
      const values = JSON.parse($('form-values').textContent);
      Object.entries(values).forEach(([name, value]) => {
        const field = form.elements.namedItem(name);
        if (!field) return;
        if (name === 'output_formats') {
          form.querySelectorAll('[name=output_formats]').forEach(input => { input.checked = value.includes(input.value); });
        } else if (name !== 'mode' || ['search','playlist','channel'].includes(value)) {
          field.value = value;
        }
      });
    }
    const tokens = value => [...new Set(value.split(/[,\n]/).map(x => x.trim()).filter(Boolean))];
    const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
    const update = () => {
      const mode = form.elements.mode.value;
      document.querySelectorAll('[data-modes]').forEach(section => {
        const visible = section.dataset.modes.split(' ').includes(mode);
        section.hidden = !visible;
        section.querySelectorAll('input,select,textarea').forEach(input => { input.disabled = !visible; });
      });
      $('query').required = mode === 'search';
      $('playlist_id').required = mode === 'playlist';
      $('channel_id').required = mode === 'channel';
      const count = mode === 'search' ? tokens($('query').value).length : mode === 'playlist' ? tokens($('playlist_id').value).length : ($('channel_id').value.trim() ? 1 : 0);
      $('query-count').textContent = `${tokens($('query').value).length} queries queued`;
      $('source-count').textContent = count;
      $('page-value').value = $('max_pages').value;
      $('summary-pages').textContent = $('max_pages').value;
      const args = ['python -m app.cli run', `--mode ${mode}`];
      if (mode === 'search') tokens($('query').value).forEach(q => args.push(`--query ${quote(q)}`));
      if (mode === 'playlist') tokens($('playlist_id').value).forEach(p => args.push(`--playlist-id ${quote(p)}`));
      if (mode !== 'playlist' && $('channel_id').value.trim()) args.push(`--channel-id ${quote($('channel_id').value.trim())}`);
      args.push(`--max-pages ${$('max_pages').value}`, `--stop-after-empty-pages ${$('stop_after_empty_pages').value}`);
      if (mode === 'search') {
        ['published_after','published_before','video_duration','order_by','region_code','relevance_language','safe_search'].forEach(id => {
          if ($(id).value) args.push(`--${id.replaceAll('_','-')} ${quote($(id).value)}`);
        });
      }
      const formats = [...form.querySelectorAll('[name=output_formats]:checked')].map(el => el.value);
      (formats.length ? formats : ['jsonl','csv']).forEach(fmt => args.push(`--output-format ${fmt}`));
      args.push('--output-root ./runs');
      $('cli-command').textContent = args.join(' \\\n  ');
    };
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    document.querySelectorAll('[data-clear]').forEach(button => button.addEventListener('click', () => { $(button.dataset.clear).value = ''; update(); }));
    $('reset-dates').addEventListener('click', () => { $('published_after').value = ''; $('published_before').value = ''; update(); });
    $('copy-cli').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText($('cli-command').textContent); $('copy-status').textContent = 'Copied to clipboard.'; }
      catch (_) { $('copy-status').textContent = 'Could not copy. Select the command and copy it manually.'; }
    });
    update();
  }

  document.querySelectorAll('form').forEach(current => current.addEventListener('submit', () => {
    const submit = current.querySelector('button[type=submit]');
    if (submit) { submit.disabled = true; submit.textContent = 'Submitting…'; }
  }));

  const list = $('run-list');
  if (list) {
    const applyFilters = () => {
      const search = $('run-search')?.value.trim().toLowerCase() || '';
      const mode = $('run-mode')?.value || '';
      const status = $('run-status')?.value || '';
      let visible = 0;
      list.querySelectorAll('[data-run-id]').forEach(card => {
        card.hidden = !card.dataset.runId.toLowerCase().includes(search) || (mode && card.dataset.mode !== mode) || (status && card.dataset.status !== status);
        if (!card.hidden) visible++;
      });
      if ($('no-matches')) $('no-matches').hidden = visible > 0 || (!search && !mode && !status);
      const empty = list.querySelector('.empty-state');
      if (empty) empty.hidden = !!(search || mode || status);
      const cards = [...list.querySelectorAll('[data-run-id]')];
      if ($('stat-runs')) {
        $('stat-runs').textContent = cards.length;
        $('stat-active').textContent = cards.filter(c => ['queued','running'].includes(c.dataset.status)).length;
        $('stat-videos').textContent = cards.reduce((sum,c) => sum + Number(c.querySelectorAll('dd')[0].textContent), 0).toLocaleString();
        $('stat-quota').textContent = cards.reduce((sum,c) => sum + Number(c.querySelectorAll('dd')[3].textContent), 0).toLocaleString();
      }
    };
    ['run-search','run-mode','run-status'].forEach(id => $(id)?.addEventListener('input', applyFilters));
    $('clear-filters')?.addEventListener('click', () => { ['run-search','run-mode','run-status'].forEach(id => $(id).value = ''); applyFilters(); });
    const poll = async () => {
      if (!document.hidden && !list.contains(document.activeElement)) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
          const response = await fetch(list.dataset.poll, {signal:controller.signal});
          if (!response.ok) throw new Error('Polling failed');
          list.innerHTML = await response.text();
          applyFilters();
          if ($('poll-status')) $('poll-status').textContent = 'Live · Updates every 4s';
        } catch (_) {
          if ($('poll-status')) $('poll-status').textContent = 'Update failed · Retrying automatically';
        } finally { clearTimeout(timeout); }
      }
      setTimeout(poll, 4000);
    };
    applyFilters();
    setTimeout(poll, 4000);
  }
})();
