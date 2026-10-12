# Shared assistant API and context

Gutenberg mounts HoardLink's canonical `install_copilot` transport before its static routes. The shared package supplies `/api/copilot/info`, `/api/copilot/panel.js`, `/api/copilot/launcher.js` and `/api/copilot/proxy`. Both JSON and multipart turns retain the native origin and stream through the same relay. Gutenberg adds no chat history store, model loop or panel portal.

`window.hoardCopilot.context()` captures the view, publication id, page index, selected native story id and form values before resolving the publication through its GET route. Inspection and story reads use that snapshot. A view or selection change during resolution is represented by the next request. Missing publications yield no active object; creation forms carry null object ids. Publication, page and story references use the real native ids, including a selected story beyond the first thirty entries.

`gutenberg:context-request` asks the forms for their changed fields. `view.editor` identifies the first dirty editor; `view.editors` preserves the other open form snapshots. Pending strings are sent in full, since native story tools only know saved text. The selected saved story's separate preview is a summary; `gutenberg_get_story` returns the complete saved story.

`hoard:copilot-turn-end` and `window.hoardCopilot.onTurnEnd()` coalesce into one refresh. Lists and native inspection refresh in place, retaining form nodes and unsaved values. The shared SDK owns locale, conversation and turn state.

`POST /api/publications/{id}/stories/{story}/text` accepts `{text, base_text?}`. With `base_text`, the native story read and write share the publication lock: a changed base returns409 without writing. Without a base it retains ordinary explicit replacement semantics. The existing thirteen MCP tools and generic native session dispatcher remain available; this UI correction does not add a second tool catalogue.

Run `node --test tests/copilot-context.test.mjs` and the Python suites for fast regressions. `tests/browser_copilot_context.py` is an opt-in private native test accepting the CLI, shared SDK and output paths. It exercises real stdio MCP and saved native files with a scripted HTTP/SSE provider; it does not start Faustus or a model and restricts its browser/HTTP connections to its own temporary servers.
