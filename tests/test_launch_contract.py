from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from fastapi.testclient import TestClient

from gutenberg_hoard import config
from gutenberg_hoard.app import app as api


ROOT = Path(__file__).resolve().parents[1]


def test_port_zero_is_preserved_and_default_is_5218(monkeypatch):
    monkeypatch.delenv("GUTENBERG_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert config.port() == 5218
    monkeypatch.setenv("GUTENBERG_PORT", "0")
    assert config.port() == 0


def test_hub_registry_resolves_launchable_app_with_own_icon():
    from hoard_link.hub.registry import read_manifest

    app = read_manifest(ROOT / "faustus-plugin.json")
    assert app is not None and app.launchable, app.launch_reason if app else "invalid manifest"
    assert app.url == "http://127.0.0.1:5218"
    assert Path(app.launch.executable).resolve() == Path(sys.executable).resolve()
    assert app.launch.cwd == str(ROOT)
    assert app.launch.env["GUTENBERG_PORT"] == "5218"
    assert app.launch.env["GUTENBERG_PORT_STRICT"] == "1"
    assert app.token_file == str((ROOT / "data" / "mcp-token").resolve())
    assert app.agent_contract is True
    icon = Path(app.icon_path)
    assert icon.parent.resolve() == ROOT.resolve()
    assert icon.name in {"app-icon.svg", "app-icon.png"}
    icon_bytes = icon.read_bytes()
    if icon.suffix.lower() == ".png":
        assert icon_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    else:
        assert b"<svg" in icon_bytes[:1024]


def test_shared_http_agent_contract_uses_same_gutenberg_handlers(monkeypatch, tmp_path):
    data = tmp_path / "http-data"
    monkeypatch.setenv("GUTENBERG_DATA_DIR", str(data))
    monkeypatch.delenv("GUTENBERG_DESIGNCRAFT_CLI", raising=False)
    with TestClient(api,base_url='http://127.0.0.1') as client:
        catalogue = client.get("/api/agent/tools")
        assert catalogue.status_code == 200
        names = {tool["name"] for tool in catalogue.json()["tools"]}
        assert {"gutenberg_publications", "gutenberg_designcraft_catalog",
                "gutenberg_designcraft_session"} <= names
        token = (data / "mcp-token").read_text(encoding="utf-8").strip()
        result = client.post("/api/agent/call", headers={"Authorization": f"Bearer {token}"},
                             json={"name": "gutenberg_publications", "arguments": {}})
        assert result.status_code == 200
        assert result.json() == {"publications": []}


def test_mcp_stdio_initializes_and_lists_tools_in_isolated_data(tmp_path):
    data = tmp_path / "mcp-data"
    env = dict(os.environ)
    env.pop("GUTENBERG_DESIGNCRAFT_CLI", None)
    env.update({"GUTENBERG_DATA_DIR": str(data), "HOARD_EVENTS": "0"})
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "gutenberg_hoard.mcp_server"],
                                   env=env, cwd=str(ROOT))

    async def verify():
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                initialized = await client.initialize()
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert initialized.serverInfo.name == "Gutenberg's Hoard"
                assert {"gutenberg_publications", "gutenberg_designcraft_catalog",
                        "gutenberg_designcraft_session", "gutenberg_export_pdf",
                        "gutenberg_designcraft_cli"} <= names
                export_tool = next(tool for tool in tools.tools if tool.name == "gutenberg_export_pdf")
                assert {"native", "raster"} <= set(export_tool.inputSchema["properties"]["renderer"]["enum"])
                result = await client.call_tool("gutenberg_publications", {})
                assert not result.isError
                payload = json.loads(result.content[0].text)
                assert payload == {"publications": []}
                catalog_result = await client.call_tool("gutenberg_designcraft_catalog", {})
                assert not catalog_result.isError
                catalog = json.loads(catalog_result.content[0].text)
                assert len(catalog["tools"]) >= 25 and len(catalog["commands"]) >= 25

                async def call(name: str, arguments: dict) -> dict:
                    response = await client.call_tool(name, arguments)
                    assert not response.isError, response
                    if response.structuredContent is not None:
                        return response.structuredContent
                    return json.loads(response.content[0].text)

                publication = await call("gutenberg_create_publication", {
                    "title": "Stdio native PDF regression", "pages": 2, "preset": "A4"})
                publication_id = publication["id"]
                await call("gutenberg_designcraft_session", {"publication_id": publication_id, "actions": [{
                    "name": "execute", "arguments": {"command": "frame.create", "params": {
                        "spread": 0, "rect": [54, 60, 540, 160], "content": "text",
                        "text": "Native PDF created through the stdio tool."}}}]})
                exported = await call("gutenberg_export_pdf", {
                    "publication_id": publication_id, "renderer": "native"})
                assert exported["renderer"] == "native" and exported["pages"] == 2
                assert Path(exported["path"]).is_file()
                assert isinstance(exported["warnings"], list)
        assert (data / "mcp-token").is_file()

    asyncio.run(verify())
