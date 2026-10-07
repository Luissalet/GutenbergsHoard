const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let publications = [];
let current = null;
let inspection = null;
let page = 0;
let storyId = null;
let catalog = null;

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3600);
}

async function request(url, options = {}) {
  const res = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  let data;
  try { data = await res.json(); } catch { data = await res.text(); }
  if (!res.ok) throw Error(data.detail || data.message || res.statusText);
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function showView(view) {
  $$('.view').forEach(x => x.classList.toggle('active', x.id === `view-${view}`));
  $$('.nav').forEach(x => {
    const active = x.dataset.view === view;
    x.classList.toggle('active', active);
    if (active) x.setAttribute('aria-current', 'page');
    else x.removeAttribute('aria-current');
  });
  if (view === 'pages') renderPages();
  if (view === 'catalog') loadCatalog();
  if (view === 'settings') loadSettings();
}
$$('[data-view]').forEach(el => el.addEventListener('click', () => showView(el.dataset.view)));

async function refresh() {
  try { publications = await request('/api/publications'); renderPublications(); }
  catch (e) { toast(e.message); }
}

function renderPublications() {
  const grid = $('#publication-grid');
  $('#publication-count').textContent = `${publications.length} ${publications.length === 1 ? 'document' : 'documents'}`;
  if (!publications.length) {
    grid.innerHTML = '<div class="empty"><div class="empty-icon">▤</div><h3>Your next issue starts here</h3><p>Create a publication to set its page size, margins and document structure.</p><button class="primary" id="empty-create">Create publication</button></div>';
    $('#empty-create').onclick = openDialog;
    return;
  }
  grid.innerHTML = publications.map(p => `<article class="pub-card" data-id="${p.id}"><div class="pub-cover"><div class="paper-mock"><i></i><i></i><i></i><i></i></div></div><div class="pub-meta"><div><strong>${escapeHtml(p.title)}</strong><small>${p.page_count} pages · ${escapeHtml(p.profile.preset || 'A4')} · ${escapeHtml(p.profile.requested_colour_space || 'RGB')} · native</small></div><span class="dots">···</span></div></article>`).join('');
  $$('.pub-card').forEach(el => el.onclick = () => selectPublication(el.dataset.id));
}

async function selectPublication(id) {
  try { current = await request(`/api/publications/${id}`); page = 0; showView('pages'); }
  catch (e) { toast(e.message); }
}

function openDialog() { $('#new-dialog').showModal(); }
$('#new-publication').onclick = openDialog;
$('#empty-create').onclick = openDialog;
$('#create-form').addEventListener('submit', async e => {
  if (e.submitter?.value === 'cancel') return;
  e.preventDefault();
  const f = new FormData(e.currentTarget);
  const payload = Object.fromEntries(f);
  payload.pages = Number(payload.pages);
  payload.margins = Number(payload.margins);
  payload.facing_pages = f.has('facing_pages');
  $('#submit-create').disabled = true;
  try {
    const pub = await request('/api/publications', { method: 'POST', body: JSON.stringify(payload) });
    $('#new-dialog').close();
    toast('Native publication created.');
    await refresh();
    await selectPublication(pub.id);
  } catch (err) { toast(err.message); }
  finally { $('#submit-create').disabled = false; }
});

function parentPrefix(label) {
  const match = String(label || '').match(/^([A-Z])(?:-|\b)/);
  return match ? match[1] : String(label || '');
}

async function loadStory(id) {
  storyId = id ? Number(id) : null;
  $('#save-story').disabled = !storyId;
  if (!storyId) { $('#story-text').value = ''; $('#story-meta').textContent = 'No stories in this document.'; return; }
  try {
    const story = await request(`/api/publications/${current.id}/stories/${storyId}`);
    $('#story-text').value = story.text || '';
    $('#story-meta').textContent = `${story.frames?.length || 0} linked frame(s) · ${story.paragraphs || 0} paragraph(s)${story.overset ? ' · overset text' : ''}`;
  } catch (e) { $('#story-meta').textContent = e.message; toast(e.message); }
}

async function renderPages() {
  if (!current) return;
  $('#editor-title').textContent = current.title;
  $('#editor-subtitle').textContent = `${current.page_count} pages · ${current.profile.preset || 'A4'} · ${current.profile.requested_colour_space || 'RGB'} · editable DesignCraft source`;
  $('#page-total').textContent = current.page_count;
  $('#edit-native').disabled = false;
  $('#export-pdf').disabled = false;
  $('#add-frame').disabled = false;
  $('#add-swatch').disabled = false;
  $('#link-source').disabled = false;
  $('#undo-edit').disabled = !current.undo_available;
  $('#page-list').innerHTML = Array.from({ length: current.page_count }, (_, i) => `<button class="page-thumb ${page === i ? 'active' : ''}" data-page="${i}"><div class="mini-page"><span>${i + 1}</span></div><span>Page ${String(i + 1).padStart(2, '0')}</span></button>`).join('');
  $$('.page-thumb').forEach(b => b.onclick = () => { page = Number(b.dataset.page); renderPages(); });
  $('#page-label').textContent = `Page ${page + 1} of ${current.page_count}`;
  $('#canvas').innerHTML = '<div class="preview-empty">Rendering native page…</div>';
  try {
    const res = await fetch(`/api/publications/${current.id}/pages/${page}/preview?scale=1.2`);
    if (!res.ok) { const j = await res.json(); throw Error(j.detail); }
    $('#canvas').innerHTML = `<img alt="Rendered page ${page + 1}" src="${URL.createObjectURL(await res.blob())}">`;
    const img = $(`#page-list [data-page="${page}"] .mini-page`);
    img.innerHTML = `<img alt="Page ${page + 1}" src="/api/publications/${current.id}/pages/${page}/preview?scale=.35">`;
    inspection = await request(`/api/publications/${current.id}/inspection`);
    renderStructure(inspection);
  } catch (e) {
    $('#canvas').innerHTML = `<div class="preview-empty">${escapeHtml(e.message)}</div>`;
    toast(e.message);
  }
}

function renderStructure(data) {
  const stories = data.stories || [];
  $('#story-select').innerHTML = stories.length
    ? stories.map(s => `<option value="${s.id}">Story ${s.id} · ${s.frames?.length || 0} frame(s)${s.overset ? ' · overset' : ''}</option>`).join('')
    : '<option value="">No stories yet</option>';
  $('#story-select').disabled = !stories.length;
  if (stories.length) {
    const selected = stories.some(s => String(s.id) === String(storyId)) ? String(storyId) : String(stories[0].id);
    $('#story-select').value = selected;
    loadStory(selected);
  } else loadStory(null);
  const parents = data.parents || [];
  const options = parents.map(p => `<option value="${escapeHtml(parentPrefix(p.label))}">${escapeHtml(p.label)} · ${p.items} item(s)</option>`).join('');
  $('#parent-select').innerHTML = '<option value="">No parent page</option>' + options;
  $('#apply-parent').disabled = false;
  $('#new-parent').disabled = false;
  const spread = (data.spreads || []).find(s => s.index === page);
  const pageInfo = spread?.pages?.[0];
  if (pageInfo?.parent && parentPrefix(pageInfo.parent)) $('#parent-select').value = parentPrefix(pageInfo.parent);
  else $('#parent-select').value = '';
  const swatches = data.swatches || [];
  $('#swatch-list').innerHTML = swatches.slice(-8).map(name => `<span class="swatch-chip">${escapeHtml(name)}</span>`).join('');
}

$('#story-select').onchange = () => loadStory($('#story-select').value);
$('#save-story').onclick = async () => {
  if (!current || !storyId) return;
  $('#save-story').disabled = true;
  try {
    const data = await request(`/api/publications/${current.id}/native-actions`, { method: 'POST', body: JSON.stringify({ actions: [{ name: 'set_story_text', arguments: { story: storyId, text: $('#story-text').value } }] }) });
    current = data.publication;
    await refresh();
    await renderPages();
    toast('Story text saved to the native document.');
  } catch (e) { toast(e.message); }
  finally { $('#save-story').disabled = !storyId; }
};

$('#apply-parent').onclick = async () => {
  if (!current) return;
  try {
    await request(`/api/publications/${current.id}/parent`, { method: 'POST', body: JSON.stringify({ page, parent: $('#parent-select').value || null }) });
    current = await request(`/api/publications/${current.id}`);
    await renderPages();
    toast('Native parent page applied.');
  } catch (e) { toast(e.message); }
};

$('#new-parent').onclick = async () => {
  if (!current) return;
  const prefix = prompt('One-letter parent prefix (for example B):', 'B');
  if (!prefix) return;
  const name = prompt('Parent page name:', 'Editorial master');
  if (!name) return;
  try {
    await request(`/api/publications/${current.id}/native-actions`, { method: 'POST', body: JSON.stringify({ actions: [{ name: 'execute', arguments: { command: 'layout.parents.new', params: { prefix: prefix.trim().toUpperCase()[0], name } } }] }) });
    current = await request(`/api/publications/${current.id}`);
    await renderPages();
    toast('Native parent page created.');
  } catch (e) { toast(e.message); }
};

$('#add-frame').onclick = async () => {
  const text = $('#frame-text').value.trim();
  if (!text) return toast('Enter text for the frame first.');
  const action = { name: 'execute', arguments: { command: 'frame.create', params: { spread: page, rect: [55, 65, 540, 160], content: 'text', text } } };
  $('#add-frame').disabled = true;
  try {
    const data = await request(`/api/publications/${current.id}/native-actions`, { method: 'POST', body: JSON.stringify({ actions: [action] }) });
    $('#frame-text').value = '';
    $('#action-result').textContent = 'Frame saved to the native document. Undo is available.';
    current = data.publication;
    await refresh();
    await renderPages();
    toast('Editable text frame added.');
  } catch (e) { toast(e.message); }
  finally { $('#add-frame').disabled = false; }
};

$('#add-swatch').onclick = async () => {
  const payload = { name: $('#swatch-name').value.trim(), c: Number($('#ink-c').value), m: Number($('#ink-m').value), y: Number($('#ink-y').value), k: Number($('#ink-k').value) };
  if (!payload.name) return toast('Give the swatch a name.');
  try {
    const data = await request(`/api/publications/${current.id}/swatches`, { method: 'POST', body: JSON.stringify(payload) });
    current = data.publication;
    await refresh();
    await renderPages();
    toast('CMYK process swatch saved in the native document.');
  } catch (e) { toast(e.message); }
};

$('#undo-edit').onclick = async () => {
  if (!current) return;
  $('#undo-edit').disabled = true;
  try {
    await request(`/api/publications/${current.id}/undo`, { method: 'POST', body: '{}' });
    current = await request(`/api/publications/${current.id}`);
    await renderPages();
    toast('Previous native document snapshot restored.');
  } catch (e) { toast(e.message); }
  finally { $('#undo-edit').disabled = !current?.undo_available; }
};

async function exportPdf() {
  if (!current) return;
  const b = $('#export-pdf');
  const result = $('#pdf-export-result');
  const renderer = $('#pdf-renderer').value;
  result.hidden = true;
  b.disabled = true;
  b.textContent = renderer === 'native' ? 'Exporting native PDF…' : 'Rendering raster pages…';
  try {
    const d = await request(`/api/publications/${current.id}/export/pdf`, { method: 'POST', body: JSON.stringify({
      renderer, scale: Number($('#pdf-scale').value)
    }) });
    const warnings = Array.isArray(d.warnings) ? d.warnings : [];
    const searchability = d.renderer === 'native'
      ? (d.searchable_text ? `${d.text_searchability.extracted_characters} extractable text characters detected` : 'No extractable text detected')
      : 'Text is not searchable in raster output';
    result.innerHTML = `<b>${escapeHtml(String(d.pages))}-page ${escapeHtml(d.renderer)} PDF · ${escapeHtml(searchability)}</b>` +
      `<div><a href="${escapeHtml(d.url)}" target="_blank" rel="noopener">Open exported PDF</a></div>` +
      (warnings.length ? `<div>DesignCraft warnings: ${warnings.map(escapeHtml).join(' · ')}</div>` :
        (d.renderer === 'native' ? '<div>DesignCraft returned no export warnings.</div>' : ''));
    result.hidden = false;
    toast(`Exported ${d.pages}-page ${d.renderer} PDF.`);
    window.open(d.url, '_blank', 'noopener');
  } catch (e) { result.textContent = e.message; result.hidden = false; toast(e.message); }
  finally { b.disabled = false; syncPdfRenderer(); }
}
$('#export-pdf').onclick = exportPdf;
function syncPdfRenderer() {
  const native = $('#pdf-renderer').value === 'native';
  $('#pdf-scale').disabled = native;
  $('#export-pdf').textContent = native ? 'Export native PDF' : 'Export raster PDF';
}
$('#pdf-renderer').onchange = syncPdfRenderer;
syncPdfRenderer();

async function launchNative() {
  if (!current) return toast('Select a publication before opening DesignCraft.');
  try {
    await request(`/api/native/launch?publication_id=${encodeURIComponent(current.id)}`, { method: 'POST', body: '{}' });
    toast('Opened this native publication in DesignCraft.');
  } catch (e) { toast(e.message); }
}
$('#open-native').onclick = launchNative;
$('#edit-native').onclick = launchNative;

async function loadCatalog(force = false) {
  if (catalog && !force) return;
  $('#tool-list').innerHTML = '<div class="empty compact">Reading installed DesignCraft tools…</div>';
  try { catalog = await request('/api/native/catalog'); renderCatalog(); }
  catch (e) { $('#tool-list').innerHTML = `<div class="empty compact">${escapeHtml(e.message)}</div>`; }
}

function renderCatalog() {
  const tools = catalog.tools || [];
  const commands = catalog.commands || [];
  const cli = catalog.cli || { commands: [], help: '' };
  $('#catalog-summary').innerHTML = `<div class="stat"><b>${tools.length}</b><small>Live native MCP tools</small></div><div class="stat"><b>${commands.length}</b><small>Native command registry entries</small></div><div class="stat"><b>${cli.commands.length}</b><small>Documented CLI verbs</small></div><div class="stat"><b>${(catalog.prompts || []).length + (catalog.resources || []).length + (catalog.resource_templates || []).length}</b><small>Additional MCP resources and prompts</small></div>`;
  $('#tool-list').innerHTML = tools.map(t => `<article class="tool-item"><code>${escapeHtml(t.name)}</code><p>${escapeHtml(t.description || 'Native DesignCraft MCP tool')}</p></article>`).join('') || '<div class="empty compact">No tools were returned by the native server.</div>';
  $('#command-list').textContent = JSON.stringify(commands, null, 2);
  $('#cli-command').innerHTML = cli.commands.map(c => `<option value="${escapeHtml(c.command)}">${escapeHtml(c.command)}</option>`).join('');
  $('#cli-help').textContent = cli.help || 'No CLI help returned.';
  $('#catalog-filter').oninput = e => $$('#tool-list .tool-item').forEach(el => { el.hidden = !el.textContent.toLowerCase().includes(e.target.value.toLowerCase()); });
}
$('#refresh-catalog').onclick = () => loadCatalog(true);
$('#run-cli').onclick = async () => {
  try {
    const argv = JSON.parse($('#cli-argv').value || '[]');
    if (!Array.isArray(argv) || argv.some(arg => typeof arg !== 'string')) throw Error('Arguments must be a JSON array of strings.');
    const result = await request('/api/native/cli', { method: 'POST', body: JSON.stringify({ command: $('#cli-command').value, argv, timeout_s: 120 }) });
    $('#cli-output').textContent = `exit code: ${result.returncode}\n\n${result.stdout}${result.stderr ? `\nSTDERR\n${result.stderr}` : ''}${result.stdout_truncated || result.stderr_truncated ? '\n(output truncated at 2 MB)' : ''}`;
  } catch (e) { $('#cli-output').textContent = e.message; toast(e.message); }
};

async function loadSettings() {
  try {
    const [c, p] = await Promise.all([request('/api/config'), request('/api/profiles')]);
    $('#settings-card').innerHTML = `<div class="settings-row"><span>DesignCraft CLI</span><code>${escapeHtml(c.designcraft_cli || 'Not configured')}</code></div><div class="settings-row"><span>Desktop editor</span><code>${escapeHtml(c.designcraft_gui || 'Not found next to CLI')}</code></div><div class="settings-row"><span>Application data</span><code>${escapeHtml(c.data_dir)}</code></div><div class="settings-row"><span>Native source</span><code>.designcraft · original document retained</code></div><div class="settings-row"><span>PDF export</span><code>Native DesignCraft or RGB raster · artifact reports warnings · no PDF/X claim</code></div>`;
    const select = $('#hub-profile');
    select.innerHTML = '<option value="">No profile selected</option>' + p.profiles.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    select.value = p.selected || '';
    $('#profile-state').textContent = p.available ? 'Profiles loaded from Hoard Hub' : 'Hoard Hub not connected';
    select.disabled = !p.available;
    select.onchange = async () => {
      try { await request('/api/profiles/selected', { method: 'POST', body: JSON.stringify({ name: select.value }) }); toast('Work context saved.'); }
      catch (e) { toast(e.message); }
    };
  } catch (e) { toast(e.message); }
}

async function health() {
  try {
    const d = await request('/api/health');
    $('#engine-state').textContent = d.configured ? 'DesignCraft connected' : 'DesignCraft needs setup';
    $('#engine-state').classList.toggle('ready', d.configured);
  } catch { $('#engine-state').textContent = 'Local service'; }
}

$$('.text-button[data-view]').forEach(el => el.onclick = () => showView(el.dataset.view));
health();
refresh();
