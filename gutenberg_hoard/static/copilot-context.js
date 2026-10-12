"use strict";
// Pure helpers that describe the open view to the family assistant panel.
// Loaded as a classic script in the browser and required by node tests.
(function (root) {
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const MAX_FIELD = 1000;

  // Saved story previews are summaries; tools can retrieve their full text.
  function clip(value, max) {
    const limit = max || MAX_FIELD;
    const text = String(value == null ? "" : value);
    return text.length > limit ? text.slice(0, limit) + "…" : text;
  }

  // Only the fields the person actually changed; used for partial saves and form snapshots.
  function changedFields(initial, draft) {
    const base = initial || {};
    return Object.fromEntries(Object.entries(draft || {}).filter(([key, value]) => !same(value, base[key])));
  }

  function previewFields(fields) {
    // Unsaved fields have no native document copy from which to recover a tail.
    return { ...(fields || {}) };
  }

  // Ask every open form for its state. Each form answers with
  // detail.provide({kind, object_id, dirty, fields}); answers are keyed by kind.
  function editorContext(target, detail) {
    const found = {};
    target.dispatchEvent(new CustomEvent("gutenberg:context-request", {
      detail: {
        ...(detail || {}),
        provide: (value) => { if (value && typeof value === "object" && value.kind) found[value.kind] = value; },
      },
    }));
    const kinds = Object.keys(found);
    if (!kinds.length) return undefined;
    const first = kinds.find((k) => found[k].dirty) || kinds[0];
    const out = { editor: found[first], editors: kinds.length > 1 ? kinds.map((k) => found[k]) : undefined };
    return out;
  }

  // One trailing call per burst, so the event and onTurnEnd trigger one refresh.
  function debounced(run, wait, timers) {
    // Wrapped: calling the bare browser timers as methods of this object throws "Illegal invocation".
    const t = timers || { set: (fn, ms) => setTimeout(fn, ms), clear: (h) => clearTimeout(h) };
    let handle = null;
    return function schedule() {
      if (handle !== null) t.clear(handle);
      handle = t.set(() => { handle = null; run(); }, wait);
    };
  }

  // publication: GET /api/publications/{id} or null when nothing real is open.
  // inspection: GET .../inspection; story: GET .../stories/{id} of the selected story.
  function buildContext({ page, publication, pageIndex, inspection, storyId, story, forms } = {}) {
    const out = { active_objects: [], view: { page: page || "workspace" } };
    const pub = publication && publication.id ? publication : null;
    if (pub) {
      const profile = pub.profile || {};
      out.project = { external_project_id: String(pub.id), title: pub.title };
      out.active_objects.push({
        kind: "publication", object_id: pub.id, title: pub.title, page_count: pub.page_count,
        preset: profile.preset, colour_space: profile.requested_colour_space, facing_pages: profile.facing_pages,
        margins_pt: profile.margins_pt, file: pub.path, updated_at: pub.updated_at, undo_available: !!pub.undo_available,
      });
      if (out.view.page === "pages") {
        const idx = Number.isInteger(pageIndex) ? pageIndex : 0;
        const spread = ((inspection && inspection.spreads) || []).find((s) => s.index === idx);
        const pageInfo = spread && spread.pages && spread.pages[0];
        out.active_objects.push({
          kind: "page", object_id: `${pub.id}:${idx}`, title: `Page ${idx + 1} of ${pub.page_count}`,
          page_index: idx, parent: pageInfo ? pageInfo.parent : undefined,
        });
        for (const s of ((inspection && inspection.stories) || [])) {
          const selected = String(s.id) === String(storyId);
          out.active_objects.push({
            kind: "story", object_id: `${pub.id}:${s.id}`, story_id: s.id, title: `Story ${s.id}`,
            frames: s.frames ? s.frames.length : 0, overset: !!s.overset, selected,
            preview: selected && story && typeof story.text === "string" ? clip(story.text, 300) : undefined,
          });
        }
        out.view.object_id = pub.id;
        out.view.page_index = idx;
      } else {
        out.view.object_id = pub.id;
      }
    }
    if (forms && forms.editor) {
      out.view.editor = forms.editor;
      if (forms.editors) out.view.editors = forms.editors;
    }
    return out;
  }

  const api = { clip, changedFields, previewFields, editorContext, debounced, buildContext };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.gutenbergCopilotContext = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
