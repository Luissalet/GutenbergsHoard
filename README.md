> **Absorbed by [Writer's Hoard](https://github.com/Luissalet/Writers-Hoard-Desktop).**
> This project's capabilities are maintained in the merged Hoard, with independent modules initially disabled.
> The code and instructions below remain as historical reference; use the linked repository for the current installation.

# Gutenberg's Hoard

**A local publication desk for paginated editorial work.** Gutenberg manages publication files and their source links. The incorporated Gutenberg engine owns the native page layout, stories, frames, parent pages, styles, swatches, history and rendering.

The complete engine and desktop editor live in `native/`: source, ZIP format, libraries, licenses and local build. Initial source: DesignCraft0.2.1 revision `80b3e3cb74618b02f40b80ac7c2fa35e5da4e1af`, incorporated and maintained here. No origin checkout, package, CLI or GUI is operationally required. `native/PROVENANCE.json`, NOTICE and MIT/Apache/OFL notices retain attribution. Existing Hoard artwork replaces the reference app icon and its protected procedural mark was removed. This is not a universal parity claim.

## What works

- Create and reopen native `.gutenberg` documents with A4, A5, Letter or Legal page sizes, margins, facing pages and a requested color workflow.
- View the live MCP tool and resource catalogue, plus the whole Gutenberg command registry. The bundled baseline reports 25 MCP tools and 432 commands; discovery always reads the installed engine rather than hardcoding the list.
- Dispatch arbitrary native MCP tools, prompts and resources. For a publication, a stable session ID keeps the Gutenberg process and its document history alive across requests. The server saves the document after each publication edit. Restarting Gutenberg closes these engine sessions cleanly; native undo is process-local, and Gutenberg retains up to 30 prior file snapshots for restart-safe undo.
- Add editable text frames, read and edit native story text, create and apply parent pages, and create native CMYK process swatches from the page workspace. Continue in Gutenberg for threaded-story layout, typography, styles and advanced composition.
- Link an editorial publication to a source record with a `hoard://` reference through Hoard Hub. This preserves source ownership and does not copy source files.
- Render page previews with the native Gutenberg renderer.
- Export a native multipage PDF through Gutenberg `file.exportPdf`. Gutenberg verifies the produced file and page count, returns Gutenberg's export warnings, and checks whether the actual PDF yields any extractable text. That check does not prove every source story is searchable; font embedding can fall back to glyph outlines. The native export does not claim PDF/X or PDF/UA conformance.
- Keep the existing raster PDF export for compatibility and predictable RGB page images. Raster text is not searchable and vector paths, CMYK separations, spot inks, bleed metadata and PDF/X conformance are not preserved. A megapixel budget prevents large exports from exhausting memory; reduce render scale for long publications.
- Read existing named work profiles from Hoard Hub. Selecting one records a work context only; Gutenberg does not create accounts or start/stop the Hub profile.

## Setup on Windows

Python3.11+ and Rust1.95, with the shared HoardLink checkout available. Setup creates a dedicated environment, installs libraries and builds the owned CLI/editor:

```powershell
$env:HOARD_LINK_ROOT = 'C:\path\to\HoardLink'
./scripts/setup.ps1 -DebugEngine
```

Without `-DebugEngine`, setup requests a release build. This delivery verifies debug, without claiming an unexecuted release build. `python scripts/build_engine.py --debug` also builds and installs both binaries under `native/bin/`. Source and Cargo.lock are versioned. Historical `designcraft_cli/gui` settings remain data; they never select the engine. No origin application is downloaded or configured.

## Faustus assistant

Once the shared Hoard Link launcher is installed, the app shows the family's Faustus panel (a floating button). The conversation, the model and the tools live in Faustus; this app only tells the panel what is open.

- **Context per view.** An open publication is sent as kind `publication` with its real id (also as the panel's external project), title, page count, preset, colour space, facing pages, margins, file path, update time and whether undo is available. In the pages view it adds the open `page` (id `<publication>:<index>`, parent) and available `story` objects (id `<publication>:<story>`, frames, overset, selected), including selections beyond the first thirty stories. Only the selected saved story carries a 300-character preview; native tools retrieve its full saved text. The view, ids and pending forms are captured together before native resolution; navigation during that request affects the next context. Views without an open publication give no active object.
- **Unsaved fields.** The panel asks for them with the `gutenberg:context-request` window event. The forms `publication_create` (no id yet), `story_edit`, `page_parent`, `frame_create`, `swatch_create` and `source_link` answer with only the fields that changed, preserving their complete pending values. Unsaved text is available to the assistant even when the change is at the end of a long draft.
- **Refresh.** When the assistant finishes a turn the open view reloads from the document in place (`hoard:copilot-turn-end` / `window.hoardCopilot.onTurnEnd`, merged into one reload); forms keep what was typed.
- **Saving.** Saving a story sends the changed text with the text it was loaded from to the new `POST /api/publications/{id}/stories/{story}/text` (`text`, `base_text`). It is an atomic compare-and-set under the publication lock: if the story changed meanwhile it answers 409 (`StoryConflict`) and nothing is written until you reload. Without `base_text` the text is replaced.
- **Tests.** `node --test tests/copilot-context.test.mjs` and `python -m pytest tests/test_copilot_ui.py tests/test_story_save.py tests/test_publication_engine.py`.

The opt-in `tests/browser_copilot_context.py` regression accepts `--cli`, `--sdk` and `--output-dir` paths, with optional `--playwright-sitepackages`. It uses private data, headless native MCP, a real browser and the shared SDK with a scripted provider to verify long drafts, the selected thirty-first story, navigation during context resolution and a native tool turn with the same editor/draft retained. See [the API and copilot contract](docs/copilot.md).

## MCP

The plugin manifest is [`faustus-plugin.json`](faustus-plugin.json). It starts `python -m gutenberg_hoard.mcp_server` over stdio and points `PYTHONPATH` at both this checkout and the shared HoardLink checkout. The dedicated interpreter has the shared HoardLink library installed; the built engine is selected from this checkout.

The core Gutenberg tools are `gutenberg_publications`, `gutenberg_create_publication`, `gutenberg_engine_catalog`, `gutenberg_engine_session`, `gutenberg_engine_raw_session`, `gutenberg_undo`, `gutenberg_export_pdf`, and `gutenberg_link_source`. `gutenberg_export_pdf` accepts `renderer="native"` or `renderer="raster"`; raster remains the default for existing callers and accepts `scale`. Native export opens the tracked source without saving or mutating it, then returns the artifact URL, page count, extractable-text check and engine warnings. The two session tools expose generic native tool/resource/prompt dispatch without an allow-list. The catalog returns the schemas that the installed Gutenberg binary advertises. A caller can keep an independent session with a stable `session_id`; tracked publication edits are saved and snapshotted after each call.

Start the web API using `python -m gutenberg_hoard`; the MCP entrypoint uses stdio and has no web listener. Health and app routes are local: `/api/health`, `/api/publications`, `/api/native/catalog`, `/api/native/session`, and `/api/profiles`.

The stdio MCP and HTTP agent contract expose19 tools. The four historical `gutenberg_designcraft_*` names remain aliases. `gutenberg_render_page` exposes page preview and `gutenberg_open_editor` opens the complete incorporated desktop editor. See [API.md](docs/API.md).

## Data and compatibility

- `data/gutenberg.db` is a local catalog and history journal; publication source files remain individual `.gutenberg` archives under `data/publications/`.
- App code imports the shared `hoard-link` package. It does not vendor a fork or recreate the shared paths, atomic writes, tokens, references, theme, or profile contracts.
- `hoard://gutenberg/publication/<id>` identifies a Gutenberg-owned publication. Other Hoards keep their own source records and files.
- The detached engine, format and APIs evolve in this repository. Historical import support does not promise future compatibility with the reference application.

## Verification

Run `./.venv/Scripts/python.exe -m pytest -q` with the real built engine. QA uses temporary directories or an isolated instance with explicit `GUTENBERG_DATA_DIR`. Historical CLI/GUI settings pointed at nonexistent paths. Creation/editing, compare-and-set story text, parent pages, CMYK, embedded images, reopening, undo and native/raster multipage PDFs are covered. Shared publication metadata keeps the browser Undo button available after saving. No model is loaded.

Historical `.designcraft` ZIP/JSON documents import to `.gutenberg` working copies, preserving originals, IDs, linked-asset base directories, profiles and history. New saves write `application/vnd.gutenberg+zip` and `meta.format=gutenberg`; a restored historical snapshot may retain its old container, which the owned reader accepts. `original_native_path` is added without removing prior columns. The desktop/direct engine also opens a historical file toward a copy, and Save without an explicit path uses it. Explicit raw-session save destinations remain caller-selected operations.

## Upstream references

- [DesignCraft source and README](https://github.com/storytold/designcraft/blob/main/README.md)
- [DesignCraft releases](https://github.com/storytold/designcraft/releases)
- [DesignCraft MCP documentation](https://github.com/storytold/designcraft/blob/main/docs/mcp.md)
- [DesignCraft control protocol](https://github.com/storytold/designcraft/blob/main/docs/control-protocol.md)
- [HoardLink shared package](https://github.com/Luissalet/HoardLink)

## Licenses

Gutenberg's Hoard is MIT-licensed. DesignCraft remains a separate upstream dependency under its MIT or Apache-2.0 license. Its notices and bundled asset licenses remain with that separate release.
