"""Lossless local bridge to DesignCraft's complete native MCP catalogue."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from .config import designcraft_cli, paths


def executable() -> Path:
    path = designcraft_cli()
    if path is None:
        raise RuntimeError("Set GUTENBERG_DESIGNCRAFT_CLI to the verified local DesignCraft CLI executable.")
    return path


def _environment() -> dict[str, str]:
    root = paths().data_dir / "native" / "designcraft-runtime"
    appdata, localappdata = root / "appdata", root / "localappdata"
    appdata.mkdir(parents=True, exist_ok=True)
    localappdata.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"APPDATA": str(appdata), "LOCALAPPDATA": str(localappdata)})
    return env


async def session(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exe = executable()
    params = StdioServerParameters(command=str(exe), args=["mcp"], env=_environment())
    out = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            for action in actions:
                kind = action.get("kind", "tool")
                name = str(action.get("name", ""))
                arguments = action.get("arguments", {})
                if not name or not isinstance(arguments, dict):
                    raise ValueError("Each action needs a name and an arguments object.")
                if kind == "tool":
                    result = await client.call_tool(name, arguments)
                    out.append({"kind": kind, "name": name, "is_error": bool(result.isError), "result": serial(result)})
                elif kind == "prompt":
                    out.append({"kind": kind, "name": name, "result": serial(await client.get_prompt(name, arguments))})
                elif kind == "resource":
                    uri = str(arguments.get("uri", name))
                    out.append({"kind": kind, "name": uri, "result": serial(await client.read_resource(uri))})
                else:
                    raise ValueError("kind must be tool, prompt, or resource")
    return out


async def catalog() -> dict[str, Any]:
    exe = executable()
    params = StdioServerParameters(command=str(exe), args=["mcp"], env=_environment())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result: dict[str, Any] = {"executable": str(exe), "tools": serial((await client.list_tools()).tools),
                                      "commands": command_catalog(), "cli": cli_help()}
            for method, key, attr in ((client.list_prompts, "prompts", "prompts"),
                                      (client.list_resources, "resources", "resources"),
                                      (client.list_resource_templates, "resource_templates", "resourceTemplates")):
                try:
                    result[key] = serial(getattr(await method(), attr, []) or [])
                except McpError as exc:
                    if exc.error.code != -32601:
                        raise
                    result[key] = []
            return result


def run(actions: list[dict[str, Any]], *, session_id: str | None = None,
        open_path: str | Path | None = None, save_path: str | Path | None = None,
        inspect: bool = False) -> list[dict[str, Any]]:
    from .engine_sessions import sessions
    return sessions.execute(actions, session_id=session_id, open_path=open_path,
                            save_path=save_path, inspect=inspect)


def discover() -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(catalog())
    # MCP tool handlers run inside an active event loop, while this sync API
    # exposes a complete async stdio discovery. Own a separate worker loop
    # instead of trying to nest asyncio.run in the server's loop.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="gutenberg-designcraft-discovery") as pool:
        return pool.submit(asyncio.run, catalog()).result(timeout=180)


def command_catalog() -> list[dict[str, Any]]:
    """Return the engine's unfiltered CLI command registry (not a curated subset)."""
    proc = subprocess.run([str(executable()), "commands"], capture_output=True, text=True, timeout=30,
                          env=_environment(), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"DesignCraft command catalogue failed: {proc.stderr[-1200:]}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError("DesignCraft returned an invalid command catalogue") from exc
    if not isinstance(data, list):
        raise RuntimeError("DesignCraft command catalogue was not an array")
    return data


def cli_help() -> dict[str, Any]:
    proc = subprocess.run([str(executable()), "--help"], capture_output=True, text=True, timeout=20,
                          env=_environment(), check=False)
    # This release writes its usage/help text to stderr and returns 1 for --help.
    # Treat that as a successful discovery only when the expected CLI usage is present.
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    if proc.returncode != 0 and "designcraft-cli run" not in output:
        raise RuntimeError(f"DesignCraft CLI help failed: {output[-1200:]}")
    lines = output.splitlines()
    commands = []
    for line in lines:
        line = line.strip()
        if line.startswith("usage: designcraft-cli "):
            rest = line[len("usage: designcraft-cli "):]
        elif line.startswith("designcraft-cli "):
            rest = line[len("designcraft-cli "):]
        else:
            continue
        command = rest.split(None, 1)[0]
        commands.append({"command": command, "usage": line})
    if not commands:
        raise RuntimeError("DesignCraft returned no CLI commands in its help output")
    return {"executable": str(executable()), "commands": commands, "help": output}


def cli_call(command: str, argv: list[str], timeout_s: float = 120) -> dict[str, Any]:
    """Run one complete documented DesignCraft CLI command without a shell."""
    info = cli_help()
    allowed = {item["command"] for item in info["commands"]} | {"--version", "--help"}
    if command not in allowed:
        raise ValueError(f"Unknown DesignCraft CLI command {command!r}; discover the installed CLI help first.")
    if len(argv) > 200 or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise ValueError("argv must contain at most 200 strings without NUL characters")
    if not 1 <= float(timeout_s) <= 600:
        raise ValueError("timeout_s must be between 1 and 600 seconds")
    runtime = paths().ensure().data_dir / "native" / "cli-workspace"
    runtime.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(executable()), command, *argv], cwd=str(runtime), capture_output=True,
                          timeout=timeout_s, env=_environment(), check=False)
    return {"command": command, "argv": argv, "returncode": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", "replace")[:2_000_000],
            "stderr": proc.stderr.decode("utf-8", "replace")[:2_000_000],
            "stdout_truncated": len(proc.stdout) > 2_000_000, "stderr_truncated": len(proc.stderr) > 2_000_000}


def serial(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [serial(x) for x in value]
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return serial(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return serial(vars(value))
    return str(value)
