"""Actual incorporated-engine effects and preservation of synthetic legacy archives."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gutenberg_hoard import config, native, publishing, store
from gutenberg_hoard.engine_sessions import sessions


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GUTENBERG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GUTENBERG_DESIGNCRAFT_CLI", str(tmp_path / "missing-external.exe"))
    monkeypatch.setenv("GUTENBERG_DESIGNCRAFT_GUI", str(tmp_path / "missing-gui.exe"))
    monkeypatch.setenv("HOARD_EVENTS", "0")
    yield
    sessions.shutdown()


def legacy_bytes(data):
    """Synthetic legacy container: same documented model, historical MIME/meta."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "mimetype":
                content = b"application/vnd.designcraft+zip"
            elif name == "meta.json":
                meta = json.loads(content)
                meta.update(format="designcraft", generator="DesignCraft 0.2.1")
                content = json.dumps(meta).encode()
            target.writestr(name, content)
    return output.getvalue()


def add_text(publication_id, text):
    return publishing.native_actions(publication_id, [{"name": "execute", "arguments": {
        "command": "frame.create", "params": {"spread": 0, "rect": [40, 40, 400, 150], "content": "text", "text": text}}}])


def test_catalog_uses_owned_engine_and_both_public_names(tmp_path):
    from gutenberg_hoard.app import app
    from gutenberg_hoard.agent_tools import TOOLS
    assert config.engine_cli().name == "gutenberg-cli.exe"
    assert config.engine_gui().name == "gutenberg.exe"
    assert config.engine_cli().parent == config.ROOT / "native/bin"
    catalog = native.discover()
    assert catalog["engine"] == "Gutenberg engine"
    assert len(catalog["tools"]) == 25 and len(catalog["commands"]) == 432
    tools = {tool.name: tool for tool in TOOLS}
    for suffix in ("catalog", "session", "raw_session", "cli"):
        own = tools["gutenberg_engine_" + suffix]
        old = tools["gutenberg_designcraft_" + suffix]
        assert own.input_model == old.input_model and own.run == old.run
    assert "gutenberg_open_editor" in tools
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/engine/catalog").json()["engine"] == "Gutenberg engine"
        assert client.get("/api/native/catalog").json()["engine"] == "Gutenberg engine"


def test_new_archive_owns_format_and_historical_profile_alias():
    pub = publishing.create_publication("Owned three-page publication", 3, colour_space="CMYK")
    assert Path(pub["path"]).suffix == ".gutenberg"
    with zipfile.ZipFile(pub["path"]) as archive:
        assert archive.read("mimetype") == b"application/vnd.gutenberg+zip"
        assert json.loads(archive.read("meta.json"))["format"] == "gutenberg"
    result = publishing.native_actions(pub["id"], [{"name": "execute", "arguments": {
        "command": "color.settings", "params": {"cmyk": "DesignCraft Generic CMYK (SWOP-like)", "intent": "relative", "bpc": True}}}])
    assert not any(item.get("is_error") for item in result["results"])
    assert publishing.inspect_publication(pub["id"])["pageCount"] == 3


def test_placed_image_bytes_survive_save_reopen_and_native_pdf(tmp_path):
    from PIL import Image
    from pypdf import PdfReader
    image = tmp_path / "synthetic-image.png"
    Image.new("RGB", (48, 24), "#568144").save(image)
    pixels = image.read_bytes()
    pub = publishing.create_publication("Embedded source image", 3)
    publishing.native_actions(pub["id"], [{"name": "place_image", "arguments": {
        "path": str(image), "spread": 1, "x": 50, "y": 50, "width": 120}}])
    source = Path(pub["path"]).read_bytes()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        assets = [archive.read(name) for name in archive.namelist() if name.startswith("assets/")]
        assert pixels in assets
    sessions.shutdown()
    result = publishing.export_pdf(pub["id"], renderer="native")
    assert len(PdfReader(result["path"]).pages) == 3
    assert Path(pub["path"]).read_bytes() == source
    assert image.read_bytes() == pixels


def test_old_id_history_and_original_survive_copy_edit_and_undo(tmp_path):
    source = publishing.create_publication("Legacy source model", 2)
    before = Path(source["path"]).read_bytes()
    edited = add_text(source["id"], "Original legacy story")
    assert edited["publication"]["undo_available"] is True
    current = Path(source["path"]).read_bytes()
    sessions.shutdown()
    legacy = tmp_path / "historical.designcraft"
    original = legacy_bytes(current)
    legacy.write_bytes(original)
    tracked = store.add_publication("Historical archive", legacy, 2, {"working_profile": "DesignCraft Generic CMYK (SWOP-like)"})
    snapshot = tmp_path / "historical-before.designcraft"
    prior_bytes = legacy_bytes(before)
    snapshot.write_bytes(prior_bytes)
    store.add_history(tracked["id"], snapshot)
    item = publishing.owned_publication(tracked["id"])
    assert item["id"] == tracked["id"] and item["profile"] == tracked["profile"]
    assert item["original_native_path"] == str(legacy.resolve())
    assert Path(item["path"]).suffix == ".gutenberg" and Path(item["path"]).read_bytes() == original
    assert legacy.read_bytes() == original
    # Earlier history still compares against identical bytes after copying.
    publishing.undo(item["id"])
    assert Path(item["path"]).read_bytes() == prior_bytes
    add_text(item["id"], "New owned story")
    saved = Path(item["path"]).read_bytes()
    sessions.shutdown()
    assert publishing.inspect_publication(item["id"])["pageCount"] == 2
    publishing.undo(item["id"])
    assert legacy.read_bytes() == original
    assert Path(item["path"]).read_bytes() != saved
    assert store.get_publication(item["id"])["id"] == tracked["id"]


def test_native_open_and_default_save_import_without_overwriting_original(tmp_path):
    source = publishing.create_publication("Standalone import model", 2)
    legacy = tmp_path / "standalone.designcraft"
    original = legacy_bytes(Path(source["path"]).read_bytes())
    legacy.write_bytes(original)
    results = native.run([
        {"name": "open_document", "arguments": {"path": str(legacy)}},
        {"name": "execute", "arguments": {"command": "frame.create", "params": {
            "spread": 0, "rect": [40, 40, 400, 150], "content": "text", "text": "Standalone imported copy"}}},
        {"name": "execute", "arguments": {"command": "file.save", "params": {}}},
    ])
    assert not any(row.get("is_error") for row in results), results
    saved = publishing._text_result(results, "execute")
    own = Path(saved["path"])
    assert own.suffix == ".gutenberg" and own != legacy
    assert hashlib.sha256(legacy.read_bytes()).digest() == hashlib.sha256(original).digest()
    with zipfile.ZipFile(own) as archive:
        assert archive.read("mimetype") == b"application/vnd.gutenberg+zip"
