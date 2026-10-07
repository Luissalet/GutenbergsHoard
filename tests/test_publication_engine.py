from __future__ import annotations

import hashlib
import json
import os
import re
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
    assert export["renderer"] == "raster"
    assert export["kind"] == "raster" and export["colour_space"] == "RGB"
    assert export["searchable_text"] is False


def test_native_pdf_export_uses_native_command_and_reports_artifact_warnings(monkeypatch: pytest.MonkeyPatch):
    from pypdf import PdfWriter

    pub = create_two_pages()
    source = Path(pub["path"])
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    def fake_native_run(actions, **kwargs):
        calls.append((actions, kwargs))
        action = actions[0]
        assert action["arguments"]["command"] == "file.exportPdf"
        target = Path(action["arguments"]["params"]["path"])
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with target.open("wb") as stream:
            writer.write(stream)
        receipt = {"path": str(target), "bytes": target.stat().st_size, "pages": 2,
                   "warnings": ["A soft effect was rasterized.", {"font": "Café Sans", "action": "embedded"}]}
        return [{"name": "execute", "is_error": False, "result": {"content": [
            {"type": "text", "text": json.dumps(receipt)}]}}]

    monkeypatch.setattr(publishing.native, "run", fake_native_run)
    result = publishing.export_pdf(pub["id"], renderer="native")

    assert len(calls) == 1
    actions, kwargs = calls[0]
    assert kwargs == {"session_id": pub["id"], "open_path": source}
    assert actions[0]["arguments"]["params"]["tagged"] is True
    assert result["renderer"] == "native" and result["pages"] == 2
    assert result["warnings"] == ["A soft effect was rasterized.", '{"font": "Café Sans", "action": "embedded"}']
    assert result["text_searchability"]["status"] == "no-text-extracted"
    assert result["searchable_text"] is False
    assert Path(result["path"]).name.endswith("-native.pdf")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert not list(Path(result["path"]).parent.glob("*.tmp.pdf"))


@pytest.mark.parametrize("failure", ["engine", "corrupt-pdf", "wrong-pages"])
def test_native_pdf_export_failures_keep_existing_target_and_remove_temp(monkeypatch: pytest.MonkeyPatch, failure: str):
    from pypdf import PdfWriter

    pub = create_two_pages()
    output = store.publication_dir() / f"{Path(pub['path']).stem}-native.pdf"
    old_bytes = b"previous verified PDF remains intact"
    output.write_bytes(old_bytes)

    def fake_native_run(actions, **kwargs):
        target = Path(actions[0]["arguments"]["params"]["path"])
        if failure == "engine":
            raise RuntimeError("injected DesignCraft engine failure")
        if failure == "corrupt-pdf":
            target.write_bytes(b"not a readable PDF" * 20)
        else:
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            with target.open("wb") as stream:
                writer.write(stream)
        return [{"name": "execute", "is_error": False, "result": {"content": [
            {"type": "text", "text": json.dumps({"path": str(target), "pages": 2})}]}}]

    monkeypatch.setattr(publishing.native, "run", fake_native_run)
    with pytest.raises(RuntimeError) as error:
        publishing.export_pdf(pub["id"], renderer="native")

    if failure == "corrupt-pdf":
        assert "Native PDF verification failed" in str(error.value)
    elif failure == "wrong-pages":
        assert "expected 2 pages, found 1" in str(error.value)
    else:
        assert "injected DesignCraft engine failure" in str(error.value)
    assert output.read_bytes() == old_bytes
    assert not list(output.parent.glob(".*.tmp.pdf"))


def test_native_pdf_replace_permission_error_is_structured_and_cleans_temp(monkeypatch: pytest.MonkeyPatch):
    from pypdf import PdfWriter

    pub = create_two_pages()
    output = store.publication_dir() / f"{Path(pub['path']).stem}-native.pdf"
    old_bytes = b"previous verified PDF remains intact"
    output.write_bytes(old_bytes)

    def fake_native_run(actions, **kwargs):
        target = Path(actions[0]["arguments"]["params"]["path"])
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with target.open("wb") as stream:
            writer.write(stream)
        return [{"name": "execute", "is_error": False, "result": {"content": [
            {"type": "text", "text": json.dumps({"path": str(target), "pages": 2})}]}}]

    def deny_replace(source, destination):
        raise PermissionError("destination is open")

    monkeypatch.setattr(publishing.native, "run", fake_native_run)
    monkeypatch.setattr(publishing.os, "replace", deny_replace)
    with pytest.raises(RuntimeError, match="could not replace destination.*open or locked"):
        publishing.export_pdf(pub["id"], renderer="native")
    assert output.read_bytes() == old_bytes
    assert not list(output.parent.glob(".*.tmp.pdf"))


def test_native_pdf_null_warnings_are_empty(monkeypatch: pytest.MonkeyPatch):
    from pypdf import PdfWriter

    pub = create_two_pages()

    def fake_native_run(actions, **kwargs):
        target = Path(actions[0]["arguments"]["params"]["path"])
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with target.open("wb") as stream:
            writer.write(stream)
        return [{"name": "execute", "is_error": False, "result": {"content": [
            {"type": "text", "text": json.dumps({"path": str(target), "pages": 2, "warnings": None})}]}}]

    monkeypatch.setattr(publishing.native, "run", fake_native_run)
    assert publishing.export_pdf(pub["id"], renderer="native")["warnings"] == []


def test_real_native_pdf_preserves_unicode_text_and_vector_path():
    pub = create_two_pages()
    expected_text = "Acci\u00f3n, ping\u00fcino, fa\u00e7ade \u2014 a\u00f1o 2026"
    add_text(pub["id"], expected_text)
    publishing.native_actions(pub["id"], [{"name": "execute", "arguments": {
        "command": "path.create", "params": {"spread": 0, "closed": False, "anchors": [
            {"p": [70, 240], "out": [130, 170]},
            {"p": [250, 240], "in": [190, 310], "out": [310, 170]},
            {"p": [430, 240], "in": [370, 310]},
        ]}}}])

    exported = publishing.export_pdf(pub["id"], renderer="native")
    from pypdf import PdfReader
    reader = PdfReader(exported["path"])
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    vector_ops = reader.pages[0].get_contents().get_data()

    assert expected_text.replace(" ", "") in re.sub(r"\s+", "", text)
    assert re.search(rb"(?<!\S)c(?:\s|$)", vector_ops), "expected cubic Bezier path operators in native PDF"
    assert exported["searchable_text"] is True
    assert exported["text_searchability"]["status"] == "text-extracted"
    assert exported["warnings"] == []


def test_named_pdf_export_contract_keeps_raster_compatibility_default():
    from gutenberg_hoard.agent_tools import PdfArgs
    from gutenberg_hoard.app import PdfExport
    from gutenberg_hoard.mcp_server import gutenberg_export_pdf

    assert PdfArgs.model_fields["renderer"].default == "raster"
    assert PdfExport.model_fields["renderer"].default == "raster"
    assert set(PdfArgs.model_fields["renderer"].annotation.__args__) == {"native", "raster"}
    assert "renderer" in __import__("inspect").signature(gutenberg_export_pdf).parameters
    assert __import__("inspect").signature(gutenberg_export_pdf).parameters["renderer"].default == "raster"


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
