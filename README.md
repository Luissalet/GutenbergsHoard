# Gutenberg's Hoard

**A local publication desk for paginated editorial work.** Gutenberg manages publication files and their source links. DesignCraft owns the native page layout, stories, frames, parent pages, styles, swatches, history and rendering.

This is an operational first release, not a claim of feature parity with desktop publishing suites. The verified upstream engine here is DesignCraft `0.2.1` (release commit `80b3e3c`, 2026-10-06), MIT or Apache-2.0. The installed release exposes native PDF export through `file.exportPdf`. Gutenberg keeps the complete native MCP catalogue and dispatch path available while adding publication cataloguing, source references, a page workspace, persistent agent sessions, save snapshots/undo, a local preview workflow and two PDF export renderers.

## What works

- Create and reopen native `.designcraft` documents with A4, A5, Letter or Legal page sizes, margins, facing pages and a requested color workflow.
- View the live MCP tool and resource catalogue, plus the whole DesignCraft command registry. The bundled baseline reports 25 MCP tools and 432 commands; discovery always reads the installed engine rather than hardcoding the list.
- Dispatch arbitrary native MCP tools, prompts and resources. For a publication, a stable session ID keeps the DesignCraft process and its document history alive across requests. The server saves the document after each publication edit. Restarting Gutenberg closes these engine sessions cleanly; native undo is process-local, and Gutenberg retains up to 30 prior file snapshots for restart-safe undo.
- Add editable text frames, read and edit native story text, create and apply parent pages, and create native CMYK process swatches from the page workspace. Continue in DesignCraft for threaded-story layout, typography, styles and advanced composition.
- Link an editorial publication to a source record with a `hoard://` reference through Hoard Hub. This preserves source ownership and does not copy source files.
- Render page previews with the native DesignCraft renderer.
- Export a native multipage PDF through DesignCraft `file.exportPdf`. Gutenberg verifies the produced file and page count, returns DesignCraft's export warnings, and checks whether the actual PDF yields any extractable text. That check does not prove every source story is searchable; font embedding can fall back to glyph outlines. The native export does not claim PDF/X or PDF/UA conformance.
- Keep the existing raster PDF export for compatibility and predictable RGB page images. Raster text is not searchable and vector paths, CMYK separations, spot inks, bleed metadata and PDF/X conformance are not preserved. A megapixel budget prevents large exports from exhausting memory; reduce render scale for long publications.
- Read existing named work profiles from Hoard Hub. Selecting one records a work context only; Gutenberg does not create accounts or start/stop the Hub profile.

## Setup on Windows

Install Python 3.11 or newer and obtain the separate DesignCraft release from its official project. Do not copy its executable into this repository. Setup creates Gutenberg's dedicated `.venv`, installs HoardLink editable into it, and installs this app:

```powershell
$env:HOARD_LINK_ROOT = 'C:\path\to\HoardLink'
$env:GUTENBERG_DESIGNCRAFT_CLI = 'D:\path\to\designcraft-cli.exe'
.\scripts\setup.ps1 -HoardLink $env:HOARD_LINK_ROOT -DesignCraftCli $env:GUTENBERG_DESIGNCRAFT_CLI
```

The installer writes the DesignCraft path to ignored `local-config.json` only when no path is already configured. Later setup runs preserve the existing value. The app reads `GUTENBERG_DESIGNCRAFT_CLI` first, then this local file. Launch with the dedicated Python:

```powershell
.\.venv\Scripts\python.exe .\scripts\launch.py
```

The Hub launches the app on loopback port `5218` in strict mode and starts stdio MCP with the same `.venv`. For a manual launch, the launcher searches for a free port from `5218`; `GUTENBERG_PORT=0` asks the OS for a free port. App data defaults to `./data`, and the DesignCraft runtime profile uses a subfolder there. The app has no login or account-management screen.

The desktop action opens the selected `.designcraft` file through the documented DesignCraft control channel: the GUI is started as `designcraft.exe --control <port>`, then the verified CLI invokes `file.open {path}`. The control port is loopback-only and selected from an unused local port.

## MCP

The plugin manifest is [`faustus-plugin.json`](faustus-plugin.json). It starts `python -m gutenberg_hoard.mcp_server` over stdio and points `PYTHONPATH` at both this checkout and the shared HoardLink checkout. Set `FAUSTUS_PYTHON`, `GUTENBERG_DESIGNCRAFT_CLI`, and `HOARDLINK_DIR` in the host's app configuration.

The core Gutenberg tools are `gutenberg_publications`, `gutenberg_create_publication`, `gutenberg_designcraft_catalog`, `gutenberg_designcraft_session`, `gutenberg_designcraft_raw_session`, `gutenberg_undo`, `gutenberg_export_pdf`, and `gutenberg_link_source`. `gutenberg_export_pdf` accepts `renderer="native"` or `renderer="raster"`; raster remains the default for existing callers and accepts `scale`. Native export opens the tracked source without saving or mutating it, then returns the artifact URL, page count, extractable-text check and engine warnings. The two session tools expose generic native tool/resource/prompt dispatch without an allow-list. The catalog returns the schemas that the installed DesignCraft binary advertises. A caller can keep an independent session with a stable `session_id`; tracked publication edits are saved and snapshotted after each call.

Start the web API using `python -m gutenberg_hoard`; the MCP entrypoint uses stdio and has no web listener. Health and app routes are local: `/api/health`, `/api/publications`, `/api/native/catalog`, `/api/native/session`, and `/api/profiles`.

## Data and compatibility

- `data/gutenberg.db` is a local catalog and history journal; publication source files remain individual `.designcraft` archives under `data/publications/`.
- App code imports the shared `hoard-link` package. It does not vendor a fork or recreate the shared paths, atomic writes, tokens, references, theme, or profile contracts.
- `hoard://gutenberg/publication/<id>` identifies a Gutenberg-owned publication. Other Hoards keep their own source records and files.
- DesignCraft features and file-format compatibility belong to its upstream release. Gutenberg does not claim to implement every advertised editing workflow itself.

## Verification

Run tests from an environment with the shared package and dependencies installed:

```powershell
$env:GUTENBERG_DESIGNCRAFT_CLI = 'D:\path\to\designcraft-cli.exe'
pytest -q
```

The integration suite uses real DesignCraft MCP sessions, creates isolated native publications, edits and undoes them, renders real page PNGs and verifies raster PDF page count. Native PDF export is separately verified against the installed engine, including its warnings and extractable text report. Tests do not start models or use network services. Test records and generated files go under pytest temporary directories.

## Upstream references

- [DesignCraft source and README](https://github.com/storytold/designcraft/blob/main/README.md)
- [DesignCraft releases](https://github.com/storytold/designcraft/releases)
- [DesignCraft MCP documentation](https://github.com/storytold/designcraft/blob/main/docs/mcp.md)
- [DesignCraft control protocol](https://github.com/storytold/designcraft/blob/main/docs/control-protocol.md)
- [HoardLink shared package](https://github.com/Luissalet/HoardLink)

## Licenses

Gutenberg's Hoard is MIT-licensed. DesignCraft remains a separate upstream dependency under its MIT or Apache-2.0 license. Its notices and bundled asset licenses remain with that separate release.
