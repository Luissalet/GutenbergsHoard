"""Persistent DesignCraft MCP sessions, isolated on a dedicated event-loop thread."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
import threading
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .native import _environment, executable, serial


class _OpenSession:
    def __init__(self, session_id: str, path: Path | None, queue: asyncio.Queue, task: asyncio.Task):
        self.session_id, self.path, self.queue, self.task = session_id, path, queue, task
        self.disk_hash = _sha(path)


class NativeSessions:
    def __init__(self) -> None:
        self._thread_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, _OpenSession] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if self._loop and self._thread and self._thread.is_alive():
                return self._loop
            ready = threading.Event()

            def worker() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                loop.run_forever()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

            self._thread = threading.Thread(target=worker, name="gutenberg-designcraft-mcp", daemon=True)
            self._thread.start()
            if not ready.wait(5) or self._loop is None:
                raise RuntimeError("Could not start the DesignCraft MCP session thread")
            return self._loop

    def execute(self, actions: list[dict[str, Any]], *, session_id: str | None = None,
                open_path: str | Path | None = None, save_path: str | Path | None = None,
                inspect: bool = False) -> list[dict[str, Any]]:
        if session_id is None:
            loop = self._ensure_loop()
            cleanup_complete = threading.Event()

            async def one_shot() -> list[dict[str, Any]]:
                try:
                    return await self._one_shot(actions)
                finally:
                    cleanup_complete.set()

            future = asyncio.run_coroutine_threadsafe(one_shot(), loop)
            try:
                return future.result(timeout=300)
            except concurrent.futures.TimeoutError as exc:
                if future.done():
                    raise
                future.cancel()
                if not cleanup_complete.wait(timeout=15):
                    raise TimeoutError("DesignCraft MCP one-shot timed out; engine cleanup is still pending") from exc
                raise TimeoutError("DesignCraft MCP one-shot exceeded five minutes") from exc
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
            raise ValueError("session_id must be 1–100 letters, digits, underscore, or hyphen")
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._execute(session_id, actions, Path(open_path) if open_path else None,
                          Path(save_path) if save_path else None, inspect), loop)
        try:
            return future.result(timeout=300)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("DesignCraft MCP session exceeded five minutes") from exc

    async def _one_shot(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        params = StdioServerParameters(command=str(executable()), args=["mcp"], env=_environment())
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                return await self._actions(client, actions)

    async def _start_session(self, session_id: str, path: Path | None) -> _OpenSession:
        queue: asyncio.Queue = asyncio.Queue()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()

        async def worker() -> None:
            params = StdioServerParameters(command=str(executable()), args=["mcp"], env=_environment())
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        if path:
                            opened = await client.call_tool("open_document", {"path": str(path)})
                            if opened.isError:
                                raise RuntimeError("DesignCraft could not open the publication: " + str(serial(opened)))
                        if not ready.done():
                            ready.set_result(True)
                        while True:
                            item = await queue.get()
                            if item is None:
                                return
                            actions, save_path, inspect, answer = item
                            try:
                                result = await self._actions(client, actions)
                                if save_path:
                                    saved = await client.call_tool("save_document", {"path": str(save_path)})
                                    result.append({"kind": "tool", "name": "save_document", "is_error": bool(saved.isError), "result": serial(saved)})
                                if inspect:
                                    inspected = await client.call_tool("inspect_document", {})
                                    result.append({"kind": "tool", "name": "inspect_document", "is_error": bool(inspected.isError), "result": serial(inspected)})
                                answer.set_result(result)
                            except BaseException as exc:
                                if not answer.done():
                                    answer.set_exception(exc)
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                raise

        task = asyncio.create_task(worker(), name=f"designcraft-{session_id}")
        try:
            await ready
        except BaseException:
            await asyncio.gather(task, return_exceptions=True)
            raise
        return _OpenSession(session_id, path, queue, task)

    async def _execute(self, session_id: str, actions: list[dict[str, Any]], path: Path | None,
                       save_path: Path | None, inspect: bool) -> list[dict[str, Any]]:
        current = self._sessions.get(session_id)
        path = path or _document_path(actions) or (current.path if current else None)
        if current and current.task.done():
            await self._close_one(session_id)
            current = None
        if current and (current.path != path or (path and _sha(path) != current.disk_hash)):
            await self._close_one(session_id)
            current = None
        if current is None:
            current = await self._start_session(session_id, path)
            self._sessions[session_id] = current
        answer: asyncio.Future = asyncio.get_running_loop().create_future()
        await current.queue.put((actions, Path(save_path) if save_path else None, inspect, answer))
        result = await answer
        saved_path = Path(save_path) if save_path else _save_path(actions)
        if saved_path:
            current.path = saved_path
        if current.path:
            current.disk_hash = _sha(current.path)
        return result

    async def _actions(self, client: ClientSession, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for action in actions:
            kind = action.get("kind", "tool")
            name = str(action.get("name", ""))
            arguments = action.get("arguments", {})
            if not name or not isinstance(arguments, dict):
                raise ValueError("Each action needs a name and an arguments object")
            if kind == "tool":
                result = await client.call_tool(name, arguments)
                results.append({"kind": kind, "name": name, "is_error": bool(result.isError), "result": serial(result)})
            elif kind == "prompt":
                results.append({"kind": kind, "name": name, "result": serial(await client.get_prompt(name, arguments))})
            elif kind == "resource":
                uri = str(arguments.get("uri", name))
                results.append({"kind": kind, "name": uri, "result": serial(await client.read_resource(uri))})
            else:
                raise ValueError("kind must be tool, prompt, or resource")
        return results

    async def _close_one(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            await session.queue.put(None)
            await session.task

    async def _close_all(self) -> None:
        for session_id in list(self._sessions):
            await self._close_one(session_id)

    def reset(self, session_id: str) -> None:
        loop = self._loop
        if loop and self._thread and self._thread.is_alive():
            asyncio.run_coroutine_threadsafe(self._close_one(session_id), loop).result(timeout=15)

    def reset_document(self, path: str | Path) -> None:
        loop = self._loop
        target = Path(path)
        if loop and self._thread and self._thread.is_alive():
            async def close_matching() -> None:
                for session_id, session in list(self._sessions.items()):
                    if session.path == target:
                        await self._close_one(session_id)
            asyncio.run_coroutine_threadsafe(close_matching(), loop).result(timeout=30)

    def shutdown(self) -> None:
        loop, thread = self._loop, self._thread
        if not loop or not thread or not thread.is_alive():
            return
        asyncio.run_coroutine_threadsafe(self._close_all(), loop).result(timeout=30)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        self._loop = None
        self._thread = None


def _sha(path: Path | None) -> str:
    if path is None:
        return ""
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document_path(actions: list[dict[str, Any]]) -> Path | None:
    for action in actions:
        name = str(action.get("name", ""))
        args = action.get("arguments", {})
        if not isinstance(args, dict):
            continue
        if name in {"open_document", "open_file"} and args.get("path"):
            return Path(str(args["path"]))
        if name in {"execute", "run_command"}:
            command = str(args.get("command", ""))
            params = args.get("params", {})
            if command in {"file.open", "file.openBytes"} and isinstance(params, dict) and params.get("path"):
                return Path(str(params["path"]))
    return None


def _save_path(actions: list[dict[str, Any]]) -> Path | None:
    for action in actions:
        name = str(action.get("name", ""))
        args = action.get("arguments", {})
        if not isinstance(args, dict):
            continue
        if name in {"save_document", "save_file"} and args.get("path"):
            return Path(str(args["path"]))
        if name in {"execute", "run_command"}:
            command = str(args.get("command", ""))
            params = args.get("params", {})
            if command in {"file.save", "file.saveAs", "file.saveACopy"} and isinstance(params, dict) and params.get("path"):
                return Path(str(params["path"]))
    return None


sessions = NativeSessions()
