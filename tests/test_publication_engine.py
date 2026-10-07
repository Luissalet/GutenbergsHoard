from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gutenberg_hoard import native, publishing, store
from gutenberg_hoard.config import designcraft_cli
from gutenberg_hoard.engine_sessions import sessions


CLI = str(designcraft_cli() or "")
pytestmark = pytest.mark.skipif(not CLI or not Path(CLI).is_file(), reason="Set GUTENBERG_DESIGNCRAFT_CLI to run release integration tests")


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GUTENBERG_DATA_DIR", str(tmp_path / "gutenberg-data"))
    monkeypatch.setenv("GUTENBERG_DESIGNCRAFT_CLI", CLI)
    monkeypatch.setenv("HOARD_EVENTS", "0")
    yield
    sessions.shutdown()


def create_two_pages() -> dict:
    return publishing.create_publication("Field Journal QA", 2, "A4", False, 36, "RGB")


def add_text(publication_id: str, text: str) -> dict:
    return publishing.native_actions(publication_id, [{
        "name": "execute", "arguments": {"command": "frame.create", "params": {
            "spread": 1, "rect": [54, 60, 540, 180], "content": "text", "text": text}}
    }])


def test_real_native_session_survives_calls_and_undo_replays_saved_file():
    pub = create_two_pages()
    path = Path(pub["path"])
    original = path.read_bytes()
    first = add_text(pub["id"], "First editorial passage")
    first_bytes = path.read_bytes()
    second = add_text(pub["id"], "Second editorial passage")
    assert first["session_id"] == second["session_id"] == pub["id"]
    assert first_bytes != original and path.read_bytes() != first_bytes
    sessions.shutdown()  # simulates a Gutenberg restart; the native session closes cleanly
    assert store.get_publication(pub["id"])["path"] == str(path.resolve())
    undone = publishing.undo(pub["id"])
    assert path.read_bytes() == first_bytes
    assert undone["publication"]["page_count"] == 2
    assert store.has_history(pub["id"])
    publishing.undo(pub["id"])
    assert path.read_bytes() == original


def test_distinct_mcp_sessions_reopen_after_another_session_saves():
    pub = create_two_pages()
    first = {"name": "execute", "arguments": {"command": "frame.create", "params": {
        "spread": 1, "rect": [54, 60, 540, 180], "content": "text", "text": "First session passage"}}}
    publishing.native_actions(pub["id"], [first], session_id="editor_session_one")
    after_first = Path(pub["path"]).read_bytes()
    second = {"name": "execute", "arguments": {"command": "frame.create", "params": {
        "spread": 1, "rect": [60, 200, 540, 320], "content": "text", "text": "Independent MCP passage"}}}
    publishing.native_actions(pub["id"], [second], session_id="editor_session_two")
    assert Path(pub["path"]).read_bytes() != after_first
    # The first engine has stale state on disk; it must be closed and reopened before its next call.
    result = publishing.native_actions(pub["id"], [
        {"name": "inspect_document", "arguments": {}}
    ], session_id="editor_session_one")
    story_text = json.dumps(result["inspection"], ensure_ascii=False)
    assert "Independent MCP passage" in story_text


def test_native_story_parent_and_cmyk_workflow_are_editable():
    pub = publishing.create_publication("Print Feature QA", 2, colour_space="CMYK")
    assert pub["profile"]["working_profile"] == "DesignCraft Generic CMYK (SWOP-like)"
    assert pub["profile"]["native_cmyk_swatch"] in publishing.inspect_publication(pub["id"])["swatches"]
    frame = {"name": "execute", "arguments": {"command": "frame.create", "params": {
        "spread": 0, "rect": [50, 50, 520, 150], "content": "text", "text": "Original story words"}}}
    edited = publishing.native_actions(pub["id"], [frame])
    story_id = edited["inspection"]["stories"][0]["id"]
    assert publishing.get_story(pub["id"], story_id)["text"] == "Original story words"
    parent = {"name": "execute", "arguments": {"command": "layout.parents.new", "params": {
        "prefix": "B", "name": "Editorial Master"}}}
    parent_result = publishing.native_actions(pub["id"], [parent])
    assert any(item["label"] == "B-Editorial Master" for item in parent_result["inspection"]["parents"])
    assignment = {"name": "execute", "arguments": {"command": "layout.pages.applyParent", "params": {
        "pages": [1], "parent": "B"}}}
    assert publishing.native_actions(pub["id"], [assignment])["inspection"]["spreads"][1]["pages"][0]["parent"] == "B-Editorial Master"
    publishing.native_actions(pub["id"], [{"name": "set_story_text", "arguments": {
        "story": story_id, "text": "Revised story words"}}])
    assert publishing.get_story(pub["id"], story_id)["text"] == "Revised story words"
    publishing.undo(pub["id"])
    assert publishing.get_story(pub["id"], story_id)["text"] == "Original story words"


def test_installed_cli_verbs_dispatch_without_a_shell():
    help_doc = native.cli_help()
    commands = {item["command"] for item in help_doc["commands"]}
    assert {"run", "commands", "describe", "script", "app", "mcp", "perf", "bench", "links"} <= commands
    result = native.cli_call("--version", [])
    assert result["returncode"] == 0
    assert "designcraft-cli 0.2.1" in result["stdout"]


def test_parallel_edits_to_one_publication_are_serialized():
    pub = create_two_pages()
    def edit(text: str, y: int):
        return publishing.native_actions(pub["id"], [{"name": "execute", "arguments": {
            "command": "frame.create", "params": {"spread": 0, "rect": [50, y, 520, y + 80],
            "content": "text", "text": text}}}], session_id=f"parallel_{y}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda args: edit(*args), [("Parallel one", 50), ("Parallel two", 160)]))
    stories = publishing.inspect_publication(pub["id"])["stories"]
    assert len(stories) == 2
    assert {publishing.get_story(pub["id"], story["id"])["text"] for story in stories} == {"Parallel one", "Parallel two"}


def test_real_two_page_preview_and_verified_raster_pdf():
    pub = create_two_pages()
    first = publishing.render_page(pub["id"], 0, 0.75)
    second = publishing.render_page(pub["id"], 1, 0.75)
    assert Path(first["path"]).read_bytes()[:8].startswith(b"\x89PNG")
    assert Path(second["path"]).stat().st_size > 1000
    export = publishing.export_pdf(pub["id"], 1.0)
    from pypdf import PdfReader
    reader = PdfReader(export["path"])
    assert len(reader.pages) == 2
    assert all(not page.extract_text() for page in reader.pages)
    assert export["kind"] == "raster" and export["colour_space"] == "RGB"
    assert export["searchable_text"] is False


def test_native_catalogue_is_live_and_unfiltered():
    result = native.discover()
    names = {tool["name"] for tool in result["tools"]}
    commands = result["commands"]
    assert len(names) >= 25
    assert {"execute", "batch", "inspect_document", "get_story"} <= names
    assert len(commands) >= 25
    assert {"file.new", "file.open", "file.save"} <= {command["id"] for command in commands}


def test_external_file_edit_is_not_overwritten_by_undo():
    pub = create_two_pages()
    add_text(pub["id"], "Agent edit")
    path = Path(pub["path"])
    external = path.read_bytes() + b"external-change-marker"
    path.write_bytes(external)
    with pytest.raises(RuntimeError, match="changed outside Gutenberg"):
        publishing.undo(pub["id"])
    assert path.read_bytes() == external
    assert store.has_history(pub["id"])


def test_tracked_session_cannot_switch_or_save_over_another_document(tmp_path: Path):
    pub = create_two_pages()
    original = Path(pub["path"]).read_bytes()
    other = tmp_path / "someone-elses-file.designcraft"
    for action in (
        {"name": "open_document", "arguments": {"path": str(other)}},
        {"name": "execute", "arguments": {"command": "file.open", "params": {"path": str(other)}}},
        {"name": "save_document", "arguments": {"path": str(other)}},
        {"name": "execute", "arguments": {"command": "file.saveAs", "params": {"path": str(other)}}},
    ):
        with pytest.raises(ValueError, match="raw session"):
            publishing.native_actions(pub["id"], [action])
    assert Path(pub["path"]).read_bytes() == original
    assert not other.exists()


def test_http_agent_contract_uses_stable_token_and_shared_schemas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient
    from gutenberg_hoard.app import app
    from hoard_link.tokens import read_or_create_token

    data = tmp_path / "agent-data"
    monkeypatch.setenv("GUTENBERG_DATA_DIR", str(data))
    monkeypatch.setenv("GUTENBERG_DESIGNCRAFT_CLI", CLI)
    with TestClient(app,base_url='http://127.0.0.1') as client:
        catalogue = client.get("/api/agent/tools")
        assert catalogue.status_code == 200
        tools = {item["name"]: item for item in catalogue.json()["tools"]}
        assert {"gutenberg_designcraft_catalog", "gutenberg_designcraft_session", "gutenberg_export_pdf"} <= tools.keys()
        token = read_or_create_token(data / "mcp-token")
        denied = client.post("/api/agent/call", json={"name": "gutenberg_publications", "arguments": {}})
        assert denied.status_code == 401
        allowed = client.post("/api/agent/call", headers={"Authorization": f"Bearer {token}"},
                              json={"name": "gutenberg_publications", "arguments": {}})
        assert allowed.status_code == 200
