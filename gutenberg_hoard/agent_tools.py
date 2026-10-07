"""Shared HoardLink HTTP agent contract for Faustus and sibling apps."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hoard_link import agentkit
from hoard_link.agentkit import Tool, ann, make_agent_router
from hoard_link.family import configure as configure_family
from hoard_link.tokens import read_or_create_token

from . import native, publishing, store
from .config import paths


class CreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    pages: int = Field(default=4, ge=1, le=300)
    preset: str = "A4"
    facing_pages: bool = False
    margins: float = Field(default=36, ge=0, le=200)
    colour_space: str = "RGB"


class PublicationArgs(BaseModel):
    publication_id: str


class EditArgs(PublicationArgs):
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, max_length=100)


class RawSessionArgs(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class PdfArgs(PublicationArgs):
    scale: float = Field(default=1.5, ge=0.5, le=4, description="Raster render scale; ignored by the native renderer.")
    renderer: Literal["native", "raster"] = "raster"


class PageArgs(PublicationArgs):
    page: int = Field(ge=0)
    scale: float = Field(default=1, ge=0.25, le=4)


class LinkArgs(PublicationArgs):
    source_ref: str = Field(min_length=10, max_length=1000)


class StoryArgs(PublicationArgs):
    story_id: int = Field(ge=0)


class ParentArgs(PublicationArgs):
    page: int = Field(ge=0)
    parent: str | None = Field(default=None, max_length=40)


class SwatchArgs(PublicationArgs):
    name: str = Field(min_length=1, max_length=80)
    c: float = Field(ge=0, le=100)
    m: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    k: float = Field(ge=0, le=100)


class NativeCliArgs(BaseModel):
    command: str = Field(min_length=1, max_length=40)
    argv: list[str] = Field(default_factory=list, max_length=200)
    timeout_s: float = Field(default=120, ge=1, le=600)


def _link(args: LinkArgs) -> dict:
    from hoard_link import fam_refs
    from hoard_link.artifacts import parse_ref
    pub = store.get_publication(args.publication_id)
    source = parse_ref(args.source_ref)
    p = paths().ensure()
    configure_family("gutenberg", str(p.data_dir), token_file=str(p.token_path))
    return fam_refs.link(f"hoard://gutenberg/publication/{args.publication_id}", source.uri, "laid_out_from",
                         from_label=pub["title"], to_label=f"{source.kind} {source.id}")


TOOLS = [
    Tool("gutenberg_publications", "List locally catalogued editable publications.", agentkit.Empty,
         ann(read_only=True), lambda _ctx, _a: {"publications": store.list_publications()}),
    Tool("gutenberg_create_publication", "Create an editable native DesignCraft publication.", CreateArgs,
         ann(), lambda _ctx, a: publishing.create_publication(a.title, a.pages, a.preset, a.facing_pages, a.margins, a.colour_space)),
    Tool("gutenberg_designcraft_catalog", "Discover every native DesignCraft MCP schema and engine command.", agentkit.Empty,
         ann(read_only=True), lambda _ctx, _a: native.discover(), capped=False),
    Tool("gutenberg_designcraft_cli", "Run any documented DesignCraft CLI command with literal argv and no shell.", NativeCliArgs,
         ann(), lambda _ctx, a: native.cli_call(a.command, a.argv, a.timeout_s), timeout_s=600, capped=False),
    Tool("gutenberg_designcraft_session", "Dispatch native DesignCraft MCP tools for a publication in a persistent saved session.", EditArgs,
         ann(), lambda _ctx, a: publishing.native_actions(a.publication_id, a.actions, a.session_id), capped=False),
    Tool("gutenberg_inspect_publication", "Read native pages, stories, parent pages, layers and swatches.", PublicationArgs,
         ann(read_only=True), lambda _ctx, a: publishing.inspect_publication(a.publication_id)),
    Tool("gutenberg_get_story", "Read a complete native story by its DesignCraft story ID.", StoryArgs,
         ann(read_only=True), lambda _ctx, a: publishing.get_story(a.publication_id, a.story_id)),
    Tool("gutenberg_assign_parent", "Apply a native DesignCraft parent page to a publication page.", ParentArgs,
         ann(), lambda _ctx, a: publishing.native_actions(a.publication_id, [{"name": "execute", "arguments": {
             "command": "layout.pages.applyParent", "params": {"pages": [a.page], "parent": a.parent}}}])),
    Tool("gutenberg_create_cmyk_swatch", "Create a native CMYK process-color swatch in the DesignCraft document.", SwatchArgs,
         ann(), lambda _ctx, a: publishing.native_actions(a.publication_id, [{"name": "execute", "arguments": {
             "command": "swatch.create", "params": {"name": a.name, "color": {"c": a.c, "m": a.m, "y": a.y, "k": a.k}}}}])),
    Tool("gutenberg_designcraft_raw_session", "Dispatch the complete DesignCraft MCP surface in a stable session_id.", RawSessionArgs,
         ann(), lambda _ctx, a: {"session_id": a.session_id, "results": native.run(a.actions, session_id=a.session_id)}, capped=False),
    Tool("gutenberg_undo", "Restore the last agent edit snapshot if the native document has not changed externally.", PublicationArgs,
         ann(), lambda _ctx, a: publishing.undo(a.publication_id)),
    Tool("gutenberg_render_page", "Render a native DesignCraft page preview PNG.", PageArgs,
         ann(read_only=True), lambda _ctx, a: publishing.render_page(a.publication_id, a.page, a.scale)),
    Tool("gutenberg_export_pdf", "Export a publication as a native DesignCraft PDF or an RGB raster PDF.", PdfArgs,
         ann(), lambda _ctx, a: publishing.export_pdf(a.publication_id, a.scale, a.renderer)),
    Tool("gutenberg_link_source", "Connect a publication to an owned source record through HoardLink.", LinkArgs,
         ann(idempotent=True), lambda _ctx, a: _link(a)),
]


INSTRUCTIONS = ("Gutenberg owns the publication catalog and source links; DesignCraft owns native page layout. "
                "Use gutenberg_designcraft_catalog to discover current engine schemas. Its session tool forwards "
                "the entire native surface. Preserve .designcraft as the editable source. "
                "gutenberg_export_pdf accepts renderer='native' or 'raster'; raster remains the default and accepts scale. "
                "Native receipts report engine warnings and whether any PDF text was extractable; this does not prove "
                "that every story is searchable or establish PDF/X or PDF/UA conformance.")

router = make_agent_router(
    tools_fn=lambda: agentkit.tool_catalog(TOOLS),
    call_fn=lambda name, args: agentkit.call_tool(TOOLS, None, name, args),
    token_fn=lambda: read_or_create_token(paths().token_path),
    instructions=INSTRUCTIONS,
    app_name="gutenberg",
)
