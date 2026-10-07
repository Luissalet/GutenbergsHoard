from __future__ import annotations

import json
import mimetypes
import os
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import hoard_link
from . import native, publishing, store
from .config import ROOT, designcraft_cli, designcraft_gui, paths
from hoard_link.family import configure as configure_family, health_block as family_health_block
from hoard_link._hubclient import fetch, hub_url

@asynccontextmanager
async def lifespan(_app):
    from hoard_link.tokens import read_or_create_token
    p = paths().ensure()
    read_or_create_token(p.token_path)
    configure_family("gutenberg", str(p.data_dir), token_file=str(p.token_path))
    yield
    from .engine_sessions import sessions
    sessions.shutdown()


app = FastAPI(title="Gutenberg's Hoard", version="0.1.0", lifespan=lifespan)
from hoard_link.guard import install_guard
from .config import port as configured_port
install_guard(app,port_getter=configured_port,allowed_env='GUTENBERG_ALLOWED_HOSTS')
app.mount("/static/hoard-link", StaticFiles(directory=Path(hoard_link.__file__).parent / "ui"), name="hoard-link-ui")
app.mount("/static", StaticFiles(directory=ROOT / "gutenberg_hoard" / "static"), name="static")
from .agent_tools import router as agent_router
app.include_router(agent_router)

_gui_lock = threading.Lock()
_gui_process: subprocess.Popen | None = None
_gui_port: int | None = None


def _desktop_open(path: str) -> dict:
    global _gui_process, _gui_port
    gui, cli = designcraft_gui(), designcraft_cli()
    if gui is None or cli is None:
        raise RuntimeError("Configure the verified DesignCraft GUI and CLI executable paths.")
    with _gui_lock:
        new_process = _gui_process is None or _gui_process.poll() is not None or _gui_port is None
        if new_process:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                control_port = sock.getsockname()[1]
            runtime = paths().ensure().data_dir / "native" / "designcraft-gui-runtime"
            appdata, localdata = runtime / "appdata", runtime / "localappdata"
            appdata.mkdir(parents=True, exist_ok=True)
            localdata.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, APPDATA=str(appdata), LOCALAPPDATA=str(localdata))
            _gui_process = subprocess.Popen([str(gui), "--control", str(control_port)], cwd=str(gui.parent), env=env,
                                            close_fds=True)
            _gui_port = control_port
            timeout = 25
        else:
            env = dict(os.environ)
            timeout = 15
            control_port = _gui_port
        deadline = time.monotonic() + timeout
        last_error = "control channel did not respond"
        while time.monotonic() < deadline and _gui_process is not None and _gui_process.poll() is None:
            command = subprocess.run([str(cli), "app", "--port", str(control_port), "file.open",
                                      json.dumps({"path": path})], capture_output=True, text=True,
                                      timeout=3, env=env, check=False)
            if command.returncode == 0:
                try:
                    result = json.loads(command.stdout)
                except ValueError:
                    result = {"result": command.stdout[-500:]}
                return {"opened": True, "executable": str(gui), "control_port": control_port, "result": result}
            last_error = command.stderr[-800:]
            if not new_process:
                break
            time.sleep(.5)
        if new_process:
            _gui_process = None
            _gui_port = None
        raise RuntimeError("DesignCraft could not open the publication over its documented control channel: " + last_error)


class CreatePublication(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    pages: int = Field(default=4, ge=1, le=300)
    preset: str = "A4"
    facing_pages: bool = False
    margins: float = Field(default=36, ge=0, le=200)
    colour_space: str = "RGB"


class NativeCalls(BaseModel):
    actions: list[dict] = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, max_length=100)


class PdfExport(BaseModel):
    scale: float = Field(default=1.5, ge=0.5, le=4)


class ProfileSelection(BaseModel):
    name: str = Field(max_length=120)


class ParentAssignment(BaseModel):
    page: int = Field(ge=0)
    parent: str | None = Field(default=None, max_length=40)


class CmykSwatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    c: float = Field(ge=0, le=100)
    m: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    k: float = Field(ge=0, le=100)


class NativeCliCall(BaseModel):
    command: str = Field(min_length=1, max_length=40)
    argv: list[str] = Field(default_factory=list, max_length=200)
    timeout_s: float = Field(default=120, ge=1, le=600)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (ROOT / "gutenberg_hoard" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(ROOT / "app-icon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def health() -> dict:
    exe = designcraft_cli()
    return {"service": "gutenbergs-hoard", "ok": True, "designcraft": str(exe) if exe else None,
            "configured": bool(exe), "shared_package": "hoard-link", "hoard_link": family_health_block()}


@app.get("/api/config")
def get_config() -> dict:
    app_paths = paths().ensure()
    return {"app": "gutenberg", "data_dir": str(app_paths.data_dir), "data_configured": app_paths.configured,
            "designcraft_cli": str(designcraft_cli()) if designcraft_cli() else None,
            "designcraft_gui": str(designcraft_gui()) if designcraft_gui() else None,
            "native_format": ".designcraft", "pdf_export": {"available": True, "kind": "multipage raster",
            "searchable_text": False, "colour_space": "RGB", "pdf_x": False}}


@app.get("/api/profiles")
def profiles() -> dict:
    """Read profiles from Hoard Hub; profiles are work contexts, never user accounts."""
    p = paths().ensure()
    configure_family("gutenberg", str(p.data_dir), token_file=str(p.token_path))
    try:
        token = p.token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    status, body = fetch(hub_url() + "/api/profiles", timeout=1.5,
                         headers={"Authorization": "Bearer " + token} if token else {})
    names = []
    if status == 200 and isinstance(body, dict):
        names = [str(item.get("name")) for item in body.get("profiles", []) if isinstance(item, dict) and item.get("name")]
    return {"available": status == 200, "profiles": names, "selected": store.setting("selected_profile"),
            "source": "Hoard Hub" if status == 200 else None}


@app.post("/api/profiles/selected")
def select_profile(payload: ProfileSelection) -> dict:
    available = profiles()
    if payload.name and (not available["available"] or payload.name not in available["profiles"]):
        raise HTTPException(400, "Choose a profile returned by the connected Hoard Hub.")
    store.set_setting("selected_profile", payload.name)
    return {"selected": payload.name, "context_only": True}


@app.get("/api/publications")
def publications() -> list[dict]:
    return store.list_publications()


@app.post("/api/publications")
def create_publication(payload: CreatePublication) -> dict:
    return _run(lambda: publishing.create_publication(payload.title, payload.pages, payload.preset,
                  payload.facing_pages, payload.margins, payload.colour_space))


@app.get("/api/publications/{publication_id}")
def publication(publication_id: str) -> dict:
    return _run(lambda: {**store.get_publication(publication_id), "undo_available": store.has_history(publication_id)})


@app.post("/api/publications/{publication_id}/native-actions")
def native_actions(publication_id: str, payload: NativeCalls) -> dict:
    return _run(lambda: publishing.native_actions(publication_id, payload.actions, payload.session_id))


@app.get("/api/publications/{publication_id}/inspection")
def inspection(publication_id: str) -> dict:
    return _run(lambda: publishing.inspect_publication(publication_id))


@app.get("/api/publications/{publication_id}/stories/{story_id}")
def story(publication_id: str, story_id: int) -> dict:
    return _run(lambda: publishing.get_story(publication_id, story_id))


@app.post("/api/publications/{publication_id}/parent")
def assign_parent(publication_id: str, payload: ParentAssignment) -> dict:
    return _run(lambda: publishing.native_actions(publication_id, [{"name": "execute", "arguments": {
        "command": "layout.pages.applyParent", "params": {"pages": [payload.page], "parent": payload.parent}}}]))


@app.post("/api/publications/{publication_id}/swatches")
def create_swatch(publication_id: str, payload: CmykSwatch) -> dict:
    return _run(lambda: publishing.native_actions(publication_id, [{"name": "execute", "arguments": {
        "command": "swatch.create", "params": {"name": payload.name,
        "color": {"c": payload.c, "m": payload.m, "y": payload.y, "k": payload.k}}}}]))


@app.post("/api/publications/{publication_id}/undo")
def undo(publication_id: str) -> dict:
    return _run(lambda: publishing.undo(publication_id))


@app.post("/api/publications/{publication_id}/source")
def attach_source(publication_id: str, payload: dict) -> dict:
    def action():
        from hoard_link.artifacts import parse_ref
        from hoard_link import fam_refs
        pub = store.get_publication(publication_id)
        ref = parse_ref(str(payload.get("source", "")))
        p = paths().ensure()
        configure_family("gutenberg", str(p.data_dir), token_file=str(p.token_path))
        own = f"hoard://gutenberg/publication/{publication_id}"
        return fam_refs.link(own, ref.uri, "laid_out_from", from_label=pub["title"], to_label=f"{ref.kind} {ref.id}")
    return _run(action)


@app.get("/api/native/commands")
def native_commands() -> dict:
    return _run(lambda: {"commands": native.command_catalog()})


@app.get("/api/native/cli-info")
def native_cli_info() -> dict:
    return _run(native.cli_help)


@app.post("/api/native/cli")
def native_cli(payload: NativeCliCall) -> dict:
    return _run(lambda: native.cli_call(payload.command, payload.argv, payload.timeout_s))


@app.get("/api/publications/{publication_id}/pages/{page}/preview")
def preview(publication_id: str, page: int, scale: float = 1) -> FileResponse:
    result = _run(lambda: publishing.render_page(publication_id, page, scale))
    return FileResponse(result["path"], media_type="image/png", filename=Path(result["path"]).name)


@app.post("/api/publications/{publication_id}/export/pdf")
def export_pdf(publication_id: str, payload: PdfExport) -> dict:
    return _run(lambda: publishing.export_pdf(publication_id, payload.scale))


@app.get("/api/files/{filename}")
def file(filename: str) -> FileResponse:
    target = store.publication_dir() / filename
    if target.name != filename or target.resolve().parent != store.publication_dir().resolve() \
            or not target.is_file() or target.suffix.lower() not in {".pdf", ".designcraft"}:
        raise HTTPException(404, "File not found")
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=mime, filename=target.name)


@app.get("/api/native/catalog")
def native_catalog() -> dict:
    return _run(native.discover)


@app.post("/api/native/session")
def native_session(payload: NativeCalls) -> dict:
    return _run(lambda: {"session_id": payload.session_id,
                         "results": native.run(payload.actions, session_id=payload.session_id)})


@app.post("/api/native/launch")
def launch_native(publication_id: str) -> dict:
    return _run(lambda: _desktop_open(store.get_publication(publication_id)["path"]))


def _run(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
