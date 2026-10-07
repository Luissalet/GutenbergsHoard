"""MCP entrypoint: app tools plus complete discover/dispatch access to native DesignCraft MCP."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import native, publishing, store

mcp = FastMCP("Gutenberg's Hoard")


@mcp.tool()
def gutenberg_publications() -> dict:
    """List paginated editorial documents tracked by Gutenberg."""
    return {"publications": store.list_publications()}


@mcp.tool()
def gutenberg_create_publication(title: str, pages: int = 4, preset: str = "A4", facing_pages: bool = False,
                                 margins: float = 36, colour_space: str = "RGB") -> dict:
    """Create and save an editable native DesignCraft publication."""
    return publishing.create_publication(title, pages, preset, facing_pages, margins, colour_space)


@mcp.tool()
def gutenberg_designcraft_catalog() -> dict:
    """Discover every currently available DesignCraft MCP tool, prompt, resource, and template."""
    return native.discover()


@mcp.tool()
def gutenberg_designcraft_session(publication_id: str, actions: list[dict], session_id: str = "") -> dict:
    """Open a native publication, execute arbitrary DesignCraft MCP tools in sequence, then save and inspect it.

    `actions` is an array of {name, arguments, kind?}. It dispatches tools, prompts, and resources without an
    allow-list. Consult gutenberg_designcraft_catalog for the installed engine's live schemas. DesignCraft undo
    operates inside an MCP process; edits are saved back to the original native document.
    """
    return publishing.native_actions(publication_id, actions, session_id or None)


@mcp.tool()
def gutenberg_export_pdf(publication_id: str, scale: float = 1.5) -> dict:
    """Render all native pages and assemble a verified multipage RGB raster PDF."""
    return publishing.export_pdf(publication_id, scale)


@mcp.tool()
def gutenberg_undo(publication_id: str) -> dict:
    """Restore the previous saved native file snapshot from a Gutenberg MCP edit."""
    return publishing.undo(publication_id)


@mcp.tool()
def gutenberg_inspect_publication(publication_id: str) -> dict:
    """Read live native pages, stories, parents, layers and swatches without adding a saved edit."""
    return publishing.inspect_publication(publication_id)


@mcp.tool()
def gutenberg_get_story(publication_id: str, story_id: int) -> dict:
    """Read the full native text of an editable DesignCraft story."""
    return publishing.get_story(publication_id, story_id)


@mcp.tool()
def gutenberg_assign_parent(publication_id: str, page: int, parent: str = "") -> dict:
    """Apply a native DesignCraft parent-page prefix to a page; blank removes it."""
    return publishing.native_actions(publication_id, [{"name": "execute", "arguments": {
        "command": "layout.pages.applyParent", "params": {"pages": [page], "parent": parent or None}}}])


@mcp.tool()
def gutenberg_create_cmyk_swatch(publication_id: str, name: str, c: float, m: float, y: float, k: float) -> dict:
    """Create and save a native DesignCraft process color in CMYK percentages."""
    return publishing.native_actions(publication_id, [{"name": "execute", "arguments": {
        "command": "swatch.create", "params": {"name": name, "color": {"c": c, "m": m, "y": y, "k": k}}}}])


@mcp.tool()
def gutenberg_link_source(publication_id: str, source_ref: str) -> dict:
    """Link this publication to an existing source record using shared HoardLink references."""
    from hoard_link.artifacts import parse_ref
    from hoard_link import fam_refs
    pub = store.get_publication(publication_id)
    source = parse_ref(source_ref)
    return fam_refs.link(f"hoard://gutenberg/publication/{publication_id}", source.uri, "laid_out_from",
                         from_label=pub["title"], to_label=f"{source.kind} {source.id}")


@mcp.tool()
def gutenberg_designcraft_raw_session(session_id: str, actions: list[dict]) -> dict:
    """Call DesignCraft MCP directly, preserving its full surface for operations outside tracked publications."""
    return {"session_id": session_id, "results": native.run(actions, session_id=session_id)}


@mcp.tool()
def gutenberg_designcraft_cli(command: str, argv: list[str] | None = None, timeout_s: float = 120) -> dict:
    """Run the installed DesignCraft CLI's complete documented verbs (run, script, commands, describe, app, mcp, perf, bench, links)."""
    return native.cli_call(command, argv or [], timeout_s)


def main() -> None:
    from .config import paths
    from hoard_link.family import configure
    from hoard_link.tokens import read_or_create_token
    app_paths = paths().ensure()
    read_or_create_token(app_paths.token_path)
    configure("gutenberg", str(app_paths.data_dir), token_file=str(app_paths.token_path))
    try:
        mcp.run(transport="stdio")
    finally:
        from .engine_sessions import sessions
        sessions.shutdown()


if __name__ == "__main__":
    main()
