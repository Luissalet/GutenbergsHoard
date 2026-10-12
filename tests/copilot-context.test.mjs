import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const CC = require('../gutenberg_hoard/static/copilot-context.js');

test('changedFields returns only edited fields and previewFields clips long text', () => {
  assert.deepEqual(CC.changedFields({ a: 1, b: [1, 2], c: 'x' }, { a: 1, b: [1, 2], c: 'y', d: 'new' }), { c: 'y', d: 'new' });
  assert.deepEqual(CC.changedFields(undefined, { a: 1 }), { a: 1 });
  const clipped = CC.previewFields({ text: 'x'.repeat(5000), n: 3 });
  assert.equal(clipped.text.length, 1001);
  assert.equal(clipped.n, 3);
});

test('editorContext picks the first dirty form, lists several, and is undefined without forms', () => {
  const target = new EventTarget();
  assert.equal(CC.editorContext(target), undefined);
  target.addEventListener('gutenberg:context-request', e => e.detail.provide({ kind: 'one', object_id: null, dirty: false, fields: {} }));
  target.addEventListener('gutenberg:context-request', e => e.detail.provide({ kind: 'two', object_id: 'a:1', dirty: true, fields: { text: 'x' } }));
  target.addEventListener('gutenberg:context-request', e => e.detail.provide('junk'));
  const out = CC.editorContext(target);
  assert.equal(out.editor.kind, 'two');
  assert.deepEqual(out.editors.map(f => f.kind), ['one', 'two']);
});

test('debounced coalesces a burst into one trailing run', () => {
  let pending = null, runs = 0;
  const timers = { set: fn => { pending = fn; return 1; }, clear: () => { pending = null; } };
  const schedule = CC.debounced(() => { runs += 1; }, 250, timers);
  schedule(); schedule();
  pending();
  assert.equal(runs, 1);
});

test('buildContext lists the publication, page and stories; nothing real open means no objects', () => {
  const publication = { id: 'p1', title: 'Journal', page_count: 2, path: 'D:/data/j.designcraft', profile: { preset: 'A4', requested_colour_space: 'RGB', facing_pages: false, margins_pt: 36 }, undo_available: true };
  const inspection = { stories: [{ id: 1, frames: [{}], overset: false }, { id: 2, frames: [], overset: true }], spreads: [{ index: 1, pages: [{ parent: 'B-Master' }] }] };
  const ctx = CC.buildContext({ page: 'pages', publication, pageIndex: 1, inspection, storyId: 2, story: { text: 'y'.repeat(900) } });
  assert.deepEqual(ctx.project, { external_project_id: 'p1', title: 'Journal' });
  assert.deepEqual(ctx.active_objects.map(o => [o.kind, o.object_id]), [['publication', 'p1'], ['page', 'p1:1'], ['story', 'p1:1'], ['story', 'p1:2']]);
  assert.equal(ctx.active_objects[1].parent, 'B-Master');
  assert.equal(ctx.active_objects[3].selected, true);
  assert.equal(ctx.active_objects[3].preview.length, 301);
  assert.equal(ctx.active_objects[2].preview, undefined);
  assert.equal(ctx.view.page, 'pages');
  const empty = CC.buildContext({ page: 'workspace', publication: null });
  assert.deepEqual(empty.active_objects, []);
  assert.equal(empty.project, undefined);
});

// ---- the shipping app.js against stubbed DOM and API ----
class Element {
  constructor() { this.dataset = {}; this.value = ''; this.textContent = ''; this.innerHTML = ''; this.hidden = false; this.options = []; this.open = false; this.values = {}; this.classList = { add() {}, remove() {}, toggle() {} }; }
  addEventListener() {}
  setAttribute() {}
  removeAttribute() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const pub = { id: 'p1', title: 'Journal', page_count: 2, path: 'D:/data/j.designcraft', updated_at: 't', undo_available: false, profile: { preset: 'A4', requested_colour_space: 'RGB', facing_pages: false, margins_pt: 36 } };
const respond = (body, ok = true, status = 200) => ({ ok, status, statusText: 'x', json: async () => body, blob: async () => ({}) });

function boot(state) {
  const elements = new Map();
  const document = {
    querySelector: s => { if (!elements.has(s)) elements.set(s, new Element()); return elements.get(s); },
    querySelectorAll: () => [],
  };
  const window = new EventTarget();
  const calls = [];
  const fetch = async (path, options = {}) => {
    calls.push(`${options.method || 'GET'} ${path}`);
    if (state.failAll) return respond({ detail: 'down' }, false, 500);
    if (path === '/api/health') return respond({ configured: true });
    if (path === '/api/publications') return respond([pub]);
    if (path === '/api/publications/p1') return respond(pub);
    if (path.includes('/preview')) return respond({});
    if (path.endsWith('/inspection')) return respond(state.inspection);
    if (path.endsWith('/stories/1/text')) {
      state.saved = JSON.parse(options.body);
      return state.text !== state.saved.base_text ? respond({ detail: 'changed' }, false, 409) : respond({ publication: pub });
    }
    if (path.endsWith('/stories/1')) return respond({ text: state.text, frames: [{}], paragraphs: 1 });
    return respond({ detail: 'not found' }, false, 404);
  };
  class FormData { constructor(form) { this.form = form; } [Symbol.iterator]() { return Object.entries(this.form.values)[Symbol.iterator](); } has(k) { return k in this.form.values; } }
  const context = vm.createContext({ document, window, fetch, FormData, CustomEvent, EventTarget, Event, URL: { createObjectURL: () => 'blob:x' }, setTimeout, clearTimeout, console });
  if (state.existing) window.hoardCopilot = state.existing;
  vm.runInContext(fs.readFileSync('gutenberg_hoard/static/copilot-context.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('gutenberg_hoard/static/app.js', 'utf8'), context);
  return { window, calls, context, q: s => document.querySelector(s) };
}
const plain = x => JSON.parse(JSON.stringify(x));
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const inspection = { stories: [{ id: 1, frames: [{}], overset: false }], parents: [], spreads: [{ index: 0, pages: [{}] }], swatches: [] };

async function openPages(state) {
  const app = boot(state);
  await tick();
  vm.runInContext('selectPublication("p1")', app.context);
  await tick(80);
  return app;
}

test('context() reads the open publication through the app API and includes unsaved forms', async () => {
  const state = { inspection, text: 'Original words' };
  const app = await openPages(state);
  app.q('#story-text').value = 'Original words, edited';
  app.q('#frame-text').value = 'A heading';
  app.q('#ink-c').value = '0'; app.q('#ink-m').value = '100';
  app.q('#swatch-name').value = 'Print Ink'; app.q('#ink-y').value = '0'; app.q('#ink-k').value = '0';
  const ctx = plain(await app.window.hoardCopilot.context());
  assert.equal(ctx.project.external_project_id, 'p1');
  assert.deepEqual(ctx.active_objects.map(o => o.object_id), ['p1', 'p1:0', 'p1:1']);
  assert.equal(ctx.active_objects[2].preview, 'Original words');
  assert.equal(ctx.view.page, 'pages');
  assert.equal(ctx.view.editor.kind, 'story_edit');
  assert.deepEqual(ctx.view.editor.fields, { text: 'Original words, edited' });
  const kinds = Object.fromEntries(ctx.view.editors.map(f => [f.kind, f]));
  assert.deepEqual(kinds.frame_create.fields, { text: 'A heading' });
  assert.equal(kinds.frame_create.object_id, null);
  assert.deepEqual(kinds.swatch_create.fields, { c: 0, m: 100 });
  assert.equal(kinds.page_parent.dirty, false);
});

test('the creation dialog answers context-request as a new-object form', async () => {
  const app = boot({ inspection, text: 'x' });
  await tick();
  app.q('#new-dialog').open = true;
  app.q('#create-form').values = { title: 'Spring', pages: '12', preset: 'A4', margins: '36', colour_space: 'CMYK' };
  const ctx = plain(await app.window.hoardCopilot.context());
  assert.deepEqual(ctx.active_objects, []);
  assert.equal(ctx.view.editor.kind, 'publication_create');
  assert.equal(ctx.view.editor.object_id, null);
  assert.deepEqual(ctx.view.editor.fields, { title: 'Spring', pages: 12, colour_space: 'CMYK' });
});

test('context() never throws: fetch errors and the workspace view yield no object', async () => {
  const state = { inspection, text: 'x' };
  const app = await openPages(state);
  state.failAll = true;
  const ctx = plain(await app.window.hoardCopilot.context());
  assert.deepEqual(ctx.active_objects, []);
  assert.equal(ctx.project, undefined);
  state.failAll = false;
  vm.runInContext('showView("workspace")', app.context);
  const home = plain(await app.window.hoardCopilot.context());
  assert.deepEqual(home.active_objects, []);
  assert.equal(home.view.page, 'workspace');
});

test('turn end refreshes once for both triggers and keeps a half-typed story', async () => {
  const state = { inspection, text: 'Original words' };
  const app = await openPages(state);
  app.q('#story-text').value = 'My own rewrite';
  app.q('#frame-text').value = 'typed by hand';
  state.text = 'Changed by the assistant';
  const before = app.calls.filter(c => c === 'GET /api/publications').length;
  app.window.dispatchEvent(new Event('hoard:copilot-turn-end'));
  app.window.hoardCopilot.onTurnEnd();
  await tick(450);
  assert.equal(app.calls.filter(c => c === 'GET /api/publications').length - before, 1);
  assert.equal(app.q('#story-text').value, 'My own rewrite');
  assert.equal(app.q('#frame-text').value, 'typed by hand');
  // the document moved on: the stale save is refused instead of overwriting the assistant's edit
  await app.q('#save-story').onclick();
  assert.equal(state.saved.base_text, 'Original words');
});

test('an untouched story follows the reloaded document and saving sends only a changed story', async () => {
  const state = { inspection, text: 'Original words' };
  const app = await openPages(state);
  state.text = 'Changed by the assistant';
  app.window.hoardCopilot.onTurnEnd();
  await tick(450);
  assert.equal(app.q('#story-text').value, 'Changed by the assistant');
  const posts = () => app.calls.filter(c => c.startsWith('POST'));
  await app.q('#save-story').onclick();
  assert.equal(posts().length, 0);
  app.q('#story-text').value = 'Mine';
  await app.q('#save-story').onclick();
  assert.deepEqual(plain(state.saved), { text: 'Mine', base_text: 'Changed by the assistant' });
});

test('an existing window.hoardCopilot is left alone', async () => {
  const existing = { context: () => 1 };
  const app = boot({ inspection, text: 'x', existing });
  assert.equal(app.window.hoardCopilot, existing);
});
