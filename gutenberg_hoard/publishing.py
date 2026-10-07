from __future__ import annotations

import json
import os
from pathlib import Path
import hashlib
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager

from PIL import Image
from hoard_link.atomic import write_bytes_atomic

from . import native, store


def _emit(event: str, data: dict) -> None:
    try:
        from hoard_link.family import emit
        emit(f"gutenberg.{event}", data)
    except Exception:
        pass

_edit_locks_guard = threading.Lock()
_edit_locks: dict[str, threading.RLock] = {}


def _edit_lock(publication_id: str) -> threading.RLock:
    with _edit_locks_guard:
        return _edit_locks.setdefault(publication_id, threading.RLock())


@contextmanager
def _publication_lock(publication_id: str):
    with _edit_lock(publication_id):
        with store.publication_lock(publication_id):
            yield


def _text_result(action: dict, name: str) -> dict:
    for item in reversed(action):
        if item.get("name") != name:
            continue
        for block in item.get("result", {}).get("content", []):
            if block.get("type") == "text":
                try:
                    return json.loads(block.get("text", "{}"))
                except (TypeError, ValueError):
                    return {}
    return {}


def create_publication(title: str, pages: int, preset: str = "A4", facing_pages: bool = False,
                       margins: float = 36, colour_space: str = "RGB") -> dict:
    if not title.strip() or len(title) > 160:
        raise ValueError("title must contain 1 to 160 characters")
    if not 1 <= pages <= 300:
        raise ValueError("pages must be between 1 and 300")
    if preset not in {"A4", "A5", "Letter", "Legal"}:
        raise ValueError("preset must be A4, A5, Letter, or Legal")
    if colour_space not in {"RGB", "CMYK"}:
        raise ValueError("colour_space must be RGB or CMYK")
    native_path = store.publication_dir() / f"{store.safe_stem(title)}-{uuid.uuid4().hex[:8]}.designcraft"
    try:
        actions = [{"name": "new_document", "arguments": {"title": title, "preset": preset,
                    "pages": pages, "facingPages": facing_pages, "margins": margins}}]
        if colour_space == "CMYK":
            actions.extend([
                {"name": "execute", "arguments": {"command": "color.settings", "params": {
                    "cmyk": "DesignCraft Generic CMYK (SWOP-like)", "intent": "relative", "bpc": True}}},
                {"name": "execute", "arguments": {"command": "swatch.create", "params": {
                    "name": "Gutenberg Print Cyan", "color": {"c": 100, "m": 0, "y": 0, "k": 0}}}},
            ])
        actions.extend([
            {"name": "save_document", "arguments": {"path": str(native_path)}},
            {"name": "inspect_document", "arguments": {}},
        ])
        results = native.run(actions)
        _raise_native_errors(results)
        inspect = _text_result(results, "inspect_document")
        count = inspect.get("pageCount", pages)
        if not native_path.is_file() or count != pages:
            raise RuntimeError(f"DesignCraft did not save the expected {pages}-page document (reported {count}).")
        publication = store.add_publication(title, native_path, pages,
                                            {"preset": preset, "facing_pages": facing_pages, "margins_pt": margins,
                                             "requested_colour_space": colour_space,
                                             "working_profile": "DesignCraft Generic CMYK (SWOP-like)" if colour_space == "CMYK" else "sRGB IEC61966-2.1",
                                             "native_cmyk_swatch": "Gutenberg Print Cyan" if colour_space == "CMYK" else None})
        _emit("publication.created", {"publication_id": publication["id"], "title": title, "pages": pages})
        return publication
    except Exception:
        native_path.unlink(missing_ok=True)
        raise


def inspect_publication(publication_id: str) -> dict:
    with _publication_lock(publication_id):
        pub = store.get_publication(publication_id)
        results = native.run([{"name": "inspect_document", "arguments": {}}],
                             session_id=publication_id, open_path=pub["path"])
        _raise_native_errors(results)
        return _text_result(results, "inspect_document")


def get_story(publication_id: str, story_id: int) -> dict:
    with _publication_lock(publication_id):
        pub = store.get_publication(publication_id)
        results = native.run([{"name": "get_story", "arguments": {"story": story_id}}],
                             session_id=publication_id, open_path=pub["path"])
        _raise_native_errors(results)
        return _text_result(results, "get_story")


def native_actions(publication_id: str, actions: list[dict], session_id: str | None = None) -> dict:
    pub = store.get_publication(publication_id)
    if not Path(pub["path"]).is_file():
        raise FileNotFoundError("Native DesignCraft document is missing")
    _validate_publication_actions(actions, Path(pub["path"]))
    # Open first in the same MCP process, so every native edit remains undoable there
    # and the application stays the owner of the complete .designcraft document model.
    with _publication_lock(publication_id):
        before = Path(pub["path"]).read_bytes()
        active_session = session_id or publication_id
        try:
            results = native.run(actions, session_id=active_session, open_path=pub["path"],
                                 save_path=pub["path"], inspect=True)
        except Exception:
            current = Path(pub["path"]).read_bytes()
            if current != before:
                versions = store.publication_dir() / publication_id / "history"
                versions.mkdir(parents=True, exist_ok=True)
                snapshot = versions / f"{uuid.uuid4().hex}.designcraft"
                write_bytes_atomic(snapshot, before)
                store.add_history(publication_id, snapshot)
            raise
        current = Path(pub["path"]).read_bytes()
        if current != before:
            versions = store.publication_dir() / publication_id / "history"
            versions.mkdir(parents=True, exist_ok=True)
            snapshot = versions / f"{uuid.uuid4().hex}.designcraft"
            write_bytes_atomic(snapshot, before)
            store.add_history(publication_id, snapshot)
        _raise_native_errors(results)
        inspect = _text_result(results, "inspect_document")
        count = int(inspect.get("pageCount", pub["page_count"]) or pub["page_count"])
        store.touch(publication_id, pages=count)
        _emit("publication.edited", {"publication_id": publication_id, "pages": count})
        return {"publication": store.get_publication(publication_id), "results": results,
                "inspection": inspect, "undo_available": current != before,
                "session_id": active_session}


def _validate_publication_actions(actions: list[dict], publication_path: Path) -> None:
    """Keep a tracked session bound to its publication file; raw sessions handle other documents."""
    expected = publication_path.resolve()
    for action in actions:
        name = str(action.get("name", ""))
        args = action.get("arguments", {})
        if not isinstance(args, dict):
            continue
        if name in {"new_document", "open_document", "open_file"}:
            raise ValueError("Tracked publication sessions cannot replace or switch the open document; use a raw session")
        target = args.get("path")
        command = ""
        params = {}
        if name in {"execute", "run_command"}:
            command = str(args.get("command", ""))
            params = args.get("params", {})
            if not isinstance(params, dict):
                params = {}
            target = params.get("path", target)
            if command in {"file.new", "file.open", "file.openBytes"}:
                raise ValueError("Tracked publication sessions cannot replace or switch the open document; use a raw session")
        if name in {"save_document", "save_file"} or command in {"file.saveAs", "file.saveACopy"}:
            if target and Path(str(target)).resolve() != expected:
                raise ValueError("Tracked publication sessions can save only to their original native file; use a raw session")


def undo(publication_id: str) -> dict:
    with _publication_lock(publication_id):
        pub = store.get_publication(publication_id)
        target = Path(pub["path"])
        entry = store.peek_history(publication_id)
        if entry is None:
            raise LookupError("No saved Gutenberg edit is available to undo")
        current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if entry["after_sha256"] and current_hash != entry["after_sha256"]:
            raise RuntimeError("The native document changed outside Gutenberg after the last edit. Reconcile it before undoing.")
        snapshot = store.pop_history(publication_id)
        if snapshot is None or not snapshot.is_file():
            raise LookupError("No saved Gutenberg edit is available to undo")
        # Atomically replace the current file so a reader never observes a partial archive.
        fd, tmp_name = tempfile.mkstemp(prefix=".gutenberg-undo-", suffix=".designcraft", dir=target.parent)
        os.close(fd)
        try:
            shutil.copyfile(snapshot, tmp_name)
            os.replace(tmp_name, target)
            snapshot.unlink(missing_ok=True)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        # Ask DesignCraft for authoritative page count after replaying the native snapshot.
        from .engine_sessions import sessions
        sessions.reset_document(target)
        results = native.run([{"name": "inspect_document", "arguments": {}}], session_id=publication_id,
                         open_path=target, inspect=False)
        _raise_native_errors(results)
        inspect = _text_result(results, "inspect_document")
        store.touch(publication_id, pages=int(inspect.get("pageCount", pub["page_count"]) or pub["page_count"]))
        return {"publication": store.get_publication(publication_id), "inspection": inspect,
                "undo_available": store.has_history(publication_id)}


def render_page(publication_id: str, page: int, scale: float = 1.0) -> dict:
    with _publication_lock(publication_id):
        return _render_page_locked(publication_id, page, scale)


def _render_page_locked(publication_id: str, page: int, scale: float) -> dict:
    pub = store.get_publication(publication_id)
    if page < 0 or page >= pub["page_count"]:
        raise ValueError("page index is outside the publication")
    if not 0.25 <= scale <= 4:
        raise ValueError("scale must be between 0.25 and 4")
    output_dir = store.publication_dir() / pub["id"] / "preview"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"page-{page + 1}.png"
    results = native.run([{"name": "render_page", "arguments": {"page": page, "path": str(output), "scale": scale}}],
                         session_id=publication_id, open_path=pub["path"])
    _raise_native_errors(results)
    if not output.is_file() or output.stat().st_size < 256:
        raise RuntimeError("DesignCraft did not produce a page preview")
    return {"page": page, "path": str(output), "url": f"/api/publications/{publication_id}/pages/{page}/preview",
            "bytes": output.stat().st_size}


def export_pdf(publication_id: str, scale: float = 1.5) -> dict:
    with _publication_lock(publication_id):
        return _export_pdf_locked(publication_id, scale)


def _export_pdf_locked(publication_id: str, scale: float) -> dict:
    pub = store.get_publication(publication_id)
    if not 0.5 <= scale <= 4:
        raise ValueError("scale must be between 0.5 and 4")
    estimated_pixels = 595 * 842 * pub["page_count"] * scale * scale
    if estimated_pixels > 120_000_000:
        max_scale = (120_000_000 / (595 * 842 * pub["page_count"])) ** 0.5
        raise ValueError(f"This export would exceed the 120-megapixel in-memory PDF budget. Use scale {max_scale:.2f} or lower.")
    output_dir = store.publication_dir() / pub["id"] / "pdf-render"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [output_dir / f"page-{index + 1}.png" for index in range(pub["page_count"])]
    actions = [{"name": "render_page", "arguments": {"page": index, "path": str(path), "scale": scale}}
               for index, path in enumerate(paths)]
    _raise_native_errors(native.run(actions, session_id=publication_id, open_path=pub["path"]))
    if not all(path.is_file() and path.stat().st_size > 256 for path in paths):
        raise RuntimeError("Could not render every page; no PDF was published")
    pixel_count = 0
    for path in paths:
        with Image.open(path) as page_image:
            pixel_count += page_image.width * page_image.height
    if pixel_count > 120_000_000:
        raise ValueError(f"Rendered pages total {pixel_count / 1_000_000:.1f} megapixels. Lower the scale to stay under 120 megapixels.")
    pdf_path = store.publication_dir() / f"{Path(pub['path']).stem}-raster.pdf"
    temp_pdf = pdf_path.with_name(pdf_path.stem + f"-{uuid.uuid4().hex}.tmp.pdf")
    images = []
    try:
        for path in paths:
            with Image.open(path) as img:
                images.append(img.convert("RGB"))
        images[0].save(temp_pdf, "PDF", save_all=True, append_images=images[1:], resolution=72 * scale)
    finally:
        for image in images:
            image.close()
    from pypdf import PdfReader
    reader = PdfReader(str(temp_pdf))
    if len(reader.pages) != pub["page_count"]:
        temp_pdf.unlink(missing_ok=True)
        raise RuntimeError(f"PDF verification failed: expected {pub['page_count']} pages, found {len(reader.pages)}")
    os.replace(temp_pdf, pdf_path)
    _emit("publication.exported", {"publication_id": publication_id, "format": "pdf-raster", "pages": len(reader.pages)})
    return {"path": str(pdf_path), "url": f"/api/files/{pdf_path.name}", "pages": len(reader.pages),
            "kind": "raster", "searchable_text": False, "colour_space": "RGB", "resolution_scale": scale,
            "bytes": pdf_path.stat().st_size}


def _raise_native_errors(results: list[dict]) -> None:
    failed = [result for result in results if result.get("is_error")]
    if failed:
        raise RuntimeError(f"DesignCraft MCP {failed[0]['name']} failed: {failed[0].get('result')}")
